from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.agents.gamemaster import GamemasterCompilation
from crisis_room.app.backchannels import (
    prepare_backchannel_message,
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
from crisis_room.config.gameplay import HARD_ACTION_BUDGET, NORMAL_ACTION_BUDGET
from crisis_room.config.settings import load_settings
from crisis_room.engine.actions import ActionDefinition, ScenarioCapability
from crisis_room.llm.contracts import LLMCallRecord, LLMClient
from crisis_room.llm.diagnostics import LlamaCppError
from crisis_room.llm.llama_cpp_client import LlamaCppServerClient
from crisis_room.llm.task_contracts import AdvisorCouncilResponse
from crisis_room.scenario.endings import (
    accept_ending_offer,
    reject_ending_offer,
    render_active_ending_offers,
)
from crisis_room.scenario.loader import (
    DEFAULT_SCENARIO_ID,
    ScenarioLoadError,
    load_scenario,
)
from crisis_room.scenario.schema import Scenario
from crisis_room.scenario.event_choices import build_event_choice_action
from crisis_room.state.saves import (
    load_playable_session,
    pending_plan_matches_world,
    restore_pending_plan,
    save_playable_session,
)
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
ACTION <text>  Submit formal actions and resolve one turn
BACKCHANNEL <target> <message>
               Send one scarce direct message through an open thread
END            Take no formal action and let the turn resolve
BRIEFING       Reprint problems, pressure, agenda, and action cards
STATUS         Same as BRIEFING
ADVISORS       Show persistent council state
BACKCHANNELS   Show active backchannel threads
EVENT <choice> <option>
               Commit a pending event choice as a formal action
ENDING         Show active ending offers
ACCEPT ENDING [offer]
               Accept an offered ending and conclude the crisis
REJECT ENDING [offer]
               Reject an offered ending and continue
DEBUG          Toggle raw turn debug output
SAVE           Save the session JSON now
HELP           Show commands
QUIT           Save, exit, and close the managed server
"""


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.action_budget < 0:
        print("Invalid action budget: value must be non-negative.")
        return
    if args.hard_action_limit < args.action_budget:
        print("Invalid hard action limit: value must be greater than or equal to action budget.")
        return
    try:
        scenario = load_scenario(args.scenario, scenario_dir=args.scenario_dir)
    except ScenarioLoadError as exc:
        print(_format_runtime_error("Scenario load", exc))
        return
    world = scenario.create_initial_world(rng_seed=args.seed)
    player_id = scenario.player_entity_id
    pending_plan = None
    if args.load_save is not None:
        try:
            loaded_save = load_playable_session(args.load_save)
        except Exception as exc:
            print(_format_runtime_error("Load playable save", exc))
            return
        if loaded_save.scenario_id != scenario.scenario_id:
            print(
                "Load playable save failed: "
                f"save scenario {loaded_save.scenario_id!r} does not match "
                f"{scenario.scenario_id!r}."
            )
            return
        world = loaded_save.world_state
        player_id = loaded_save.player_entity_id
        pending_plan = restore_pending_plan(loaded_save)
    try:
        llm_client = _build_llm_client()
    except Exception as exc:
        print(_format_runtime_error("Local LLM startup", exc))
        return
    try:
        orchestrator = TurnOrchestrator(
            action_catalog=scenario.action_catalog,
            capabilities=scenario.capabilities,
            scenario_events=scenario.scenario_events,
            scenario_endings=scenario.scenario_endings,
            event_settings=scenario.event_settings,
            llm_client=llm_client,
            action_budget=args.action_budget,
            hard_action_limit=args.hard_action_limit,
        )
        dialogue_engine = DialogueEngineAgent(
            action_catalog=scenario.action_catalog,
            capabilities=scenario.capabilities,
        )
        recorder = DebugSessionRecorder(
            world_state=world,
            player_entity_id=player_id,
            output_dir=args.output_dir,
        )

        print(INTRO_TEXT)
        print(f"SCENARIO: {scenario.metadata.title}")
        print(scenario.intro_text)
        print()
        _print_status(
            world,
            player_id,
            scenario.action_catalog,
            scenario.capabilities,
            action_budget=args.action_budget,
        )
        print(HELP_TEXT)

        world = _input_loop(
            scenario=scenario,
            world=world,
            player_id=player_id,
            llm_client=llm_client,
            orchestrator=orchestrator,
            dialogue_engine=dialogue_engine,
            recorder=recorder,
            save_dir=args.save_dir,
            max_turns=args.max_turns,
            pending_plan=pending_plan,
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
    save_dir: Path,
    max_turns: int,
    pending_plan: PlayerPlanPreview | None = None,
    command_source: list[str] | None,
) -> WorldStateV2:
    command_index = 0
    debug_mode = False
    if pending_plan is not None:
        print("Loaded pending plan. Type COMMIT to resolve it, PLAN <text> to replace it, or HELP.\n")
    while True:
        try:
            if command_source is None:
                user_text = input("> ")
            elif command_index < len(command_source):
                user_text = command_source[command_index]
                command_index += 1
                print(f"> {user_text}")
            else:
                debug_path = recorder.save()
                playable_path = _save_playable(
                    world,
                    player_id,
                    save_dir,
                    pending_plan=pending_plan,
                )
                print(f"Command script finished. Saved playable session: {playable_path}")
                print(f"Saved debug session: {debug_path}")
                return world
        except EOFError:
            debug_path = recorder.save()
            playable_path = _save_playable(
                world,
                player_id,
                save_dir,
                pending_plan=pending_plan,
            )
            print(f"\nInput ended. Saved playable session: {playable_path}")
            print(f"Saved debug session: {debug_path}")
            return world
        user_text = user_text.strip().lstrip("\ufeff")
        if not user_text:
            continue
        command = user_text.upper()
        if command == "QUIT":
            debug_path = recorder.save()
            playable_path = _save_playable(
                world,
                player_id,
                save_dir,
                pending_plan=pending_plan,
            )
            print(f"Saved playable session: {playable_path}")
            print(f"Saved debug session: {debug_path}")
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
            _print_status(
                world,
                player_id,
                scenario.action_catalog,
                scenario.capabilities,
                action_budget=orchestrator.action_budget,
            )
            continue
        if command == "ADVISORS":
            _print_advisors(world, player_id, debug_mode=debug_mode)
            continue
        if command == "BACKCHANNELS":
            print(render_backchannel_threads(world, viewer_entity_id=player_id))
            print()
            continue
        if command in {"ENDING", "ENDINGS"}:
            print(render_active_ending_offers(world, player_entity_id=player_id))
            print()
            continue
        if command == "ACCEPT ENDING" or command.startswith("ACCEPT ENDING "):
            query = user_text[len("ACCEPT ENDING") :].strip() or "latest"
            decision = accept_ending_offer(
                world,
                player_entity_id=player_id,
                offer_query=query,
            )
            if decision.errors:
                print()
                print("ACCEPT ENDING FAILED")
                for error in decision.errors:
                    print(f"- {error}")
                print()
                continue
            world = decision.world_state
            pending_plan = None
            recorder.update_world_state(world, rendered_log_entry=decision.summary)
            debug_path = recorder.save()
            playable_path = _save_playable(world, player_id, save_dir)
            print()
            print(decision.summary)
            print(f"Saved playable session: {playable_path}")
            print(f"Saved debug session: {debug_path}")
            print("Crisis concluded.")
            return world
        if command == "REJECT ENDING" or command.startswith("REJECT ENDING "):
            query = user_text[len("REJECT ENDING") :].strip() or "latest"
            decision = reject_ending_offer(
                world,
                player_entity_id=player_id,
                offer_query=query,
            )
            if decision.errors:
                print()
                print("REJECT ENDING FAILED")
                for error in decision.errors:
                    print(f"- {error}")
                print()
                continue
            world = decision.world_state
            pending_plan = None
            recorder.update_world_state(world, rendered_log_entry=decision.summary)
            debug_path = recorder.save()
            playable_path = _save_playable(world, player_id, save_dir)
            print()
            print(decision.summary)
            print(f"Saved playable session: {playable_path}")
            print(f"Saved debug session: {debug_path}")
            print("Continue with ASK, PLAN, ACTION, END, SAVE, HELP, or QUIT.\n")
            continue
        if command.startswith("BACKCHANNEL "):
            backchannel_text = user_text[len("BACKCHANNEL ") :].strip()
            world = _send_backchannel_message(
                world=world,
                player_id=player_id,
                backchannel_text=backchannel_text,
                scenario=scenario,
                orchestrator=orchestrator,
                recorder=recorder,
                save_dir=save_dir,
                debug_mode=debug_mode,
            )
            pending_plan = None
            continue
        if command == "SAVE":
            debug_path = recorder.save()
            playable_path = _save_playable(
                world,
                player_id,
                save_dir,
                pending_plan=pending_plan,
            )
            print(f"Saved playable session: {playable_path}")
            print(f"Saved debug session: {debug_path}")
            continue
        if command.startswith("EVENT "):
            event_text = user_text[len("EVENT ") :].strip()
            world = _commit_event_choice(
                world=world,
                player_id=player_id,
                event_text=event_text,
                scenario=scenario,
                orchestrator=orchestrator,
                recorder=recorder,
                save_dir=save_dir,
                debug_mode=debug_mode,
            )
            pending_plan = None
            if _maybe_end_at_max_turn(world, max_turns, recorder, save_dir, player_id):
                return world
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
                save_dir=save_dir,
                debug_mode=debug_mode,
                precompiled_player_compilation=pending_plan.compilation,
            )
            pending_plan = None
            if _maybe_end_at_max_turn(world, max_turns, recorder, save_dir, player_id):
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
                save_dir=save_dir,
                debug_mode=debug_mode,
            )
            pending_plan = None
            if _maybe_end_at_max_turn(world, max_turns, recorder, save_dir, player_id):
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
                save_dir=save_dir,
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
                save_dir=save_dir,
                debug_mode=debug_mode,
            )
            pending_plan = None
            if _maybe_end_at_max_turn(world, max_turns, recorder, save_dir, player_id):
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
    save_dir: Path,
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
    debug_path = recorder.save()
    playable_path = _save_playable(next_world, player_id, save_dir)
    print()
    _print_turn_result(render_aftermath_report(result.aftermath_report))
    if debug_mode:
        print()
        _print_turn_result(result.debug_transcript.rendered_text)
    print()
    _print_status(
        next_world,
        player_id,
        scenario.action_catalog,
        scenario.capabilities,
        action_budget=orchestrator.action_budget,
    )
    print(f"Saved playable session: {playable_path}")
    print(f"Saved debug session: {debug_path}")
    print("Ask advisors, PLAN, ACTION, ENDING, END, SAVE, HELP, or QUIT.\n")
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
    save_dir: Path,
) -> PlayerPlanPreview | None:
    call_start = _llm_call_count(llm_client)
    try:
        preview = build_player_plan_preview(
            world,
            player_entity_id=player_id,
            player_intent=player_intent,
            gamemaster=orchestrator.gamemaster,
            action_catalog=scenario.action_catalog,
            capabilities=scenario.capabilities,
            scenario_events=scenario.scenario_events,
        )
    except Exception as exc:
        print(_format_runtime_error("Plan preview", exc))
        return None

    rendered = render_player_plan_preview(
        preview,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )
    recorder.append_plan_preview(
        turn=world.turn_number,
        player_intent=player_intent,
        preview=preview,
        rendered_text=rendered,
        llm_calls=_llm_call_records(llm_client, start_index=call_start),
    )
    debug_path = recorder.save()
    playable_path = _save_playable(
        world,
        player_id,
        save_dir,
        pending_plan=preview if preview.is_committable else None,
    )
    print()
    print(rendered)
    print(f"Saved playable session: {playable_path}")
    print(f"Saved debug session: {debug_path}")
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
    return pending_plan_matches_world(preview, world, player_id)


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
    scenario: Scenario,
    orchestrator: TurnOrchestrator,
    recorder: DebugSessionRecorder,
    save_dir: Path,
    debug_mode: bool,
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

    call_start = _llm_call_count(orchestrator.llm_client)
    if target_id is not None:
        preparation = prepare_backchannel_message(
            world,
            player_entity_id=player_id,
            target_entity_id=target_id,
            message_text=message_text,
            action_catalog=scenario.action_catalog,
            capabilities=scenario.capabilities,
            llm_client=orchestrator.llm_client,
        )
        if not preparation.accepted:
            print()
            print("BACKCHANNEL FAILED")
            for error in preparation.errors:
                print(f"- {error}")
            print()
            return world
        if preparation.formal:
            preparation_llm_calls = _llm_call_records(
                orchestrator.llm_client,
                start_index=call_start,
            )
            if preparation_llm_calls:
                recorder.append_llm_task(
                    turn=world.turn_number,
                    label=preparation_llm_calls[0].request.label,
                    llm_calls=preparation_llm_calls,
                    rendered_text=(
                        f"[turn {world.turn_number} llm] "
                        f"{preparation_llm_calls[0].request.label}"
                    ),
                )
            assert preparation.compilation is not None
            print()
            print("BACKCHANNEL FORMAL ACTION")
            print(f"Sent to {target_id}: {preparation.message_text}")
            print("Resolving through the turn pipeline.\n")
            return _resolve_turn(
                world=world,
                player_id=player_id,
                player_intent=f"direct backchannel message to {target_id}",
                player_message="",
                scenario=scenario,
                orchestrator=orchestrator,
                recorder=recorder,
                save_dir=save_dir,
                debug_mode=debug_mode,
                precompiled_player_compilation=preparation.compilation,
            )

    result = send_backchannel_message(
        world,
        player_entity_id=player_id,
        target_entity_id=target_id or "",
        target_query=target_query,
        message_text=message_text,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=orchestrator.llm_client,
        info_channel=orchestrator.info_channel,
    )
    llm_calls = _llm_call_records(orchestrator.llm_client, start_index=call_start)
    if llm_calls:
        recorder.append_llm_task(
            turn=world.turn_number,
            label=llm_calls[0].request.label,
            llm_calls=llm_calls,
            rendered_text=(
                f"[turn {world.turn_number} llm] "
                f"{llm_calls[0].request.label}"
            ),
        )
    rendered = render_backchannel_direct_message_result(result)
    print()
    print(rendered)
    next_world = result.world_state
    recorder.update_world_state(next_world, rendered_log_entry=rendered)
    debug_path = recorder.save()
    playable_path = _save_playable(next_world, player_id, save_dir)
    print(f"Saved playable session: {playable_path}")
    print(f"Saved debug session: {debug_path}")
    print("Ask advisors, PLAN, ACTION, use BACKCHANNELS, ENDING, END, SAVE, HELP, or QUIT.\n")
    return next_world


def _commit_event_choice(
    *,
    world: WorldStateV2,
    player_id: str,
    event_text: str,
    scenario: Scenario,
    orchestrator: TurnOrchestrator,
    recorder: DebugSessionRecorder,
    save_dir: Path,
    debug_mode: bool,
) -> WorldStateV2:
    pieces = event_text.split(maxsplit=1)
    if len(pieces) < 2:
        print("EVENT needs a choice and option, for example:")
        print("EVENT latest private_probe\n")
        return world
    choice_query, option_query = pieces
    package, errors = build_event_choice_action(
        world,
        player_entity_id=player_id,
        choice_query=choice_query,
        option_query=option_query,
    )
    if package is None:
        print()
        print("EVENT CHOICE FAILED")
        for error in errors:
            print(f"- {error}")
        print()
        return world
    compilation = GamemasterCompilation(
        action_packages=[package],
        action_package=package,
        compiled_intents=[package.intent_summary],
        notes=[
            "Compiled pending event choice through its configured scenario capability."
        ],
        action_budget=orchestrator.action_budget,
        hard_action_limit=orchestrator.hard_action_limit,
    )
    print()
    print("EVENT CHOICE FORMAL ACTION")
    print(f"Choice: {choice_query} -> {option_query}")
    print("Resolving through the turn pipeline.\n")
    return _resolve_turn(
        world=world,
        player_id=player_id,
        player_intent=f"event choice {choice_query} {option_query}",
        player_message="",
        scenario=scenario,
        orchestrator=orchestrator,
        recorder=recorder,
        save_dir=save_dir,
        debug_mode=debug_mode,
        precompiled_player_compilation=compilation,
    )


def _print_status(
    world: WorldStateV2,
    player_id: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability],
    *,
    action_budget: int = NORMAL_ACTION_BUDGET,
) -> None:
    briefing = build_turn_briefing(
        world,
        player_entity_id=player_id,
        action_catalog=action_catalog,
        capabilities=capabilities,
        action_budget=action_budget,
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


def _print_advisors(
    world: WorldStateV2,
    player_id: str,
    *,
    debug_mode: bool = False,
) -> None:
    council = world.advisor_councils.get(player_id)
    if council is None:
        print("No persistent advisor council is initialized.\n")
        return
    print()
    print("ADVISOR COUNCIL")
    for advisor in council.advisors.values():
        trusted_channel = _trusted_channel(advisor.trust_channels)
        belief = next(iter(advisor.beliefs.values()), None)
        if debug_mode:
            print(
                f"- {advisor.name}: trust {advisor.trust_player:.0%}, "
                f"urgency {advisor.urgency:.0%}, paranoia {advisor.paranoia:.0%}, "
                f"trusted channel {trusted_channel}"
            )
        else:
            print(
                f"- {advisor.name}: {_trust_read(advisor.trust_player)} trust, "
                f"{_pressure_read(advisor.urgency)} urgency, "
                f"{_pressure_read(advisor.paranoia)} caution, "
                f"trusts {trusted_channel}"
            )
        if belief is not None:
            print(f"  Belief: {belief.summary}")
        if advisor.recent_recommendations:
            print(f"  Recent recommendation: {advisor.recent_recommendations[-1]}")
        if advisor.recent_embarrassments:
            print(f"  Concern: {advisor.recent_embarrassments[-1]}")
    print()


def _print_advisor_response(response: AdvisorCouncilResponse) -> None:
    print()
    print("ADVISORS")
    print(response.answer)
    if response.council_summary:
        print(f"Council: {response.council_summary}")
    for view in response.advisor_views:
        print(f"- {view.advisor_name}: {view.stance}. {view.reasoning}")
    for warning in response.risk_warnings:
        print(f"! {warning}")
    if response.suggested_capability_ids:
        print(f"Suggested moves: {', '.join(response.suggested_capability_ids)}")
    elif response.suggested_action_ids:
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
    save_dir: Path,
    player_id: str,
) -> bool:
    if max_turns <= 0 or world.turn_number <= max_turns:
        return False
    debug_path = recorder.save()
    playable_path = _save_playable(world, player_id, save_dir)
    print(f"Reached max turn limit ({max_turns}). Saved playable session: {playable_path}")
    print(f"Saved debug session: {debug_path}")
    return True


def _build_llm_client() -> LLMClient:
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


def _trust_read(value: float) -> str:
    if value >= 0.72:
        return "strong"
    if value >= 0.55:
        return "steady"
    if value >= 0.38:
        return "fragile"
    return "strained"


def _pressure_read(value: float) -> str:
    if value >= 0.75:
        return "high"
    if value >= 0.55:
        return "rising"
    if value >= 0.35:
        return "guarded"
    return "low"


def _format_float_map(values: dict[str, float]) -> str:
    return ", ".join(f"{key}={value:.2f}" for key, value in sorted(values.items()))


def _save_playable(
    world: WorldStateV2,
    player_id: str,
    save_dir: Path,
    *,
    pending_plan: PlayerPlanPreview | None = None,
) -> Path:
    return save_playable_session(
        world_state=world,
        player_entity_id=player_id,
        output_dir=save_dir,
        pending_plan=pending_plan,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Crisis Room game.")
    parser.add_argument("--seed", type=int, default=7, help="deterministic scenario seed")
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO_ID,
        help=(
            "built-in scenario ID/alias or path to a Scenario JSON file "
            f"(default: {DEFAULT_SCENARIO_ID})"
        ),
    )
    parser.add_argument(
        "--scenario-dir",
        type=Path,
        default=None,
        help="directory of launch-time Scenario JSON files",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=10,
        help="stop automatically after this turn number; use 0 for unlimited",
    )
    parser.add_argument(
        "--action-budget",
        type=int,
        default=NORMAL_ACTION_BUDGET,
        help="normal number of formal player actions per turn",
    )
    parser.add_argument(
        "--hard-action-limit",
        type=int,
        default=HARD_ACTION_BUDGET,
        help="hard maximum compiler candidates before a player turn is rejected",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/debug_sessions"),
        help="directory for debug session JSON files",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=Path("saves"),
        help="directory for playable save JSON files",
    )
    parser.add_argument(
        "--load-save",
        type=Path,
        default=None,
        help="load a playable save JSON file before starting",
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
