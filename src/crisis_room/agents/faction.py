from __future__ import annotations

from crisis_room.agents.base import AgentOutput
from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.config.gameplay import (
    FACTION_DEBATE_MAX_TOKENS,
    FACTION_DECISION_MAX_TOKENS,
    FACTION_PERCEPTION_MAX_TOKENS,
    FACTION_TURN_MAX_TOKENS,
    NESTED_LLM_CONTEXT_LIMIT,
)
from crisis_room.engine.actions import ActionDefinition, ActionPackage, ScenarioCapability
from crisis_room.engine.adjudication import DeterministicEngineV2
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.task_contracts import (
    FactionDecision,
    FactionTurnResponse,
    InternalDebate,
    PerceptionUpdate,
)
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
        return AgentOutput(
            entity_id=entity_state.entity_id,
            perception_summary=perception.situation_summary,
            internal_debate=[
                position.argument for position in debate.positions
            ] + [debate.synthesis],
            action_package=action_package,
            raw_llm_outputs=[
                {"task": "faction_turn", "response": turn_response.model_dump(mode="json")},
                {"task": "perception_update", "response": perception.model_dump(mode="json")},
                {"task": "internal_debate", "response": debate.model_dump(mode="json")},
                {"task": "faction_decision", "response": decision.model_dump(mode="json")},
            ],
            debug_notes=[*packaging_notes, *turn_response.self_critique],
        )

    def _run_faction_turn(
        self,
        visible_context: dict[str, object],
        world_state: WorldStateV2,
        llm_client: LLMClient,
    ) -> FactionTurnResponse:
        request = build_task_request(
            label=f"faction.{self.entity_id}.turn",
            system_prompt=(
                "You are a faction crisis-room cell. In one structured response, "
                "simulate how this entity perceives the turn, argues with itself, "
                "red-teams the tempting options, and settles on a legal catalog "
                "action or a deliberate no-action choice. Use only visible context."
            ),
            visible_context=visible_context,
            task_instruction=(
                "Return a FactionTurnResponse. First produce an entity-local "
                "perception_update grounded in visible public timeline, local "
                "timeline, inbox, beliefs, resources, public metrics, and known "
                "commitments. Then produce an internal_debate with distinct "
                "narrative positions that disagree over interpretation, timing, "
                "risk, credibility, off-ramps, red lines, or restraint; include "
                "preferred visible action_id and capability_id values when a "
                "position has one. The synthesis must explain what tradeoff won. "
                "Finally produce decision using only visible generic action ids, "
                "capability ids, target ids, allowed channels, and parameter keys. "
                "If no legal catalog action fits, leave action_id and capability_id "
                "null, target_ids empty, and explain no_action_reason. Use "
                "self_critique for doubts or red-team objections that made the "
                "decision more cautious. Do not claim deterministic effects have "
                "already happened."
            ),
            response_schema_name="FactionTurnResponse",
            metadata={"agent": self.entity_id, "turn_number": world_state.turn_number},
            max_tokens=FACTION_TURN_MAX_TOKENS,
        )
        return llm_client.complete_json(request, FactionTurnResponse)

    def _run_perception(
        self,
        visible_context: dict[str, object],
        world_state: WorldStateV2,
        llm_client: LLMClient,
    ) -> PerceptionUpdate:
        request = build_task_request(
            label=f"faction.{self.entity_id}.perception_update",
            system_prompt=(
                "You are a faction perception cell in a political-military crisis. "
                "Interpret only the provided inbox, public timeline, local timeline, "
                "beliefs, and public metrics."
            ),
            visible_context=visible_context,
            task_instruction=(
                "Produce an entity-local perception update. Identify changed beliefs, "
                "uncertainties, memory notes, and priority questions without claiming "
                "omniscient knowledge. Keep the situation_summary concise and tie "
                "belief updates to visible public timeline, local timeline, inbox, "
                "or belief context."
            ),
            response_schema_name="PerceptionUpdate",
            metadata={"agent": self.entity_id, "turn_number": world_state.turn_number},
            max_tokens=FACTION_PERCEPTION_MAX_TOKENS,
        )
        return llm_client.complete_json(request, PerceptionUpdate)

    def _run_debate(
        self,
        visible_context: dict[str, object],
        perception: PerceptionUpdate,
        world_state: WorldStateV2,
        llm_client: LLMClient,
    ) -> InternalDebate:
        debate_context = dict(visible_context)
        debate_context["perception_update"] = _compact_perception_context(perception)
        request = build_task_request(
            label=f"faction.{self.entity_id}.internal_debate",
            system_prompt=(
                "You are modeling internal faction disagreement. Each internal "
                "narrative should argue from its worldview, preferred strategy, "
                "fears, red lines, and the entity's visible information."
            ),
            visible_context=debate_context,
            task_instruction=(
                "Generate the competing narrative positions and a synthesis. "
                "Preferred actions must refer to visible generic action ids and "
                "capability ids when possible. "
                "Make each position argue a different interpretation of risk, red "
                "lines, timing, or restraint rather than repeating the same stance."
            ),
            response_schema_name="InternalDebate",
            metadata={"agent": self.entity_id, "turn_number": world_state.turn_number},
            max_tokens=FACTION_DEBATE_MAX_TOKENS,
        )
        return llm_client.complete_json(request, InternalDebate)

    def _run_decision(
        self,
        visible_context: dict[str, object],
        perception: PerceptionUpdate,
        debate: InternalDebate,
        world_state: WorldStateV2,
        llm_client: LLMClient,
    ) -> FactionDecision:
        decision_context = dict(visible_context)
        decision_context["perception_update"] = _compact_perception_context(perception)
        decision_context["internal_debate"] = _compact_debate_context(debate)
        request = build_task_request(
            label=f"faction.{self.entity_id}.faction_decision",
            system_prompt=(
                "You are a faction decision cell. Choose a legal catalog action "
                "or explicitly choose no action. You propose intent; deterministic "
                "code will decide legality and effects."
            ),
            visible_context=decision_context,
            task_instruction=(
                "Return the final faction decision. Use action_id only from the "
                "visible generic action ids, capability_id only from visible "
                "capabilities, target_ids only from visible entity ids, parameters "
                "only from the capability schema, and a channel allowed by that "
                "capability. If no catalog action fits, leave action_id and "
                "capability_id null and explain no_action_reason. Private rationale "
                "may use this entity's goals and debate, but do not claim that the "
                "action has already succeeded."
            ),
            response_schema_name="FactionDecision",
            metadata={"agent": self.entity_id, "turn_number": world_state.turn_number},
            max_tokens=FACTION_DECISION_MAX_TOKENS,
        )
        return llm_client.complete_json(request, FactionDecision)

    def _build_action_package(
        self,
        decision: FactionDecision,
        entity_state: EntityState,
        world_state: WorldStateV2,
    ) -> tuple[ActionPackage | None, list[str]]:
        notes: list[str] = []
        if not decision.action_id:
            reason = decision.no_action_reason or "faction decision selected no action"
            return None, [reason]
        if decision.action_id not in self._catalog_by_id:
            return None, [f"decision referenced non-catalog action: {decision.action_id}"]
        if self.capabilities and not decision.capability_id:
            return None, ["decision omitted required capability_id"]
        if decision.capability_id and decision.capability_id not in self._capabilities_by_id:
            return None, [
                f"decision referenced non-catalog capability: {decision.capability_id}"
            ]
        if not decision.intent_summary.strip():
            return None, ["decision intent_summary is empty"]

        package = ActionPackage(
            actor_id=entity_state.entity_id,
            action_id=decision.action_id,
            capability_id=decision.capability_id,
            target_ids=decision.target_ids,
            channel=decision.channel,
            intent_summary=decision.intent_summary,
            public_rationale=decision.public_rationale,
            private_rationale=decision.private_rationale,
            requested_timing=decision.requested_timing,
            commitment_level=decision.commitment_level,
            risk_acceptance=decision.risk_acceptance,
            fallback_condition=decision.fallback_condition,
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


def _compact_perception_context(perception: PerceptionUpdate) -> dict[str, object]:
    belief_updates = perception.belief_updates[:NESTED_LLM_CONTEXT_LIMIT]
    uncertainty_notes = perception.uncertainty_notes[:NESTED_LLM_CONTEXT_LIMIT]
    memory_notes = perception.memory_notes[:NESTED_LLM_CONTEXT_LIMIT]
    priority_questions = perception.priority_questions[:NESTED_LLM_CONTEXT_LIMIT]
    return {
        "situation_summary": perception.situation_summary,
        "belief_updates": [
            update.model_dump(mode="json") for update in belief_updates
        ],
        "uncertainty_notes": uncertainty_notes,
        "memory_notes": memory_notes,
        "priority_questions": priority_questions,
        "nested_context_limits": {
            "item_limit": NESTED_LLM_CONTEXT_LIMIT,
            "belief_updates_total": len(perception.belief_updates),
            "belief_updates_truncated": len(belief_updates) < len(perception.belief_updates),
            "uncertainty_notes_total": len(perception.uncertainty_notes),
            "uncertainty_notes_truncated": len(uncertainty_notes) < len(perception.uncertainty_notes),
            "memory_notes_total": len(perception.memory_notes),
            "memory_notes_truncated": len(memory_notes) < len(perception.memory_notes),
            "priority_questions_total": len(perception.priority_questions),
            "priority_questions_truncated": len(priority_questions) < len(perception.priority_questions),
        },
    }


def _compact_debate_context(debate: InternalDebate) -> dict[str, object]:
    positions = debate.positions[:NESTED_LLM_CONTEXT_LIMIT]
    unresolved = debate.unresolved_disagreements[:NESTED_LLM_CONTEXT_LIMIT]
    return {
        "positions": [position.model_dump(mode="json") for position in positions],
        "synthesis": debate.synthesis,
        "dominant_narrative_id": debate.dominant_narrative_id,
        "unresolved_disagreements": unresolved,
        "nested_context_limits": {
            "item_limit": NESTED_LLM_CONTEXT_LIMIT,
            "positions_total": len(debate.positions),
            "positions_truncated": len(positions) < len(debate.positions),
            "unresolved_disagreements_total": len(debate.unresolved_disagreements),
            "unresolved_disagreements_truncated": len(unresolved) < len(debate.unresolved_disagreements),
        },
    }
