from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.agents.gamemaster import GamemasterCompilation
from crisis_room.app.backchannels import (
    render_backchannel_direct_message_result,
    render_backchannel_threads,
    resolve_backchannel_target,
    send_backchannel_message,
)
from crisis_room.app.debug_sessions import DebugSessionRecorder
from crisis_room.app.presentation import (
    build_turn_briefing,
    render_aftermath_report,
    render_turn_briefing,
)
from crisis_room.app.planning import (
    PlayerPlanPreview,
    build_player_plan_preview,
    render_player_plan_preview,
)
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.config.settings import load_settings
from crisis_room.engine.actions import ActionDefinition
from crisis_room.llm.contracts import LLMCallRecord, LLMClient
from crisis_room.llm.diagnostics import LlamaCppError
from crisis_room.llm.llama_cpp_client import LlamaCppServerClient
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.llm.task_contracts import AdvisorResponse
from crisis_room.scenario.schema import Scenario, build_cuban_missile_crisis_1962_scenario
from crisis_room.state.world import WorldStateV2


INTRO_TEXT = """\
CRISIS ROOM SIMULATION

You are inside a political-military crisis room. This build runs the real
typed-agent/orchestrator path. By default it uses the managed local llama.cpp
server configured in config/llama_cpp.local.json.
"""


HELP_TEXT = """\
Commands:
ASK <text>     Ask advisors a question
<text>         Same as ASK <text>
PLAN <text>    Preview compiled actions without resolving a turn
COMMIT         Resolve the last previewed plan
ACTION <text>  Submit up to 3 formal actions and resolve one turn
BACKCHANNEL <target> <message>
               Send one scarce direct message through an open thread
END            Take no formal action and let the turn resolve
BRIEFING       Reprint problems, pressure, agenda, and action cards
STATUS         Same as BRIEFING
ADVISORS       Show persistent council state
BACKCHANNELS   Show active backchannel threads
DEBUG          Toggle raw turn debug output
SAVE           Save the session JSON now
HELP           Show commands
QUIT           Save, exit, and close the managed server
"""


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=args.seed)
    player_id = scenario.player_entity_id
    try:
        llm_client = _build_llm_client(args.llm)
    except Exception as exc:
        print(_format_runtime_error("Local LLM startup", exc))
        return
    try:
        orchestrator = TurnOrchestrator(
            action_catalog=scenario.action_catalog,
            scenario_events=scenario.scenario_events,
            llm_client=llm_client,
        )
        dialogue_engine = DialogueEngineAgent(action_catalog=scenario.action_catalog)
        recorder = DebugSessionRecorder(
            world_state=world,
            player_entity_id=player_id,
            output_dir=args.output_dir,
        )

        print(INTRO_TEXT)
        print(f"SCENARIO: {scenario.metadata.title}")
        print(scenario.intro_text)
        print()
        _print_status(world, player_id, scenario.action_catalog)
        print(HELP_TEXT)

        world = _input_loop(
            scenario=scenario,
            world=world,
            player_id=player_id,
            llm_client=llm_client,
            orchestrator=orchestrator,
            dialogue_engine=dialogue_engine,
            recorder=recorder,
            max_turns=args.max_turns,
            command_source=_demo_commands() if args.demo else None,
        )
    finally:
        _close_client(llm_client)


def _input_loop(
    *,
    scenario: Scenario,
    world: WorldStateV2,
    player_id: str,
    llm_client: LLMClient,
    orchestrator: TurnOrchestrator,
    dialogue_engine: DialogueEngineAgent,
    recorder: DebugSessionRecorder,
    max_turns: int,
    command_source: list[str] | None,
) -> WorldStateV2:
    command_index = 0
    debug_mode = False
    pending_plan: PlayerPlanPreview | None = None
    while True:
        try:
            if command_source is None:
                user_text = input("> ")
            elif command_index < len(command_source):
                user_text = command_source[command_index]
                command_index += 1
                print(f"> {user_text}")
            else:
                path = recorder.save()
                print(f"Command script finished. Saved session: {path}")
                return world
        except EOFError:
            path = recorder.save()
            print(f"\nInput ended. Saved session: {path}")
            return world
        user_text = user_text.strip().lstrip("\ufeff")
        if not user_text:
            continue
        command = user_text.upper()
        if command == "QUIT":
            path = recorder.save()
            print(f"Saved session: {path}")
            print("Exiting game.")
            return world
        if command == "HELP":
            print(HELP_TEXT)
            continue
        if command == "DEBUG":
            debug_mode = not debug_mode
            print(f"Debug output: {'on' if debug_mode else 'off'}")
            continue
        if command in {"STATUS", "BRIEFING", "NEXT"}:
            _print_status(world, player_id, scenario.action_catalog)
            continue
        if command == "ADVISORS":
            _print_advisors(world, player_id)
            continue
        if command == "BACKCHANNELS":
            print(render_backchannel_threads(world, viewer_entity_id=player_id))
            print()
            continue
        if command.startswith("BACKCHANNEL "):
            backchannel_text = user_text[len("BACKCHANNEL ") :].strip()
            world = _send_backchannel_message(
                world=world,
                player_id=player_id,
                backchannel_text=backchannel_text,
                orchestrator=orchestrator,
                recorder=recorder,
            )
            pending_plan = None
            continue
        if command == "SAVE":
            path = recorder.save()
            print(f"Saved session: {path}")
            continue
        if command == "COMMIT":
            if pending_plan is None:
                print("No pending plan. Use PLAN <text> first.\n")
                continue
            if not _plan_matches_world(pending_plan, world, player_id):
                print("The pending plan is stale. Use PLAN <text> again.\n")
                pending_plan = None
                continue
            world = _resolve_turn(
                world=world,
                player_id=player_id,
                player_intent=pending_plan.player_intent,
                player_message="",
                scenario=scenario,
                orchestrator=orchestrator,
                recorder=recorder,
                debug_mode=debug_mode,
                precompiled_player_compilation=pending_plan.compilation,
            )
            pending_plan = None
            if _maybe_end_at_max_turn(world, max_turns, recorder):
                return world
            continue
        if command == "END":
            world = _resolve_turn(
                world=world,
                player_id=player_id,
                player_intent="hold no action this turn",
                player_message="",
                scenario=scenario,
                orchestrator=orchestrator,
                recorder=recorder,
                debug_mode=debug_mode,
            )
            pending_plan = None
            if _maybe_end_at_max_turn(world, max_turns, recorder):
                return world
            continue
        if command == "PLAN" or command.startswith("PLAN "):
            plan_text = user_text[4:].strip()
            if not plan_text:
                print("PLAN needs text, for example: PLAN open a private backchannel.")
                continue
            pending_plan = _preview_plan(
                world=world,
                player_id=player_id,
                player_intent=plan_text,
                scenario=scenario,
                llm_client=llm_client,
                orchestrator=orchestrator,
                recorder=recorder,
            )
            continue
        if command.startswith("ACTION"):
            action_text = user_text[6:].strip()
            if not action_text:
                print("ACTION needs text, for example: ACTION open a private backchannel.")
                continue
            world = _resolve_turn(
                world=world,
                player_id=player_id,
                player_intent=action_text,
                player_message="",
                scenario=scenario,
                orchestrator=orchestrator,
                recorder=recorder,
                debug_mode=debug_mode,
            )
            pending_plan = None
            if _maybe_end_at_max_turn(world, max_turns, recorder):
                return world
            continue

        question = user_text[4:].strip() if command.startswith("ASK ") else user_text
        _answer_dialogue(
            world=world,
            player_id=player_id,
            question=question,
            dialogue_engine=dialogue_engine,
            llm_client=llm_client,
            recorder=recorder,
        )


def _resolve_turn(
    *,
    world: WorldStateV2,
    player_id: str,
    player_intent: str,
    player_message: str,
    scenario: Scenario,
    orchestrator: TurnOrchestrator,
    recorder: DebugSessionRecorder,
    debug_mode: bool,
    precompiled_player_compilation: GamemasterCompilation | None = None,
) -> WorldStateV2:
    try:
        result = orchestrator.run_turn(
            world,
            player_entity_id=player_id,
            player_intent=player_intent,
            player_message=player_message,
            scenario_notes=scenario.metadata.designer_notes,
            precompiled_player_compilation=precompiled_player_compilation,
        )
    except Exception as exc:
        print(_format_runtime_error("Turn", exc))
        return world

    next_world = result.world_state
    recorder.append_turn(result.debug_transcript, next_world)
    path = recorder.save()
    print()
    _print_turn_result(render_aftermath_report(result.aftermath_report))
    if debug_mode:
        print()
        _print_turn_result(result.debug_transcript.rendered_text)
    print()
    _print_status(next_world, player_id, scenario.action_catalog)
    print(f"Saved session: {path}")
    print("Ask advisors, PLAN, ACTION, END, SAVE, HELP, or QUIT.\n")
    return next_world


def _preview_plan(
    *,
    world: WorldStateV2,
    player_id: str,
    player_intent: str,
    scenario: Scenario,
    llm_client: LLMClient,
    orchestrator: TurnOrchestrator,
    recorder: DebugSessionRecorder,
) -> PlayerPlanPreview | None:
    call_start = _llm_call_count(llm_client)
    try:
        preview = build_player_plan_preview(
            world,
            player_entity_id=player_id,
            player_intent=player_intent,
            gamemaster=orchestrator.gamemaster,
            action_catalog=scenario.action_catalog,
        )
    except Exception as exc:
        print(_format_runtime_error("Plan preview", exc))
        return None

    rendered = render_player_plan_preview(
        preview,
        action_catalog=scenario.action_catalog,
    )
    recorder.append_plan_preview(
        turn=world.turn_number,
        player_intent=player_intent,
        preview=preview,
        rendered_text=rendered,
        llm_calls=_llm_call_records(llm_client, start_index=call_start),
    )
    path = recorder.save()
    print()
    print(rendered)
    print(f"Saved session: {path}")
    if not preview.is_committable:
        print("Use PLAN <text> to try again, ACTION <text> to resolve immediately, or HELP.\n")
        return None
    print("Type COMMIT to resolve this plan, PLAN <text> to replace it, or HELP.\n")
    return preview


def _plan_matches_world(
    preview: PlayerPlanPreview,
    world: WorldStateV2,
    player_id: str,
) -> bool:
    return (
        preview.player_entity_id == player_id
        and preview.turn_number == world.turn_number
        and preview.is_committable
    )


def _answer_dialogue(
    *,
    world: WorldStateV2,
    player_id: str,
    question: str,
    dialogue_engine: DialogueEngineAgent,
    llm_client: LLMClient,
    recorder: DebugSessionRecorder,
) -> None:
    call_start = _llm_call_count(llm_client)
    try:
        response = dialogue_engine.respond_to_player(
            world,
            player_entity_id=player_id,
            player_message=question,
            llm_client=llm_client,
        )
    except Exception as exc:
        print(_format_runtime_error("Advisor dialogue", exc))
        return
    calls = _llm_call_records(llm_client, start_index=call_start)
    recorder.append_dialogue(
        turn=world.turn_number,
        player_message=question,
        response=response,
        llm_calls=calls,
    )
    _print_advisor_response(response)


def _send_backchannel_message(
    *,
    world: WorldStateV2,
    player_id: str,
    backchannel_text: str,
    orchestrator: TurnOrchestrator,
    recorder: DebugSessionRecorder,
) -> WorldStateV2:
    pieces = backchannel_text.split(maxsplit=1)
    if len(pieces) < 2:
        print("BACKCHANNEL needs a target and message, for example:")
        print("BACKCHANNEL soviet_presidium What terms would make withdrawal possible?\n")
        return world
    target_query, message_text = pieces
    target_id = resolve_backchannel_target(
        world,
        player_entity_id=player_id,
        target_query=target_query,
    )
    if target_id is None:
        print(f"Backchannel target not found or ambiguous: {target_query}\n")
        return world

    result = send_backchannel_message(
        world,
        player_entity_id=player_id,
        target_entity_id=target_id,
        message_text=message_text,
        info_channel=orchestrator.info_channel,
    )
    rendered = render_backchannel_direct_message_result(result)
    print()
    print(rendered)
    next_world = result.world_state
    recorder.update_world_state(next_world, rendered_log_entry=rendered)
    path = recorder.save()
    print(f"Saved session: {path}")
    print("Ask advisors, PLAN, ACTION, use BACKCHANNELS, END, SAVE, HELP, or QUIT.\n")
    return next_world


def _print_status(
    world: WorldStateV2,
    player_id: str,
    action_catalog: list[ActionDefinition],
) -> None:
    briefing = build_turn_briefing(
        world,
        player_entity_id=player_id,
        action_catalog=action_catalog,
    )
    print(render_turn_briefing(briefing))
    player = world.actors[player_id]
    print()
    print(f"Resources: {_format_resources(player.resources)}")
    print(f"Player inbox items: {len(player.inbox)}")
    for delivery in player.inbox[-3:]:
        print(
            f"- {delivery.channel.value} from {delivery.source_entity_id}: "
            f"{delivery.observed_content}"
        )
    print()


def _print_advisors(world: WorldStateV2, player_id: str) -> None:
    council = world.advisor_councils.get(player_id)
    if council is None:
        print("No persistent advisor council is initialized.\n")
        return
    print()
    print("ADVISOR COUNCIL")
    for advisor in council.advisors.values():
        trusted_channel = _trusted_channel(advisor.trust_channels)
        belief = next(iter(advisor.beliefs.values()), None)
        print(
            f"- {advisor.name}: trust {advisor.trust_player:.0%}, "
            f"urgency {advisor.urgency:.0%}, paranoia {advisor.paranoia:.0%}, "
            f"trusted channel {trusted_channel}"
        )
        if belief is not None:
            print(f"  Belief: {belief.summary}")
    print()


def _print_advisor_response(response: AdvisorResponse) -> None:
    print()
    print("ADVISORS")
    print(response.answer)
    for view in response.advisor_views:
        print(f"- {view.advisor_name}: {view.stance}. {view.reasoning}")
    for warning in response.risk_warnings:
        print(f"! {warning}")
    if response.suggested_action_ids:
        print(f"Suggested actions: {', '.join(response.suggested_action_ids)}")
    if response.visible_context_limits:
        print(f"Limits: {' | '.join(response.visible_context_limits)}")
    print()


def _print_turn_result(rendered_text: str) -> None:
    print(rendered_text)


def _maybe_end_at_max_turn(
    world: WorldStateV2,
    max_turns: int,
    recorder: DebugSessionRecorder,
) -> bool:
    if max_turns <= 0 or world.turn_number <= max_turns:
        return False
    path = recorder.save()
    print(f"Reached max turn limit ({max_turns}). Saved session: {path}")
    return True


def _build_llm_client(mode: str) -> LLMClient:
    if mode == "llama":
        settings = load_settings().llama_cpp
        client = LlamaCppServerClient(settings)
        try:
            print(f"Starting local LLM server: {settings.server_model}")
            print(f"Endpoint: {settings.base_url}")
            client.lease.ensure_running()
            if client.lease.log_path is not None:
                print(f"llama-server log: {client.lease.log_path}")
            else:
                print("Connected to existing llama-server endpoint.")
            print()
        except Exception:
            client.close()
            raise
        return client
    return ScriptedLLMClient()


def _close_client(llm_client: LLMClient) -> None:
    close = getattr(llm_client, "close", None)
    if callable(close):
        close()


def _format_runtime_error(context: str, exc: Exception) -> str:
    if not isinstance(exc, LlamaCppError):
        return f"{context} failed: {type(exc).__name__}: {exc}"

    lines = [
        f"{context} failed.",
        f"Live LLM error: {type(exc).__name__}",
    ]
    details = str(exc).strip()
    if details:
        lines.append("Details:")
        lines.extend(f"  {part.strip()}" for part in details.split("; ") if part.strip())
    return "\n".join(lines)


def _llm_call_count(llm_client: LLMClient) -> int:
    calls = getattr(llm_client, "calls", [])
    return len(calls) if isinstance(calls, list) else 0


def _llm_call_records(
    llm_client: LLMClient,
    *,
    start_index: int,
) -> list[LLMCallRecord]:
    calls = getattr(llm_client, "calls", [])
    if not isinstance(calls, list):
        return []
    return [
        call.model_copy(deep=True)
        for call in calls[start_index:]
        if isinstance(call, LLMCallRecord)
    ]


def _format_resources(resources: dict[str, int]) -> str:
    if not resources:
        return "(none)"
    return ", ".join(f"{key}={value}" for key, value in sorted(resources.items()))


def _trusted_channel(channels: dict[str, float]) -> str:
    if not channels:
        return "uncertain"
    channel, _ = max(channels.items(), key=lambda item: item[1])
    return channel.replace("_", " ")


def _format_float_map(values: dict[str, float]) -> str:
    return ", ".join(f"{key}={value:.2f}" for key, value in sorted(values.items()))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Crisis Room game.")
    parser.add_argument(
        "--llm",
        choices=["scripted", "llama"],
        default="llama",
        help="llama starts/uses the managed local llama.cpp server; scripted is an offline fallback",
    )
    parser.add_argument("--seed", type=int, default=7, help="deterministic scenario seed")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=10,
        help="stop automatically after this turn number; use 0 for unlimited",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/debug_sessions"),
        help="directory for saved session JSON files",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="run a short non-interactive command script",
    )
    return parser.parse_args(argv)


def _demo_commands() -> list[str]:
    return [
        "ASK How do we keep an off-ramp open?",
        "ACTION announce a naval quarantine while keeping a private Kremlin channel open",
        "SAVE",
        "QUIT",
    ]
