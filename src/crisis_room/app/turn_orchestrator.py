from __future__ import annotations

import re

from pydantic import BaseModel, Field

from crisis_room.agents.base import AgentOutput
from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.agents.event_creator import EventCreatorAgent
from crisis_room.agents.faction import FactionAgent
from crisis_room.agents.gamemaster import CatalogGamemasterCompiler, GamemasterCompilation
from crisis_room.agents.info_channel import PrototypeInfoChannel, RoutingResult
from crisis_room.agents.international_community import InternationalCommunityAgent
from crisis_room.app.advisor_updates import update_advisor_council
from crisis_room.app.backchannels import (
    build_formal_backchannel_response_signals,
    update_backchannel_threads,
)
from crisis_room.app.chief_of_staff import ChiefReviewResult, review_chief_plan
from crisis_room.app.presentation import (
    TurnAftermathReport,
    TurnBriefing,
    build_turn_aftermath_report,
    build_turn_briefing,
)
from crisis_room.app.runtime_helpers import (
    format_advisor_retry_error,
    llm_call_count,
    llm_call_records,
)
from crisis_room.config.gameplay import HARD_ACTION_BUDGET, NORMAL_ACTION_BUDGET
from crisis_room.engine.actions import ActionDefinition, ActionPackage, ScenarioCapability
from crisis_room.engine.adjudication import DeterministicEngineV2, DeterministicTurnResult
from crisis_room.engine.batch_validation import (
    BatchValidationReport,
    build_batch_validation_report,
)
from crisis_room.llm.contracts import LLMCallRecord, LLMClient
from crisis_room.llm.diagnostics import LlamaCppJSONError
from crisis_room.llm.task_contracts import AdvisorCouncilResponse
from crisis_room.llm.task_contracts import EventCandidate
from crisis_room.scenario.endings import (
    EndingEvaluation,
    ScenarioEndingDefinition,
    evaluate_ending_events,
)
from crisis_room.scenario.event_choices import update_event_choices_from_actions
from crisis_room.scenario.events import (
    ScenarioEventDefinition,
    ScenarioEventResolution,
    ScenarioEventSettings,
    resolve_scenario_events,
)
from crisis_room.scenario.pressure import (
    HiddenObligation,
    PressureResolution,
    PressureRule,
    apply_scenario_pressure,
)
from crisis_room.state.advisors import AdvisorCouncilUpdate
from crisis_room.state.backchannels import BackchannelThreadUpdate
from crisis_room.state.signals import Signal
from crisis_room.state.world import EntityState, EntityType, WorldStateV2


RECOVERABLE_PLAYER_ACTION_TEXT = (
    "I could not turn that into a valid action. Please reword it or name the "
    "action and target more directly.\n"
    "The turn has not advanced."
)


class RecoverablePlayerActionError(ValueError):
    """Player can retry a failed formal action without advancing the turn."""


class RecoverableAdvisorDialogueError(ValueError):
    """Player can retry a failed advisor prompt without advancing the turn."""


class TurnDebugTranscript(BaseModel):
    scenario_id: str
    start_turn: int
    end_turn: int
    player_entity_id: str
    player_message: str = ""
    player_intent: str = ""
    start_routing_result: RoutingResult
    dialogue_response: AdvisorCouncilResponse | None = None
    player_compilation: GamemasterCompilation
    player_briefing: TurnBriefing | None = None
    aftermath_report: TurnAftermathReport | None = None
    advisor_update: AdvisorCouncilUpdate | None = None
    backchannel_update: BackchannelThreadUpdate | None = None
    batch_validation_report: BatchValidationReport | None = None
    pressure_resolution: PressureResolution | None = None
    scenario_event_result: ScenarioEventResolution | None = None
    ending_result: EndingEvaluation | None = None
    chief_review: ChiefReviewResult | None = None
    agent_outputs: dict[str, AgentOutput] = Field(default_factory=dict)
    event_output: AgentOutput | None = None
    deterministic_result: DeterministicTurnResult
    final_routing_result: RoutingResult
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    rendered_text: str = ""


class OrchestratedTurnResult(BaseModel):
    world_state: WorldStateV2
    start_routing_result: RoutingResult
    dialogue_response: AdvisorCouncilResponse | None = None
    player_compilation: GamemasterCompilation
    player_briefing: TurnBriefing
    aftermath_report: TurnAftermathReport
    advisor_update: AdvisorCouncilUpdate | None = None
    backchannel_update: BackchannelThreadUpdate | None = None
    batch_validation_report: BatchValidationReport | None = None
    pressure_resolution: PressureResolution | None = None
    scenario_event_result: ScenarioEventResolution | None = None
    ending_result: EndingEvaluation | None = None
    chief_review: ChiefReviewResult | None = None
    agent_outputs: dict[str, AgentOutput] = Field(default_factory=dict)
    event_output: AgentOutput | None = None
    deterministic_result: DeterministicTurnResult
    final_routing_result: RoutingResult
    debug_transcript: TurnDebugTranscript


class TurnOrchestrator:
    """Run one complete debug turn through agents, engine, and info channel."""

    def __init__(
        self,
        *,
        action_catalog: list[ActionDefinition],
        capabilities: list[ScenarioCapability] | None = None,
        llm_client: LLMClient,
        scenario_events: list[ScenarioEventDefinition] | None = None,
        scenario_endings: list[ScenarioEndingDefinition] | None = None,
        pressure_rules: list[PressureRule] | None = None,
        hidden_obligations: list[HiddenObligation] | None = None,
        event_settings: ScenarioEventSettings | None = None,
        info_channel: PrototypeInfoChannel | None = None,
        action_budget: int = NORMAL_ACTION_BUDGET,
        hard_action_limit: int = HARD_ACTION_BUDGET,
        enable_chief_of_staff: bool = False,
    ) -> None:
        self.action_budget = action_budget
        self.hard_action_limit = hard_action_limit
        self.enable_chief_of_staff = enable_chief_of_staff
        self.action_catalog = action_catalog
        self.capabilities = capabilities or []
        self.scenario_events = [event.model_copy(deep=True) for event in scenario_events or []]
        self.scenario_endings = [
            ending.model_copy(deep=True) for ending in scenario_endings or []
        ]
        self.pressure_rules = [rule.model_copy(deep=True) for rule in pressure_rules or []]
        self.hidden_obligations = [
            obligation.model_copy(deep=True)
            for obligation in hidden_obligations or []
        ]
        self.event_settings = event_settings or ScenarioEventSettings()
        self.llm_client = llm_client
        self.info_channel = info_channel or PrototypeInfoChannel(llm_client=llm_client)
        self.engine = DeterministicEngineV2(action_catalog, self.capabilities)
        self.dialogue_engine = DialogueEngineAgent(
            action_catalog=action_catalog,
            capabilities=self.capabilities,
        )
        self.gamemaster = CatalogGamemasterCompiler(
            action_catalog,
            llm_client,
            self.capabilities,
            action_budget=action_budget,
            hard_action_limit=hard_action_limit,
        )
        self.event_creator = EventCreatorAgent()

    def initialize_chief_plan(
        self,
        world_state: WorldStateV2,
        *,
        player_entity_id: str,
    ) -> ChiefReviewResult | None:
        if not self.enable_chief_of_staff or world_state.chief_plan is not None:
            return None
        return review_chief_plan(
            world_state,
            player_entity_id=player_entity_id,
            action_catalog=self.action_catalog,
            capabilities=self.capabilities,
            llm_client=self.llm_client,
            action_budget=self.action_budget,
            review_turn=world_state.turn_number,
        )

    def run_turn(
        self,
        world_state: WorldStateV2,
        *,
        player_entity_id: str,
        player_intent: str,
        player_message: str = "",
        scenario_notes: list[str] | None = None,
        precompiled_player_compilation: GamemasterCompilation | None = None,
        allow_empty_player_action: bool = False,
    ) -> OrchestratedTurnResult:
        start_turn = world_state.turn_number
        llm_call_start = llm_call_count(self.llm_client)
        start_routing_result = self.info_channel.route_signals(world_state, [])
        working_world = start_routing_result.world_state
        player_briefing = build_turn_briefing(
            working_world,
            player_entity_id=player_entity_id,
            action_catalog=self.action_catalog,
            capabilities=self.capabilities,
            action_budget=self.action_budget,
        )

        dialogue_response = None
        if player_message.strip():
            try:
                dialogue_response = self.dialogue_engine.respond_to_player(
                    working_world,
                    player_entity_id=player_entity_id,
                    player_message=player_message,
                    llm_client=self.llm_client,
                    json_retries=1,
                )
            except LlamaCppJSONError as exc:
                raise RecoverableAdvisorDialogueError(
                    format_advisor_retry_error(exc)
                ) from exc

        if precompiled_player_compilation is None:
            player_compilation = self.gamemaster.compile_player_intent(
                working_world,
                player_entity_id,
                player_intent,
            )
        else:
            player_compilation = precompiled_player_compilation.model_copy(deep=True)

        player_action_packages = (
            [] if player_compilation.rejected else list(player_compilation.action_packages)
        )
        valid_player_action_count, player_validation_errors = self._validate_player_actions(
            working_world,
            player_action_packages,
        )
        if not allow_empty_player_action and valid_player_action_count == 0:
            raise RecoverablePlayerActionError(
                _recoverable_player_action_message(
                    player_compilation,
                    player_validation_errors,
                )
            )

        action_packages: list[ActionPackage] = []
        action_packages.extend(player_action_packages)

        agent_outputs, agent_signals = self._run_entity_agents(
            working_world,
            player_entity_id=player_entity_id,
        )
        for output in agent_outputs.values():
            if output.action_package is not None:
                action_packages.append(output.action_package)

        action_packages = _stable_action_packages(
            action_packages,
            turn_number=working_world.turn_number,
        )

        emitted_signals = [*agent_signals]
        batch_validation_report = build_batch_validation_report(
            working_world,
            action_packages,
            self.action_catalog,
            player_entity_id=player_entity_id,
            capabilities=self.capabilities,
            action_budget=self.action_budget,
        )

        deterministic_result = self.engine.resolve_actions(
            working_world,
            action_packages,
        )
        formal_backchannel_response_signals = build_formal_backchannel_response_signals(
            deterministic_result.world_state,
            deterministic_result=deterministic_result,
        )
        final_routing_result = self.info_channel.route_signals(
            deterministic_result.world_state,
            [
                *deterministic_result.emitted_signals,
                *formal_backchannel_response_signals,
                *emitted_signals,
            ],
        )
        pressure_resolution = apply_scenario_pressure(
            final_routing_result.world_state,
            pressure_rules=self.pressure_rules,
            hidden_obligations=self.hidden_obligations,
            deterministic_result=deterministic_result,
        )
        final_routing_result = final_routing_result.model_copy(
            update={"world_state": pressure_resolution.world_state}
        )
        event_output = self.event_creator.create_candidate(
            final_routing_result.world_state,
            llm_client=self.llm_client,
            scenario_notes=scenario_notes,
            scenario_events=self.scenario_events,
        )
        for entry in event_output.public_timeline_delta:
            final_routing_result.world_state.public_timeline.append(entry)
        scenario_event_result = resolve_scenario_events(
            final_routing_result.world_state,
            self.scenario_events,
            deterministic_result=deterministic_result,
            player_entity_id=player_entity_id,
            framing_summary=event_output.perception_summary,
            event_settings=self.event_settings,
            event_candidate=_event_candidate_from_output(event_output),
        )
        if scenario_event_result.emitted_signals:
            scenario_event_routing_result = self.info_channel.route_signals(
                scenario_event_result.world_state,
                scenario_event_result.emitted_signals,
            )
            final_routing_result = _merge_routing_results(
                final_routing_result,
                scenario_event_routing_result,
            )
            scenario_event_result = scenario_event_result.model_copy(
                update={"world_state": final_routing_result.world_state}
            )
        else:
            final_routing_result = final_routing_result.model_copy(
                update={"world_state": scenario_event_result.world_state}
            )
        leak_event_result = resolve_scenario_events(
            final_routing_result.world_state,
            _leak_triggered_scenario_events(self.scenario_events),
            deterministic_result=deterministic_result,
            routing_result=final_routing_result,
            player_entity_id=player_entity_id,
            framing_summary=event_output.perception_summary,
        )
        if leak_event_result.fired_events:
            leak_event_routing_result = self.info_channel.route_signals(
                leak_event_result.world_state,
                leak_event_result.emitted_signals,
            )
            final_routing_result = _merge_routing_results(
                final_routing_result,
                leak_event_routing_result,
            )
            scenario_event_result = _merge_scenario_event_results(
                scenario_event_result,
                leak_event_result,
                world_state=final_routing_result.world_state,
            )
        next_world = final_routing_result.world_state
        _record_player_posture_observations(
            next_world,
            final_routing_result,
            player_entity_id=player_entity_id,
        )
        update_event_choices_from_actions(next_world, deterministic_result)
        backchannel_update = update_backchannel_threads(
            next_world,
            deterministic_result=deterministic_result,
            action_catalog=self.action_catalog,
            capabilities=self.capabilities,
            player_entity_id=player_entity_id,
        )
        advisor_update = update_advisor_council(
            next_world,
            before_world_state=working_world,
            player_entity_id=player_entity_id,
            action_catalog=self.action_catalog,
            capabilities=self.capabilities,
            deterministic_result=deterministic_result,
            agent_outputs=agent_outputs,
            council_response=dialogue_response,
            event_output=event_output,
            final_routing_result=final_routing_result,
        )
        ending_result = None
        if self.scenario_endings:
            ending_result = evaluate_ending_events(
                next_world,
                self.scenario_endings,
                player_entity_id=player_entity_id,
            )
            next_world = ending_result.world_state
            final_routing_result = final_routing_result.model_copy(
                update={"world_state": next_world}
            )
            scenario_event_result = _merge_ending_result(
                scenario_event_result,
                ending_result,
                world_state=next_world,
            )
        chief_review = None
        if self.enable_chief_of_staff:
            chief_review = review_chief_plan(
                next_world,
                player_entity_id=player_entity_id,
                action_catalog=self.action_catalog,
                capabilities=self.capabilities,
                llm_client=self.llm_client,
                action_budget=self.action_budget,
                review_turn=next_world.turn_number + 1,
                deterministic_result=deterministic_result,
            )
        aftermath_report = build_turn_aftermath_report(
            before_world_state=working_world,
            after_world_state=next_world,
            player_entity_id=player_entity_id,
            action_catalog=self.action_catalog,
            capabilities=self.capabilities,
            deterministic_result=deterministic_result,
            agent_outputs=agent_outputs,
            advisor_update=advisor_update,
            batch_validation_report=batch_validation_report,
            scenario_event_result=scenario_event_result,
            event_output=event_output,
            pressure_resolution=pressure_resolution,
            chief_updates=chief_review.update_lines if chief_review else [],
            action_budget=self.action_budget,
        )
        next_world.turn_number += 1

        rendered_text = _render_turn_debug(
            start_turn=start_turn,
            next_world=next_world,
            player_compilation=player_compilation,
            action_packages=action_packages,
            agent_outputs=agent_outputs,
            event_output=event_output,
            scenario_event_result=scenario_event_result,
            ending_result=ending_result,
            batch_validation_report=batch_validation_report,
            backchannel_update=backchannel_update,
            advisor_update=advisor_update,
            pressure_resolution=pressure_resolution,
            deterministic_result=deterministic_result,
            start_routing_result=start_routing_result,
            final_routing_result=final_routing_result,
        )
        transcript = TurnDebugTranscript(
            scenario_id=next_world.scenario_id,
            start_turn=start_turn,
            end_turn=next_world.turn_number,
            player_entity_id=player_entity_id,
            player_message=player_message,
            player_intent=player_intent,
            start_routing_result=start_routing_result,
            dialogue_response=dialogue_response,
            player_compilation=player_compilation,
            player_briefing=player_briefing,
            aftermath_report=aftermath_report,
            advisor_update=advisor_update,
            backchannel_update=backchannel_update,
            batch_validation_report=batch_validation_report,
            pressure_resolution=pressure_resolution,
            scenario_event_result=scenario_event_result,
            ending_result=ending_result,
            chief_review=chief_review,
            agent_outputs=agent_outputs,
            event_output=event_output,
            deterministic_result=deterministic_result,
            final_routing_result=final_routing_result,
            llm_calls=llm_call_records(self.llm_client, start_index=llm_call_start),
            rendered_text=rendered_text,
        )
        return OrchestratedTurnResult(
            world_state=next_world,
            start_routing_result=start_routing_result,
            dialogue_response=dialogue_response,
            player_compilation=player_compilation,
            player_briefing=player_briefing,
            aftermath_report=aftermath_report,
            advisor_update=advisor_update,
            backchannel_update=backchannel_update,
            batch_validation_report=batch_validation_report,
            pressure_resolution=pressure_resolution,
            scenario_event_result=scenario_event_result,
            ending_result=ending_result,
            chief_review=chief_review,
            agent_outputs=agent_outputs,
            event_output=event_output,
            deterministic_result=deterministic_result,
            final_routing_result=final_routing_result,
            debug_transcript=transcript,
        )

    def _run_entity_agents(
        self,
        world_state: WorldStateV2,
        *,
        player_entity_id: str,
    ) -> tuple[dict[str, AgentOutput], list[Signal]]:
        outputs: dict[str, AgentOutput] = {}
        emitted_signals: list[Signal] = []
        for entity in world_state.actors.values():
            if entity.entity_id == player_entity_id:
                continue
            output = self._run_entity_agent(entity, world_state)
            if output is None:
                continue
            outputs[entity.entity_id] = output
            emitted_signals.extend(output.emitted_signals)
        return outputs, emitted_signals

    def _run_entity_agent(
        self,
        entity: EntityState,
        world_state: WorldStateV2,
    ) -> AgentOutput | None:
        if entity.entity_type in {
            EntityType.ALLIED_FACTION,
            EntityType.OPPOSING_FACTION,
        }:
            return FactionAgent(
                entity.entity_id,
                self.action_catalog,
                self.capabilities,
            ).run_turn(
                entity,
                world_state,
                self.llm_client,
            )
        if entity.entity_type == EntityType.INTERNATIONAL_COMMUNITY:
            return InternationalCommunityAgent(entity.entity_id).run_turn(
                entity,
                world_state,
                self.llm_client,
            )
        return None

    def _validate_player_actions(
        self,
        world_state: WorldStateV2,
        action_packages: list[ActionPackage],
    ) -> tuple[int, list[str]]:
        valid_count = 0
        errors: list[str] = []
        for package in action_packages:
            validation = self.engine.validate_action(world_state, package)
            if validation.is_valid:
                valid_count += 1
            else:
                errors.extend(validation.errors)
        return valid_count, errors


def _leak_triggered_scenario_events(
    scenario_events: list[ScenarioEventDefinition],
) -> list[ScenarioEventDefinition]:
    return [
        event
        for event in scenario_events
        if event.trigger.required_any_leaked_signal_action_ids
        or event.trigger.required_any_leaked_signal_capability_ids
    ]


def _stable_action_packages(
    packages: list[ActionPackage],
    *,
    turn_number: int,
) -> list[ActionPackage]:
    return [
        package.model_copy(
            deep=True,
            update={
                "package_id": (
                    f"pkg_{turn_number}_{index}_"
                    f"{_stable_id_part(package.actor_id)}_"
                    f"{_stable_id_part(package.mechanical_id)}"
                )
            },
        )
        for index, package in enumerate(packages, start=1)
    ]


def _stable_id_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "action"


def _record_player_posture_observations(
    world_state: WorldStateV2,
    routing_result: RoutingResult,
    *,
    player_entity_id: str,
) -> None:
    recipients = {
        delivery.recipient_entity_id
        for delivery in routing_result.deliveries
        if delivery.source_entity_id == player_entity_id
    }
    player = world_state.actors.get(player_entity_id)
    player_name = player.name if player is not None else player_entity_id
    for entity in world_state.actors.values():
        if entity.entity_type not in {
            EntityType.ALLIED_FACTION,
            EntityType.OPPOSING_FACTION,
        }:
            continue
        if entity.entity_id in recipients:
            continue
        world_state.append_entity_timeline(
            entity.entity_id,
            "No Visible Player Move",
            (
                f"No new formal move from {player_name} reached this actor this turn. "
                "The absence may indicate restraint, indecision, concealment, or weakness."
            ),
            source="gamemaster",
            tags=["posture", "absence_of_signal"],
        )


def _merge_routing_results(
    first: RoutingResult,
    second: RoutingResult,
) -> RoutingResult:
    return RoutingResult(
        world_state=second.world_state,
        deliveries=[*first.deliveries, *second.deliveries],
        delayed_signals=[*first.delayed_signals, *second.delayed_signals],
        leaked_signals=[*first.leaked_signals, *second.leaked_signals],
        suppressed_signal_ids=[
            *first.suppressed_signal_ids,
            *second.suppressed_signal_ids,
        ],
        contradicted_delivery_ids=[
            *first.contradicted_delivery_ids,
            *second.contradicted_delivery_ids,
        ],
        public_timeline_entry_ids=[
            *first.public_timeline_entry_ids,
            *second.public_timeline_entry_ids,
        ],
        omniscient_timeline_entry_ids=[
            *first.omniscient_timeline_entry_ids,
            *second.omniscient_timeline_entry_ids,
        ],
        trace=[*first.trace, *second.trace],
    )


def _merge_scenario_event_results(
    first: ScenarioEventResolution,
    second: ScenarioEventResolution,
    *,
    world_state: WorldStateV2,
) -> ScenarioEventResolution:
    return ScenarioEventResolution(
        world_state=world_state,
        fired_events=[*first.fired_events, *second.fired_events],
        emitted_signals=[*first.emitted_signals, *second.emitted_signals],
        no_event_reason=(
            ""
            if first.fired_events or second.fired_events
            else second.no_event_reason or first.no_event_reason
        ),
        trace=[*first.trace, *second.trace],
        framing_summary=second.framing_summary or first.framing_summary,
    )


def _merge_ending_result(
    scenario_event_result: ScenarioEventResolution,
    ending_result: EndingEvaluation,
    *,
    world_state: WorldStateV2,
) -> ScenarioEventResolution:
    fired_events = list(scenario_event_result.fired_events)
    if ending_result.event_record is not None:
        fired_events.append(ending_result.event_record)
    return ScenarioEventResolution(
        world_state=world_state,
        fired_events=fired_events,
        emitted_signals=list(scenario_event_result.emitted_signals),
        no_event_reason=(
            ""
            if fired_events
            else scenario_event_result.no_event_reason
        ),
        trace=[*scenario_event_result.trace, *ending_result.trace],
        framing_summary=scenario_event_result.framing_summary,
    )


def _event_candidate_from_output(output: AgentOutput | None) -> EventCandidate | None:
    if output is None:
        return None
    for raw in reversed(output.raw_llm_outputs):
        task = raw.get("task")
        if task not in {"event_candidate", "event_creator_response"}:
            continue
        response = raw.get("response")
        if task == "event_creator_response" and isinstance(response, dict):
            response = response.get("event_candidate")
        if response is None:
            return None
        if isinstance(response, EventCandidate):
            return response
        if isinstance(response, dict):
            return EventCandidate.model_validate(response)
    return None


def _recoverable_player_action_message(
    compilation: GamemasterCompilation,
    validation_errors: list[str],
) -> str:
    hints = _friendly_action_hints(
        [
            *compilation.errors,
            *compilation.rejected_intents,
            *validation_errors,
        ]
    )
    return "\n".join([RECOVERABLE_PLAYER_ACTION_TEXT, *hints])


def _friendly_action_hints(errors: list[str]) -> list[str]:
    hints: list[str] = []
    for error in errors:
        lowered = error.lower()
        if "requires at least" in lowered and "target" in lowered:
            _append_once(hints, "This action needs a target.")
            _append_once(
                hints,
                "Try: ACTION open a private Kremlin channel to soviet_presidium.",
            )
        elif "parameters missing required keys" in lowered and "message_text" in lowered:
            _append_once(hints, "This action needs a message.")
        elif "non-catalog" in lowered:
            _append_once(hints, "Name one listed action or capability.")
    if not hints and errors:
        hints.append("No legal action was compiled from that wording.")
    return hints[:2]


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _render_turn_debug(
    *,
    start_turn: int,
    next_world: WorldStateV2,
    player_compilation: GamemasterCompilation,
    action_packages: list[ActionPackage],
    agent_outputs: dict[str, AgentOutput],
    event_output: AgentOutput,
    scenario_event_result: ScenarioEventResolution | None,
    ending_result: EndingEvaluation | None,
    batch_validation_report: BatchValidationReport | None,
    backchannel_update: BackchannelThreadUpdate | None,
    advisor_update: AdvisorCouncilUpdate | None,
    pressure_resolution: PressureResolution | None,
    deterministic_result: DeterministicTurnResult,
    start_routing_result: RoutingResult,
    final_routing_result: RoutingResult,
) -> str:
    lines = [
        "ORCHESTRATED TURN DEBUG",
        "",
        "[turn]",
        f"- start: {start_turn}",
        f"- end: {next_world.turn_number}",
        "",
        "[start_info_channel]",
        f"- due deliveries: {len(start_routing_result.deliveries)}",
        f"- delayed remaining: {len(start_routing_result.world_state.pending_signals)}",
        "",
        "[player_gamemaster]",
        f"- rejected: {player_compilation.rejected}",
        f"- action budget: {player_compilation.action_budget}",
        f"- hard action limit: {player_compilation.hard_action_limit}",
        f"- compiled actions: {len(player_compilation.action_packages)}",
    ]
    if not player_compilation.action_packages:
        lines.append("- action: (none)")
    for package in player_compilation.action_packages:
        lines.append(f"- {package.actor_id}: {_package_label(package)} via {package.channel.value}")
    lines.extend(f"- rejected intent: {intent}" for intent in player_compilation.rejected_intents)
    lines.extend(
        f"- unprocessed intent: {intent}" for intent in player_compilation.unprocessed_intents
    )
    lines.extend(f"- error: {error}" for error in player_compilation.errors)
    lines.extend(f"- note: {note}" for note in player_compilation.notes)
    lines.extend(
        [
            "",
            "[agent_actions]",
            f"- submitted actions: {len(action_packages)}",
        ]
    )
    for package in action_packages:
        lines.append(f"- {package.actor_id}: {_package_label(package)} via {package.channel.value}")
    lines.extend(["", "[entity_agents]"])
    for entity_id, output in agent_outputs.items():
        lines.append(f"- {entity_id}: {output.perception_summary}")
        lines.append(f"  attempted action: {_attempted_action(output)}")
        if output.action_package is not None:
            lines.append(
                f"  accepted package: {_package_label(output.action_package)} "
                f"via {output.action_package.channel.value}"
            )
        for note in output.debug_notes:
            lines.append(f"  note: {note}")
    lines.extend(
        [
            "",
            "[event_creator]",
            f"- {event_output.perception_summary}",
        ]
    )
    for entry in event_output.public_timeline_delta:
        lines.append(f"- media headline: {entry.title}: {entry.summary}")
    lines.extend(
        [
            "",
            "[scenario_events]",
            f"- fired: {len(scenario_event_result.fired_events) if scenario_event_result else 0}",
        ]
    )
    if scenario_event_result is not None:
        if scenario_event_result.no_event_reason:
            lines.append(f"- no event: {scenario_event_result.no_event_reason}")
        for record in scenario_event_result.fired_events:
            lines.append(f"- {record.event_id}: {record.title}")
            lines.extend(f"  effect: {effect}" for effect in record.effect_summary)
        for item in scenario_event_result.trace:
            lines.append(f"  trace: {item}")
    lines.extend(
        [
            "",
            "[endings]",
            f"- offered: {ending_result.offer_record.ending_id if ending_result and ending_result.offer_record else '(none)'}",
        ]
    )
    if ending_result is not None:
        for item in ending_result.trace:
            lines.append(f"  trace: {item}")
    lines.extend(
        [
            "",
            "[batch_validation]",
            f"- warnings: {len(batch_validation_report.warnings) if batch_validation_report else 0}",
        ]
    )
    if batch_validation_report is not None:
        for warning in batch_validation_report.warnings:
            lines.append(f"- {warning.code}: {warning.message}")
            if warning.package_ids:
                lines.append(f"  packages: {', '.join(warning.package_ids)}")
            if warning.action_ids:
                lines.append(f"  actions: {', '.join(warning.action_ids)}")
    lines.extend(
        [
            "",
            "[backchannel_threads]",
            f"- applied: {backchannel_update is not None}",
        ]
    )
    if backchannel_update is not None:
        lines.extend(f"- {summary}" for summary in backchannel_update.summary)
        lines.append(f"- opened: {len(backchannel_update.opened_thread_ids)}")
        lines.append(f"- refreshed: {len(backchannel_update.refreshed_thread_ids)}")
        lines.append(f"- expired: {len(backchannel_update.expired_thread_ids)}")
        lines.append(f"- records: {len(backchannel_update.message_record_ids)}")
    lines.extend(
        [
            "",
            "[advisor_updates]",
            f"- applied: {advisor_update is not None}",
        ]
    )
    if advisor_update is not None:
        lines.append(f"- deltas: {len(advisor_update.deltas)}")
        lines.extend(f"- {summary}" for summary in advisor_update.summary)
        for delta in advisor_update.deltas:
            lines.append(
                f"- {delta.advisor_id}: "
                f"trust {delta.trust_player_delta:+.3f}, "
                f"urgency {delta.urgency_delta:+.3f}, "
                f"paranoia {delta.paranoia_delta:+.3f}"
            )
    lines.extend(
        [
            "",
            "[deterministic_engine]",
            f"- accepted: {len(deterministic_result.accepted_actions)}",
            f"- rejected: {len(deterministic_result.rejected_actions)}",
            f"- scheduled: {len(deterministic_result.scheduled_actions)}",
        ]
    )
    for package in deterministic_result.rejected_actions:
        validation = deterministic_result.validation_results.get(package.package_id)
        reason = "; ".join(validation.errors) if validation is not None else "unknown reason"
        lines.append(f"- rejected action: {package.actor_id}:{_package_label(package)} ({reason})")
    lines.extend(
        [
            "",
            "[scenario_pressure]",
            f"- applications: {len(pressure_resolution.applications) if pressure_resolution else 0}",
        ]
    )
    if pressure_resolution is not None:
        for application in pressure_resolution.applications:
            lines.append(f"- {application.rule_id}: {application.summary}")
            lines.extend(f"  effect: {effect}" for effect in application.effect_summary)
        for item in pressure_resolution.trace:
            lines.append(f"  trace: {item}")
    lines.extend(
        [
            "",
            "[final_info_channel]",
            f"- deliveries: {len(final_routing_result.deliveries)}",
            f"- delayed: {len(final_routing_result.delayed_signals)}",
            f"- leaked: {len(final_routing_result.leaked_signals)}",
            f"- suppressed: {len(final_routing_result.suppressed_signal_ids)}",
            "",
            "[timelines]",
            f"- public entries: {len(next_world.public_timeline.entries)}",
            f"- omniscient entries: {len(next_world.omniscient_timeline.entries)}",
            f"- entity-local timelines: {len(next_world.entity_timelines)}",
        ]
    )
    return "\n".join(lines)


def _action_id(action_package: ActionPackage | None) -> str:
    return action_package.action_id if action_package is not None else "(none)"


def _package_label(action_package: ActionPackage) -> str:
    if action_package.capability_id:
        return f"{action_package.action_id}/{action_package.capability_id}"
    return action_package.action_id


def _attempted_action(output: AgentOutput) -> str:
    if output.action_package is not None:
        return _package_label(output.action_package)
    for raw in reversed(output.raw_llm_outputs):
        task = raw.get("task")
        if task not in {"faction_decision", "faction_turn"}:
            continue
        response = raw.get("response")
        if task == "faction_turn" and isinstance(response, dict):
            response = response.get("decision")
        if isinstance(response, dict):
            action_id = response.get("action_id")
            capability_id = response.get("capability_id")
            if action_id and capability_id:
                return f"{action_id}/{capability_id}"
            return str(action_id) if action_id else "(none)"
    return "(none)"
