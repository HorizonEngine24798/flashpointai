from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.agents.base import AgentOutput
from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.agents.event_creator import EventCreatorAgent
from crisis_room.agents.faction import FactionAgent
from crisis_room.agents.gamemaster import CatalogGamemasterCompiler, GamemasterCompilation
from crisis_room.agents.info_channel import PrototypeInfoChannel, RoutingResult
from crisis_room.agents.international_community import InternationalCommunityAgent
from crisis_room.app.advisor_updates import update_advisor_council
from crisis_room.app.backchannels import update_backchannel_threads
from crisis_room.app.presentation import (
    TurnAftermathReport,
    TurnBriefing,
    build_turn_aftermath_report,
    build_turn_briefing,
)
from crisis_room.engine.actions import ActionDefinition, ActionPackage
from crisis_room.engine.adjudication import DeterministicEngineV2, DeterministicTurnResult
from crisis_room.engine.batch_validation import (
    BatchValidationReport,
    build_batch_validation_report,
)
from crisis_room.llm.contracts import LLMCallRecord, LLMClient
from crisis_room.llm.task_contracts import AdvisorResponse
from crisis_room.scenario.events import (
    ScenarioEventDefinition,
    ScenarioEventResolution,
    resolve_scenario_events,
)
from crisis_room.state.advisors import AdvisorCouncilUpdate
from crisis_room.state.backchannels import BackchannelThreadUpdate
from crisis_room.state.signals import Signal
from crisis_room.state.world import EntityState, EntityType, WorldStateV2


class TurnDebugTranscript(BaseModel):
    scenario_id: str
    start_turn: int
    end_turn: int
    player_entity_id: str
    player_message: str = ""
    player_intent: str = ""
    start_routing_result: RoutingResult
    dialogue_response: AdvisorResponse | None = None
    player_compilation: GamemasterCompilation
    player_briefing: TurnBriefing | None = None
    aftermath_report: TurnAftermathReport | None = None
    advisor_update: AdvisorCouncilUpdate | None = None
    backchannel_update: BackchannelThreadUpdate | None = None
    batch_validation_report: BatchValidationReport | None = None
    scenario_event_result: ScenarioEventResolution | None = None
    agent_outputs: dict[str, AgentOutput] = Field(default_factory=dict)
    event_output: AgentOutput | None = None
    deterministic_result: DeterministicTurnResult
    final_routing_result: RoutingResult
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    rendered_text: str = ""


class OrchestratedTurnResult(BaseModel):
    world_state: WorldStateV2
    start_routing_result: RoutingResult
    dialogue_response: AdvisorResponse | None = None
    player_compilation: GamemasterCompilation
    player_briefing: TurnBriefing
    aftermath_report: TurnAftermathReport
    advisor_update: AdvisorCouncilUpdate | None = None
    backchannel_update: BackchannelThreadUpdate | None = None
    batch_validation_report: BatchValidationReport | None = None
    scenario_event_result: ScenarioEventResolution | None = None
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
        llm_client: LLMClient,
        scenario_events: list[ScenarioEventDefinition] | None = None,
        info_channel: PrototypeInfoChannel | None = None,
    ) -> None:
        self.action_catalog = action_catalog
        self.scenario_events = [event.model_copy(deep=True) for event in scenario_events or []]
        self.llm_client = llm_client
        self.info_channel = info_channel or PrototypeInfoChannel()
        self.engine = DeterministicEngineV2(action_catalog)
        self.dialogue_engine = DialogueEngineAgent(action_catalog=action_catalog)
        self.gamemaster = CatalogGamemasterCompiler(action_catalog, llm_client)
        self.event_creator = EventCreatorAgent()

    def run_turn(
        self,
        world_state: WorldStateV2,
        *,
        player_entity_id: str,
        player_intent: str,
        player_message: str = "",
        scenario_notes: list[str] | None = None,
        precompiled_player_compilation: GamemasterCompilation | None = None,
    ) -> OrchestratedTurnResult:
        start_turn = world_state.turn_number
        llm_call_start = _llm_call_count(self.llm_client)
        start_routing_result = self.info_channel.route_signals(world_state, [])
        working_world = start_routing_result.world_state
        player_briefing = build_turn_briefing(
            working_world,
            player_entity_id=player_entity_id,
            action_catalog=self.action_catalog,
        )

        dialogue_response = None
        if player_message.strip():
            dialogue_response = self.dialogue_engine.respond_to_player(
                working_world,
                player_entity_id=player_entity_id,
                player_message=player_message,
                llm_client=self.llm_client,
            )

        if precompiled_player_compilation is None:
            player_compilation = self.gamemaster.compile_player_intent(
                working_world,
                player_entity_id,
                player_intent,
            )
        else:
            player_compilation = precompiled_player_compilation.model_copy(deep=True)

        action_packages: list[ActionPackage] = []
        if not player_compilation.rejected:
            action_packages.extend(player_compilation.action_packages)

        agent_outputs, agent_signals = self._run_entity_agents(
            working_world,
            player_entity_id=player_entity_id,
        )
        for output in agent_outputs.values():
            if output.action_package is not None:
                action_packages.append(output.action_package)

        event_output = self.event_creator.create_candidate(
            working_world,
            llm_client=self.llm_client,
            scenario_notes=scenario_notes,
        )
        emitted_signals = [*agent_signals, *event_output.emitted_signals]
        batch_validation_report = build_batch_validation_report(
            working_world,
            action_packages,
            self.action_catalog,
            player_entity_id=player_entity_id,
        )

        deterministic_result = self.engine.resolve_actions(
            working_world,
            action_packages,
        )
        scenario_event_result = resolve_scenario_events(
            deterministic_result.world_state,
            self.scenario_events,
            deterministic_result=deterministic_result,
            player_entity_id=player_entity_id,
            framing_summary=event_output.perception_summary,
        )
        final_routing_result = self.info_channel.route_signals(
            scenario_event_result.world_state,
            [
                *deterministic_result.emitted_signals,
                *emitted_signals,
                *scenario_event_result.emitted_signals,
            ],
        )
        next_world = final_routing_result.world_state
        backchannel_update = update_backchannel_threads(
            next_world,
            deterministic_result=deterministic_result,
            action_catalog=self.action_catalog,
            player_entity_id=player_entity_id,
        )
        advisor_update = update_advisor_council(
            next_world,
            before_world_state=working_world,
            player_entity_id=player_entity_id,
            action_catalog=self.action_catalog,
            deterministic_result=deterministic_result,
            agent_outputs=agent_outputs,
            event_output=event_output,
            final_routing_result=final_routing_result,
        )
        aftermath_report = build_turn_aftermath_report(
            before_world_state=working_world,
            after_world_state=next_world,
            player_entity_id=player_entity_id,
            action_catalog=self.action_catalog,
            deterministic_result=deterministic_result,
            agent_outputs=agent_outputs,
            advisor_update=advisor_update,
            batch_validation_report=batch_validation_report,
            scenario_event_result=scenario_event_result,
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
            batch_validation_report=batch_validation_report,
            backchannel_update=backchannel_update,
            advisor_update=advisor_update,
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
            scenario_event_result=scenario_event_result,
            agent_outputs=agent_outputs,
            event_output=event_output,
            deterministic_result=deterministic_result,
            final_routing_result=final_routing_result,
            llm_calls=_llm_call_records(self.llm_client, start_index=llm_call_start),
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
            scenario_event_result=scenario_event_result,
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
            return FactionAgent(entity.entity_id, self.action_catalog).run_turn(
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


def _llm_call_count(llm_client: LLMClient) -> int:
    calls = getattr(llm_client, "calls", [])
    if not isinstance(calls, list):
        return 0
    return len(calls)


def _llm_call_records(
    llm_client: LLMClient,
    *,
    start_index: int = 0,
) -> list[LLMCallRecord]:
    calls = getattr(llm_client, "calls", [])
    if not isinstance(calls, list):
        return []
    records: list[LLMCallRecord] = []
    for call in calls[start_index:]:
        if isinstance(call, LLMCallRecord):
            records.append(call.model_copy(deep=True))
        elif isinstance(call, dict):
            records.append(LLMCallRecord.model_validate(call))
    return records


def _render_turn_debug(
    *,
    start_turn: int,
    next_world: WorldStateV2,
    player_compilation: GamemasterCompilation,
    action_packages: list[ActionPackage],
    agent_outputs: dict[str, AgentOutput],
    event_output: AgentOutput,
    scenario_event_result: ScenarioEventResolution | None,
    batch_validation_report: BatchValidationReport | None,
    backchannel_update: BackchannelThreadUpdate | None,
    advisor_update: AdvisorCouncilUpdate | None,
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
        f"- compiled actions: {len(player_compilation.action_packages)}",
    ]
    if not player_compilation.action_packages:
        lines.append("- action: (none)")
    for package in player_compilation.action_packages:
        lines.append(f"- {package.actor_id}: {package.action_id} via {package.channel.value}")
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
        lines.append(f"- {package.actor_id}: {package.action_id} via {package.channel.value}")
    lines.extend(["", "[entity_agents]"])
    for entity_id, output in agent_outputs.items():
        lines.append(f"- {entity_id}: {output.perception_summary}")
        lines.append(f"  attempted action: {_attempted_action(output)}")
        if output.action_package is not None:
            lines.append(
                f"  accepted package: {output.action_package.action_id} "
                f"via {output.action_package.channel.value}"
            )
        for note in output.debug_notes:
            lines.append(f"  note: {note}")
    lines.extend(
        [
            "",
            "[event_creator]",
            f"- {event_output.perception_summary}",
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
        lines.append(f"- rejected action: {package.actor_id}:{package.action_id} ({reason})")
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


def _attempted_action(output: AgentOutput) -> str:
    if output.action_package is not None:
        return output.action_package.action_id
    for raw in reversed(output.raw_llm_outputs):
        if raw.get("task") != "faction_decision":
            continue
        response = raw.get("response")
        if isinstance(response, dict):
            action_id = response.get("action_id")
            return str(action_id) if action_id else "(none)"
    return "(none)"
