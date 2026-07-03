from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from crisis_room.agents.context import build_visible_context
from crisis_room.agents.event_creator import EventCreatorAgent
from crisis_room.app.backchannels import (
    _backchannel_message_leak_risk,
    backchannel_thread_id,
    prepare_backchannel_message,
    send_backchannel_message,
    update_backchannel_threads,
)
from crisis_room.app.debug_sessions import DebugSessionRecorder, load_debug_session
from crisis_room.app.presentation import build_turn_briefing
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.app.tui import _send_backchannel_message
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.llm.contracts import ChatRole, FakeLLMClient
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
        capabilities=scenario.capabilities,
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
        capabilities=scenario.capabilities,
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
                    action_id="cuba_open_kremlin_channel",
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
        capabilities=scenario.capabilities,
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
        capabilities=scenario.capabilities,
        llm_client=ScriptedLLMClient(),
    )
    opened = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="open a private Kremlin backchannel for reciprocal restraint",
    )
    fake_llm = FakeLLMClient(
        {
            "backchannel.us_excomm.availability": {
                "allowed": True,
                "available": True,
                "target_entity_id": "soviet_presidium",
                "target_label": "Soviet Presidium",
                "reason": "Target has scenario gamestate.",
                "confidence": 0.9,
            },
            "backchannel.soviet_presidium.counterpart_response": {
                "accepted": True,
                "response_text": "A private assurance could be discussed.",
                "stance": "constructive",
                "trust_delta": 0.04,
                "leak_risk_delta": 0.01,
                "relationship_delta": 0.03,
            },
            "backchannel.soviet_presidium.state_change": {
                "memory_note": "EXCOMM used the backchannel to test a private pledge.",
                "unresolved_thread": "Clarify whether the pledge is public or deniable.",
                "belief_updates": [
                    {
                        "topic": "private_pledge",
                        "summary": "Washington may be willing to discuss a private assurance.",
                        "confidence": 0.65,
                    }
                ],
                "trust_delta": 0.03,
                "leak_risk_delta": 0.01,
                "relationship_delta": 0.03,
            },
        }
    )

    sent = send_backchannel_message(
        opened.world_state,
        player_entity_id=scenario.player_entity_id,
        target_entity_id="soviet_presidium",
        target_query="Soviet Presidium",
        message_text=(
            "We need a face-saving private exit. Would a non-invasion pledge "
            "make withdrawal possible?"
        ),
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=fake_llm,
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
    assert "private pledge" in sent.world_state.actors["soviet_presidium"].memory_summary
    assert "private_pledge" in sent.world_state.actors["soviet_presidium"].beliefs.claims
    assert sent.world_state.backchannel_update_history[-1].message_record_ids
    assert [call.request.label for call in fake_llm.calls] == [
        "backchannel.us_excomm.availability",
        "backchannel.soviet_presidium.counterpart_response",
        "backchannel.soviet_presidium.state_change",
    ]

    second = send_backchannel_message(
        sent.world_state,
        player_entity_id=scenario.player_entity_id,
        target_entity_id="soviet_presidium",
        message_text="One more private note.",
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=fake_llm,
        info_channel=orchestrator.info_channel,
    )
    assert not second.accepted
    assert "direct message budget is exhausted" in second.errors[0]


def test_direct_backchannel_leak_depends_on_health_and_reaches_event_creator() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=741)
    thread_id = backchannel_thread_id("us_excomm", "soviet_presidium")
    low_health_thread = BackchannelThread(
        thread_id=thread_id,
        participant_entity_ids=["soviet_presidium", "us_excomm"],
        player_entity_id="us_excomm",
        opened_turn=1,
        last_active_turn=1,
        expires_turn=3,
        trust_level=0.0,
        leak_risk=1.0,
    )
    world.backchannel_threads[thread_id] = low_health_thread
    leak_probe = low_health_thread.model_copy(update={"leak_risk": 0.2})
    high_health_probe = leak_probe.model_copy(update={"trust_level": 1.0})
    assert _backchannel_message_leak_risk(leak_probe) > _backchannel_message_leak_risk(
        high_health_probe
    )

    fake_llm = FakeLLMClient(
        {
            "backchannel.us_excomm.availability": {
                "allowed": True,
                "available": True,
                "target_entity_id": "soviet_presidium",
                "target_label": "Soviet Presidium",
                "reason": "Target has scenario gamestate.",
                "confidence": 0.9,
            },
            "backchannel.soviet_presidium.counterpart_response": {
                "accepted": True,
                "response_text": "Keep this channel quiet.",
                "stance": "guarded",
                "trust_delta": 0.0,
                "leak_risk_delta": 0.0,
                "relationship_delta": 0.0,
            },
            "backchannel.soviet_presidium.state_change": {
                "trust_delta": 0.0,
                "leak_risk_delta": 0.0,
                "relationship_delta": 0.0,
            },
        }
    )

    sent = send_backchannel_message(
        world,
        player_entity_id=scenario.player_entity_id,
        target_query="Soviet Presidium",
        message_text="Use the quiet channel before public positions harden.",
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=fake_llm,
    )

    assert sent.accepted
    assert sent.routing_result is not None
    assert sent.routing_result.leaked_signals
    assert any(
        "direct backchannel message moved between" in entry.summary
        for entry in sent.world_state.public_timeline.entries
    )

    event_llm = FakeLLMClient(
        {
            "event_creator.event_creator.media_event_turn": {
                "public_brief": {
                    "headline": "Backchannel Rumor",
                    "summary": "Reports describe a private channel rumor.",
                    "public_risk_read": "elevated",
                },
                "event_candidate": None,
                "major_event_relevant": False,
                "editorial_notes": ["Public rumor is visible."],
            }
        }
    )
    EventCreatorAgent().create_candidate(sent.world_state, llm_client=event_llm)
    event_prompt = "\n".join(
        message.content for message in event_llm.calls[0].request.messages
    )
    assert "direct backchannel message moved between" in event_prompt


def test_direct_backchannel_to_target_without_gamestate_is_unavailable() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=740)
    fake_llm = FakeLLMClient(
        {
            "backchannel.us_excomm.availability": {
                "allowed": True,
                "available": False,
                "target_entity_id": "",
                "target_label": "family member",
                "reason": "Target has no scenario actor gamestate.",
                "confidence": 0.85,
            }
        }
    )

    sent = send_backchannel_message(
        world,
        player_entity_id=scenario.player_entity_id,
        target_query="family member",
        message_text="Tell them I may be late tonight.",
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=fake_llm,
    )

    assert not sent.accepted
    assert not sent.available
    assert "no scenario actor gamestate" in sent.errors[0]
    assert sent.world_state.backchannel_threads == {}
    assert [call.request.label for call in fake_llm.calls] == [
        "backchannel.us_excomm.availability"
    ]


def test_formal_direct_backchannel_message_uses_counterpart_contract() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=76)
    thread_id = backchannel_thread_id("us_excomm", "soviet_presidium")
    world.backchannel_threads[thread_id] = BackchannelThread(
        thread_id=thread_id,
        participant_entity_ids=["soviet_presidium", "us_excomm"],
        player_entity_id="us_excomm",
        opened_turn=1,
        last_active_turn=1,
        expires_turn=3,
    )
    fake_llm = FakeLLMClient(
        {
            "backchannel.soviet_presidium.counterpart_response": {
                "accepted": True,
                "response_text": "A private assurance could be discussed.",
                "stance": "constructive",
                "trust_delta": 0.04,
                "leak_risk_delta": 0.01,
                "relationship_delta": 0.03,
            }
        }
    )

    preparation = prepare_backchannel_message(
        world,
        player_entity_id=scenario.player_entity_id,
        target_entity_id="soviet_presidium",
        message_text="Formal: would a non-invasion pledge move missile withdrawal?",
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=fake_llm,
    )
    request = fake_llm.calls[0].request
    prompt_text = "\n".join(message.content for message in request.messages)

    assert preparation.accepted
    assert preparation.formal
    assert preparation.compilation is not None
    assert request.response_schema_name == "BackchannelCounterpartResponse"
    assert request.max_tokens == 700
    assert "BackchannelCounterpartResponse contract:" in prompt_text
    assert any(message.role == ChatRole.USER for message in request.messages)
    assert preparation.compilation.action_packages[0].parameters == {
        "message_text": "would a non-invasion pledge move missile withdrawal?"
    }


def test_formal_direct_backchannel_message_advances_turn_through_pipeline() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=77)
    thread_id = backchannel_thread_id("us_excomm", "soviet_presidium")
    world.backchannel_threads[thread_id] = BackchannelThread(
        thread_id=thread_id,
        participant_entity_ids=["soviet_presidium", "us_excomm"],
        player_entity_id="us_excomm",
        opened_turn=1,
        last_active_turn=1,
        expires_turn=3,
    )
    llm_client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        scenario_events=scenario.scenario_events,
        llm_client=llm_client,
    )
    preparation = prepare_backchannel_message(
        world,
        player_entity_id=scenario.player_entity_id,
        target_entity_id="soviet_presidium",
        message_text="Formal: offer a private non-invasion pledge for withdrawal.",
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=llm_client,
    )

    assert preparation.compilation is not None
    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="direct formal backchannel message",
        precompiled_player_compilation=preparation.compilation,
    )
    thread = result.world_state.backchannel_threads[thread_id]

    assert result.world_state.turn_number == world.turn_number + 1
    assert any(
        package.mechanical_id == "cuba_direct_kremlin_message"
        for package in result.deterministic_result.accepted_actions
    )
    assert thread.player_messages_used == 1
    assert any(
        record.action_id == "direct_backchannel_response"
        for record in thread.message_records
    )
    assert any(
        delivery.source_entity_id == "soviet_presidium"
        and delivery.payload_type.value == "backchannel_message"
        for delivery in result.final_routing_result.deliveries
    )
    assert result.backchannel_update is not None
    assert result.advisor_update is not None


def test_leaked_formal_direct_message_triggers_authored_flash_event() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    for capability in scenario.capabilities:
        if capability.capability_id == "cuba_direct_kremlin_message":
            capability.signal_leak_risk = 1.0
    world = scenario.create_initial_world(rng_seed=78)
    thread_id = backchannel_thread_id("us_excomm", "soviet_presidium")
    world.backchannel_threads[thread_id] = BackchannelThread(
        thread_id=thread_id,
        participant_entity_ids=["soviet_presidium", "us_excomm"],
        player_entity_id="us_excomm",
        opened_turn=1,
        last_active_turn=1,
        expires_turn=3,
    )
    llm_client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        scenario_events=scenario.scenario_events,
        llm_client=llm_client,
    )
    preparation = prepare_backchannel_message(
        world,
        player_entity_id=scenario.player_entity_id,
        target_entity_id="soviet_presidium",
        message_text="Formal: discuss a deniable Jupiter trade for withdrawal.",
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=llm_client,
    )

    assert preparation.compilation is not None
    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="direct formal backchannel message",
        precompiled_player_compilation=preparation.compilation,
    )

    assert result.scenario_event_result is not None
    assert "direct_backchannel_message_leak" in {
        record.event_id for record in result.scenario_event_result.fired_events
    }
    assert any(
        signal.metadata.get("capability_id") == "cuba_direct_kremlin_message"
        for signal in result.final_routing_result.leaked_signals
    )
    assert any(
        entry.metadata.get("event_id") == "direct_backchannel_message_leak"
        for entry in result.world_state.public_timeline.entries
    )


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
        capabilities=scenario.capabilities,
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


def test_formal_backchannel_counterpart_call_is_saved_in_debug_session() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=79)
    thread_id = backchannel_thread_id("us_excomm", "soviet_presidium")
    world.backchannel_threads[thread_id] = BackchannelThread(
        thread_id=thread_id,
        participant_entity_ids=["soviet_presidium", "us_excomm"],
        player_entity_id="us_excomm",
        opened_turn=1,
        last_active_turn=1,
        expires_turn=3,
    )
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        scenario_events=scenario.scenario_events,
        llm_client=ScriptedLLMClient(),
    )
    recorder = DebugSessionRecorder(
        world_state=world,
        player_entity_id=scenario.player_entity_id,
        output_dir=_test_output_dir("formal_backchannel_debug"),
    )

    _send_backchannel_message(
        world=world,
        player_id=scenario.player_entity_id,
        backchannel_text=(
            "soviet_presidium Formal: offer a private non-invasion pledge "
            "for missile withdrawal."
        ),
        scenario=scenario,
        orchestrator=orchestrator,
        recorder=recorder,
        save_dir=_test_output_dir("formal_backchannel_saves"),
        debug_mode=False,
    )
    loaded = load_debug_session(recorder.path)

    assert loaded.llm_task_records
    record = loaded.llm_task_records[0]
    assert record.label == "backchannel.soviet_presidium.counterpart_response"
    assert record.llm_calls[0].request.response_schema_name == "BackchannelCounterpartResponse"
    assert record.llm_calls[0].raw_response["response_text"]
    assert record.llm_calls[0].parsed_response["response_text"]
    assert any(
        call.request.label == "backchannel.soviet_presidium.counterpart_response"
        for call in record.llm_calls
    )


def _test_output_dir(name: str) -> Path:
    path = Path("output") / "test_debug_sessions" / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path
