from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.agents.base import AgentOutput, StaticEntityAgent
from crisis_room.agents.gamemaster import GamemasterCompilation, SimpleGamemaster
from crisis_room.agents.info_channel import PrototypeInfoChannel, RoutingResult
from crisis_room.engine.adjudication import DeterministicTurnResult, FakeDeterministicEngine
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.state.world import WorldStateV2


class DebugTurnResult(BaseModel):
    world_state: WorldStateV2
    compilation: GamemasterCompilation
    deterministic_result: DeterministicTurnResult | None = None
    routing_result: RoutingResult | None = None
    agent_outputs: dict[str, AgentOutput] = Field(default_factory=dict)
    debug_dump_text: str


def run_fake_turn(
    world_state: WorldStateV2,
    player_entity_id: str,
    player_intent: str,
) -> DebugTurnResult:
    gamemaster = SimpleGamemaster()
    engine = FakeDeterministicEngine()
    info_channel = PrototypeInfoChannel()
    fake_llm = FakeLLMClient()

    compilation = gamemaster.compile_player_intent(
        world_state=world_state,
        actor_id=player_entity_id,
        intent_text=player_intent,
    )
    if compilation.rejected or compilation.action_package is None:
        return DebugTurnResult(
            world_state=world_state,
            compilation=compilation,
            debug_dump_text=_render_rejected_dump(world_state, compilation),
        )

    deterministic_result = engine.resolve_actions(
        world_state,
        [compilation.action_package],
    )
    routing_result = info_channel.route_signals(
        deterministic_result.world_state,
        deterministic_result.emitted_signals,
    )
    next_world = routing_result.world_state

    agent_outputs: dict[str, AgentOutput] = {}
    for entity_id, entity_state in next_world.actors.items():
        if entity_id == player_entity_id:
            continue
        agent = StaticEntityAgent(entity_id)
        agent_outputs[entity_id] = agent.run_turn(entity_state, next_world, fake_llm)

    next_world.turn_number += 1
    debug_dump = _render_debug_dump(
        world_state=next_world,
        compilation=compilation,
        deterministic_result=deterministic_result,
        routing_result=routing_result,
        agent_outputs=agent_outputs,
    )
    return DebugTurnResult(
        world_state=next_world,
        compilation=compilation,
        deterministic_result=deterministic_result,
        routing_result=routing_result,
        agent_outputs=agent_outputs,
        debug_dump_text=debug_dump,
    )


def _render_rejected_dump(
    world_state: WorldStateV2,
    compilation: GamemasterCompilation,
) -> str:
    lines = [
        "DEBUG TURN DUMP",
        "",
        "[gamemaster]",
        f"- turn: {world_state.turn_number}",
        "- compilation rejected",
    ]
    lines.extend(f"- error: {error}" for error in compilation.errors)
    return "\n".join(lines)


def _render_debug_dump(
    world_state: WorldStateV2,
    compilation: GamemasterCompilation,
    deterministic_result: DeterministicTurnResult,
    routing_result: RoutingResult,
    agent_outputs: dict[str, AgentOutput],
) -> str:
    action = compilation.action_package
    lines = [
        "DEBUG TURN DUMP",
        "",
        "[gamemaster]",
        f"- compiled action: {action.action_id if action else '(none)'}",
        f"- notes: {' | '.join(compilation.notes) if compilation.notes else '(none)'}",
        "",
        "[deterministic_engine]",
        f"- accepted actions: {len(deterministic_result.accepted_actions)}",
        f"- rejected actions: {len(deterministic_result.rejected_actions)}",
    ]
    lines.extend(f"- trace: {item}" for item in deterministic_result.trace)
    lines.extend(
        [
            "",
            "[info_channel]",
            f"- deliveries: {len(routing_result.deliveries)}",
            f"- delayed: {len(routing_result.delayed_signals)}",
            f"- leaked: {len(routing_result.leaked_signals)}",
            f"- suppressed: {len(routing_result.suppressed_signal_ids)}",
        ]
    )
    lines.extend(f"- trace: {item}" for item in routing_result.trace)
    lines.extend(["", "[entity_agents]"])
    for entity_id, output in agent_outputs.items():
        lines.append(f"- {entity_id}: {output.perception_summary}")
        for debate_line in output.internal_debate:
            lines.append(f"  debate: {debate_line}")
    lines.extend(
        [
            "",
            "[timelines]",
            f"- omniscient entries: {len(world_state.omniscient_timeline.entries)}",
            f"- public entries: {len(world_state.public_timeline.entries)}",
            f"- entity-local timelines: {len(world_state.entity_timelines)}",
        ]
    )
    for entity_id, entity in world_state.actors.items():
        lines.append(f"- inbox[{entity_id}]: {len(entity.inbox)} item(s)")
    return "\n".join(lines)
