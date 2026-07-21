from __future__ import annotations

from crisis_room.agents.base import AgentOutput
from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.config.gameplay import FACTION_TURN_MAX_TOKENS
from crisis_room.engine.action_matching import default_targets
from crisis_room.engine.actions import (
    ActionDefinition,
    ActionPackage,
    ScenarioCapability,
)
from crisis_room.engine.adjudication import DeterministicEngineV2
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.prompts import FACTION_SYSTEM, FACTION_TASK
from crisis_room.llm.task_contracts import (
    FactionDecision,
    FactionTurnResponse,
)
from crisis_room.state.beliefs import BeliefClaim
from crisis_room.state.world import EntityState, WorldStateV2


class FactionAgent:
    """LLM-driven faction agent with a single rich perception/debate/decision call."""

    def __init__(
        self,
        entity_id: str,
        action_catalog: list[ActionDefinition],
        capabilities: list[ScenarioCapability] | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.action_catalog = action_catalog
        self.capabilities = capabilities or []
        self._catalog_by_id = {
            definition.action_id: definition for definition in action_catalog
        }
        self._capabilities_by_id = {
            capability.capability_id: capability for capability in self.capabilities
        }
        self._engine = DeterministicEngineV2(action_catalog, self.capabilities)

    def run_turn(
        self,
        entity_state: EntityState,
        world_state: WorldStateV2,
        llm_client: LLMClient,
    ) -> AgentOutput:
        visible_context = build_visible_context(
            entity_state,
            world_state,
            action_catalog=self.action_catalog,
            capabilities=self.capabilities,
        )
        turn_response = self._run_faction_turn(visible_context, world_state, llm_client)
        perception = turn_response.perception_update
        debate = turn_response.internal_debate
        decision = turn_response.decision
        action_package, packaging_notes = self._build_action_package(
            decision,
            entity_state,
            world_state,
        )
        _apply_faction_state(entity_state, turn_response, world_state.turn_number)
        state_notes = []
        if perception.belief_updates:
            state_notes.append(
                "beliefs updated: "
                + ", ".join(update.topic for update in perception.belief_updates)
            )
        if perception.memory_notes:
            state_notes.append(f"memory notes stored: {len(perception.memory_notes)}")
        if debate.dominant_narrative_id:
            state_notes.append(f"dominant narrative: {debate.dominant_narrative_id}")
        return AgentOutput(
            entity_id=entity_state.entity_id,
            perception_summary=perception.situation_summary,
            action_package=action_package,
            raw_llm_outputs=[
                {"task": "faction_turn", "response": turn_response.model_dump(mode="json")},
            ],
            debug_notes=[*packaging_notes, *state_notes, *turn_response.self_critique],
        )

    def _run_faction_turn(
        self,
        visible_context: dict[str, object],
        world_state: WorldStateV2,
        llm_client: LLMClient,
    ) -> FactionTurnResponse:
        request = build_task_request(
            label=f"faction.{self.entity_id}.turn",
            system_prompt=FACTION_SYSTEM,
            visible_context=visible_context,
            task_instruction=FACTION_TASK,
            response_schema_name="FactionTurnResponse",
            metadata={"agent": self.entity_id, "turn_number": world_state.turn_number},
            max_tokens=FACTION_TURN_MAX_TOKENS,
        )
        return llm_client.complete_json(request, FactionTurnResponse)


    def _build_action_package(
        self,
        decision: FactionDecision,
        entity_state: EntityState,
        world_state: WorldStateV2,
    ) -> tuple[ActionPackage | None, list[str]]:
        notes: list[str] = []
        if not decision.action_id:
            reason = decision.no_action_reason or "No coherent move emerged."
            return None, [reason]
        if decision.action_id not in self._catalog_by_id:
            return None, [f"decision referenced non-catalog action: {decision.action_id}"]
        if self.capabilities and not decision.capability_id:
            return None, ["decision omitted required capability_id"]
        if decision.capability_id and decision.capability_id not in self._capabilities_by_id:
            return None, [
                f"decision referenced non-catalog capability: {decision.capability_id}"
            ]

        definition = None
        if decision.capability_id:
            definition = next(
                (
                    definition
                    for definition in self._engine.resolver.resolved_capability_definitions()
                    if definition.action_id == decision.action_id
                    and definition.capability_id == decision.capability_id
                ),
                None,
            )
        intent_summary = decision.intent_summary.strip()
        if not intent_summary:
            intent_summary = definition.title if definition is not None else "No public explanation given."
            notes.append(f"Filled missing intent summary: {intent_summary}")
        target_ids = list(decision.target_ids)
        if decision.capability_id and not target_ids:
            if definition is not None:
                target_ids = default_targets(
                    world_state,
                    entity_state.entity_id,
                    definition,
                )
                if target_ids:
                    notes.append(f"Filled default target(s): {', '.join(target_ids)}")

        package = ActionPackage(
            actor_id=entity_state.entity_id,
            action_id=decision.action_id,
            capability_id=decision.capability_id,
            target_ids=target_ids,
            channel=decision.channel,
            intent_summary=intent_summary,
            public_rationale=decision.public_rationale,
            private_rationale=decision.private_rationale,
            commitment_level=decision.commitment_level,
            submitted_turn=world_state.turn_number,
            metadata={
                "created_by": "FactionAgent",
                "confidence": decision.confidence,
            },
            parameters=decision.parameters,
        )
        validation = self._engine.validate_action(world_state, package)
        if not validation.is_valid:
            return None, [f"decision failed deterministic validation: {error}" for error in validation.errors]
        if validation.warnings:
            notes.extend(f"decision validation warning: {warning}" for warning in validation.warnings)
        return package, notes


def _apply_faction_state(
    entity_state: EntityState,
    response: FactionTurnResponse,
    turn_number: int,
) -> None:
    perception = response.perception_update
    entity_state.beliefs.summary = perception.situation_summary
    entity_state.beliefs.last_updated_turn = max(
        entity_state.beliefs.last_updated_turn,
        turn_number,
    )
    known_signal_ids = {delivery.signal_id for delivery in entity_state.inbox}
    for update in perception.belief_updates:
        entity_state.beliefs.upsert_claim(
            BeliefClaim(
                topic=update.topic,
                summary=update.summary,
                confidence=update.confidence,
                source_signal_ids=[
                    signal_id
                    for signal_id in update.source_signal_ids
                    if signal_id in known_signal_ids
                ],
                last_updated_turn=turn_number,
            )
        )
    if perception.uncertainty_notes:
        notes = [
            *entity_state.beliefs.uncertainty_notes,
            *perception.uncertainty_notes,
        ]
        entity_state.beliefs.uncertainty_notes = list(dict.fromkeys(notes))[-8:]
    unresolved = [
        *entity_state.unresolved_threads,
        *perception.priority_questions,
        *response.internal_debate.unresolved_disagreements,
    ]
    entity_state.unresolved_threads = list(dict.fromkeys(unresolved))[-8:]
    if perception.memory_notes:
        notes = [
            *[item.strip() for item in entity_state.memory_summary.split(" | ") if item.strip()],
            *[item.strip() for item in perception.memory_notes if item.strip()],
        ]
        entity_state.memory_summary = " | ".join(list(dict.fromkeys(notes))[-8:])[-700:]
        entity_state.beliefs.last_updated_turn = max(
            entity_state.beliefs.last_updated_turn,
            turn_number,
        )

    debate = response.internal_debate
    positions = {position.narrative_id: position for position in debate.positions}
    dominant_id = debate.dominant_narrative_id
    for narrative in entity_state.internal_narratives:
        position = positions.get(narrative.narrative_id)
        if position is None:
            continue
        narrative.current_argument = position.argument
        narrative.influence_weight = position.confidence
        if narrative.narrative_id == dominant_id:
            narrative.recent_wins = _bounded_unique(
                narrative.recent_wins,
                debate.synthesis,
            )
        elif dominant_id:
            narrative.recent_losses = _bounded_unique(
                narrative.recent_losses,
                debate.synthesis,
            )


def _bounded_unique(values: list[str], value: str, limit: int = 6) -> list[str]:
    if not value.strip():
        return values[-limit:]
    return list(dict.fromkeys([*values, value.strip()]))[-limit:]
