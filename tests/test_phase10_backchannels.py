from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from crisis_room.agents.context import build_visible_context
from crisis_room.app.backchannels import (
    backchannel_thread_id,
    send_backchannel_message,
    update_backchannel_threads,
)
from crisis_room.app.debug_sessions import DebugSessionRecorder, load_debug_session
from crisis_room.app.presentation import build_turn_briefing
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.backchannels import (
    BackchannelMessageRecord,
    BackchannelThread,
    BackchannelThreadStatus,
)
from crisis_room.state.world import WorldStateV2


def test_backchannel_actions_open_and_refresh_persistent_threads() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=71)
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        llm_client=ScriptedLLMClient(),
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="open a private Kremlin backchannel for reciprocal restraint",
    )

    thread_id = backchannel_thread_id("us_excomm", "soviet_presidium")
    thread = result.world_state.backchannel_threads[thread_id]
    briefing = build_turn_briefing(
        result.world_state,
        player_entity_id=scenario.player_entity_id,
        action_catalog=scenario.action_catalog,
    )

    assert result.backchannel_update is not None
    assert thread.status == BackchannelThreadStatus.OPEN
    assert thread.participant_entity_ids == ["soviet_presidium", "us_excomm"]
    assert thread.expires_turn > result.world_state.turn_number
    assert len(thread.message_records) >= 2
    assert any(record.sender_entity_id == "us_excomm" for record in thread.message_records)
    assert any(
        record.sender_entity_id == "soviet_presidium"
        for record in thread.message_records
    )
    assert "[backchannel_threads]" in result.debug_transcript.rendered_text
    assert result.debug_transcript.backchannel_update == result.backchannel_update
    assert any(problem.source == "backchannel" for problem in briefing.problems)


def test_visible_context_includes_bounded_backchannel_excerpt() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=72)
    for index in range(5):
        thread = BackchannelThread(
            thread_id=f"backchannel:counter_{index}:us_excomm",
            participant_entity_ids=[f"counter_{index}", "us_excomm"],
            player_entity_id="us_excomm",
            opened_turn=1,
            last_active_turn=index + 1,
            expires_turn=index + 4,
            message_records=[
                BackchannelMessageRecord(
                    record_id=f"record_{index}_{message_index}",
                    turn_number=message_index + 1,
                    sender_entity_id="us_excomm",
                    recipient_entity_ids=[f"counter_{index}"],
                    action_id="private_kremlin_backchannel",
                    action_package_id=f"package_{index}_{message_index}",
                    summary=f"message {index}-{message_index}",
                )
                for message_index in range(3)
            ],
        )
        world.backchannel_threads[thread.thread_id] = thread

    context = build_visible_context(
        world.actors["us_excomm"],
        world,
        action_catalog=scenario.action_catalog,
        backchannel_thread_limit=2,
        backchannel_record_limit=1,
    )

    assert "backchannel_threads" in context
    assert len(context["backchannel_threads"]) == 2
    assert len(context["backchannel_threads"][0]["recent_messages"]) == 1
    assert context["context_limits"]["backchannel_thread_total"] == 5
    assert context["context_limits"]["backchannel_thread_truncated"] is True
    assert "truth_metrics" not in str(context["backchannel_threads"])
    assert "hidden_clocks" not in str(context["backchannel_threads"])


def test_direct_backchannel_message_consumes_budget_and_routes_response() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=74)
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        llm_client=ScriptedLLMClient(),
    )
    opened = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="open a private Kremlin backchannel for reciprocal restraint",
    )

    sent = send_backchannel_message(
        opened.world_state,
        player_entity_id=scenario.player_entity_id,
        target_entity_id="soviet_presidium",
        message_text=(
            "We need a face-saving private exit. Would a non-invasion pledge "
            "make withdrawal possible?"
        ),
        info_channel=orchestrator.info_channel,
    )
    thread_id = backchannel_thread_id("us_excomm", "soviet_presidium")
    thread = sent.world_state.backchannel_threads[thread_id]

    assert sent.accepted
    assert sent.world_state.turn_number == opened.world_state.turn_number
    assert thread.player_messages_used == 1
    assert thread.player_messages_remaining == 0
    assert sent.response_text
    assert any(
        delivery.source_entity_id == "soviet_presidium"
        for delivery in sent.world_state.actors["us_excomm"].inbox
    )
    assert any(
        delivery.source_entity_id == "us_excomm"
        for delivery in sent.world_state.actors["soviet_presidium"].inbox
    )
    assert sent.world_state.relationships["us_excomm->soviet_presidium"]["trust"] > 0
    assert sent.world_state.backchannel_update_history[-1].message_record_ids

    second = send_backchannel_message(
        sent.world_state,
        player_entity_id=scenario.player_entity_id,
        target_entity_id="soviet_presidium",
        message_text="One more private note.",
        info_channel=orchestrator.info_channel,
    )
    assert not second.accepted
    assert "direct message budget is exhausted" in second.errors[0]


def test_backchannel_threads_expire_and_survive_world_hydration() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=73)
    thread_id = backchannel_thread_id("us_excomm", "soviet_presidium")
    world.backchannel_threads[thread_id] = BackchannelThread(
        thread_id=thread_id,
        participant_entity_ids=["soviet_presidium", "us_excomm"],
        player_entity_id="us_excomm",
        opened_turn=1,
        last_active_turn=1,
        expires_turn=1,
    )
    world.turn_number = 3

    update = update_backchannel_threads(
        world,
        deterministic_result=DeterministicTurnResult(world_state=world),
        action_catalog=scenario.action_catalog,
        player_entity_id=scenario.player_entity_id,
    )
    rehydrated = WorldStateV2.model_validate(world.model_dump(mode="json"))

    assert update is not None
    assert update.expired_thread_ids == [thread_id]
    assert world.backchannel_threads[thread_id].status == BackchannelThreadStatus.EXPIRED
    assert rehydrated.backchannel_threads[thread_id].status == BackchannelThreadStatus.EXPIRED
    assert rehydrated.backchannel_update_history[-1].expired_thread_ids == [thread_id]


def test_direct_backchannel_message_updates_debug_session_world() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=75)
    thread_id = backchannel_thread_id("us_excomm", "soviet_presidium")
    world.backchannel_threads[thread_id] = BackchannelThread(
        thread_id=thread_id,
        participant_entity_ids=["soviet_presidium", "us_excomm"],
        player_entity_id="us_excomm",
        opened_turn=1,
        last_active_turn=1,
        expires_turn=3,
    )
    recorder = DebugSessionRecorder(
        world_state=world,
        player_entity_id=scenario.player_entity_id,
        output_dir=_test_output_dir("direct_backchannel"),
    )

    sent = send_backchannel_message(
        world,
        player_entity_id=scenario.player_entity_id,
        target_entity_id="soviet_presidium",
        message_text="Can we keep this private and reciprocal?",
    )
    recorder.update_world_state(sent.world_state, rendered_log_entry="BACKCHANNEL")
    loaded = load_debug_session(recorder.save())

    assert loaded.world_state.backchannel_threads[thread_id].player_messages_used == 1
    assert loaded.rendered_log[-1] == "BACKCHANNEL"


def _test_output_dir(name: str) -> Path:
    path = Path("output") / "test_debug_sessions" / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path
