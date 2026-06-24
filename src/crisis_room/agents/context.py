from __future__ import annotations

import json
from typing import Any

from crisis_room.engine.actions import ActionDefinition
from crisis_room.llm.contracts import ChatRole, LLMMessage, LLMRequest
from crisis_room.state.backchannels import BackchannelThreadStatus
from crisis_room.state.timelines import Timeline, TimelineEntry
from crisis_room.state.world import EntityState, WorldStateV2


DEFAULT_ACTION_CATALOG_LIMIT = 32
DEFAULT_BACKCHANNEL_THREAD_LIMIT = 4
DEFAULT_BACKCHANNEL_RECORD_LIMIT = 2

_SCHEMA_CONTRACT_GUIDANCE = {
    "AdvisorResponse": (
        "AdvisorResponse contract: answer should directly address player_message. "
        "advisor_views must contain distinct named viewpoints with stance, reasoning, "
        "and confidence. risk_warnings must be concrete hazards. suggested_action_ids "
        "must be copied from visible action_catalog ids only. Use information_gaps "
        "and visible_context_limits for uncertainty or unavailable information."
    ),
    "IntentCompilation": (
        "IntentCompilation contract: if accepted is true, action_id must be one "
        "visible action_catalog id, target_ids must be visible entity ids allowed by "
        "that action, channel must be allowed by that action, and intent_summary must "
        "be non-empty. If accepted is false, set action_id to null, target_ids to an "
        "empty list, and explain the rejection in errors."
    ),
    "MultiIntentCompilation": (
        "MultiIntentCompilation contract: translate the player ACTION text into zero "
        "to three candidates. Split clearly separate concrete intents, but prefer one "
        "candidate when wording describes one integrated action. Each accepted "
        "candidate must use one visible action_catalog id, visible target_ids, an "
        "allowed channel, and a non-empty intent_summary. Reject individual intents "
        "that cannot be represented legally; do not invent more than three actions."
    ),
    "PerceptionUpdate": (
        "PerceptionUpdate contract: write from this entity's local viewpoint only. "
        "Use belief_updates for changed interpretations tied to visible evidence; "
        "source_signal_ids should come from inbox entries when available. Put gaps "
        "in uncertainty_notes or priority_questions instead of inventing secrets."
    ),
    "InternalDebate": (
        "InternalDebate contract: positions should map to visible internal narratives "
        "when possible. narrative_id should use an existing narrative id or a short "
        "stable label. preferred_action_id must be a visible action_catalog id or "
        "null. target_entity_ids must be visible entity ids. synthesis must be non-empty."
    ),
    "FactionDecision": (
        "FactionDecision contract: to act, use a visible action_catalog action_id, "
        "visible target_ids, an allowed channel, and a non-empty intent_summary. "
        "To choose no action, set action_id to null, target_ids to an empty list, "
        "and provide no_action_reason. Do not narrate deterministic effects as facts."
    ),
    "InternationalPressure": (
        "InternationalPressure contract: describe outside pressure, not direct state "
        "mutation. pressure_signals must be plausible SignalCandidate objects using "
        "visible entity ids when targeted. Keep reliability, leak_risk, "
        "distortion_risk, urgency, and escalation_read between 0 and 1."
    ),
    "EventCandidate": (
        "EventCandidate contract: candidate_id should be short and stable, kind must "
        "match the allowed event kinds, and title plus summary must describe one "
        "specific pressure event. suggested_signals must be plausible information "
        "packets. deterministic_effect_hints are numeric non-authoritative hints only."
    ),
}


def build_visible_context(
    entity_state: EntityState,
    world_state: WorldStateV2,
    *,
    action_catalog: list[ActionDefinition] | None = None,
    player_message: str | None = None,
    extra: dict[str, Any] | None = None,
    inbox_limit: int = 8,
    timeline_limit: int = 8,
    action_catalog_limit: int = DEFAULT_ACTION_CATALOG_LIMIT,
    backchannel_thread_limit: int = DEFAULT_BACKCHANNEL_THREAD_LIMIT,
    backchannel_record_limit: int = DEFAULT_BACKCHANNEL_RECORD_LIMIT,
) -> dict[str, Any]:
    """Build an entity-local view that excludes omniscient truth state."""

    local_timeline = world_state.entity_timelines.get(entity_state.entity_id)
    context: dict[str, Any] = {
        "scenario_id": world_state.scenario_id,
        "turn_number": world_state.turn_number,
        "time_label": world_state.time_label,
        "entity": {
            "entity_id": entity_state.entity_id,
            "name": entity_state.name,
            "entity_type": entity_state.entity_type.value,
            "role": entity_state.role,
            "public_goals": entity_state.public_goals,
            "private_goals": entity_state.private_goals,
            "doctrine": entity_state.doctrine,
            "resources": entity_state.resources,
            "memory_summary": entity_state.memory_summary,
            "beliefs": entity_state.beliefs.model_dump(mode="json"),
            "internal_narratives": [
                narrative.model_dump(mode="json")
                for narrative in entity_state.internal_narratives
            ],
            "known_commitments": entity_state.known_commitments,
            "unresolved_threads": entity_state.unresolved_threads,
            "confidence_map": entity_state.confidence_map,
        },
        "public_metrics": world_state.public_metrics,
        "actor_public_profiles": [
            {
                "entity_id": actor.entity_id,
                "name": actor.name,
                "entity_type": actor.entity_type.value,
                "role": actor.role,
                "public_goals": actor.public_goals,
            }
            for actor in world_state.actors.values()
        ],
        "public_timeline": _dump_entries(
            _latest_timeline_entries(world_state.public_timeline, timeline_limit)
        ),
        "entity_local_timeline": _dump_entries(
            _latest_timeline_entries(local_timeline, timeline_limit)
        ),
        "inbox": [
            delivery.model_dump(mode="json")
            for delivery in _bounded_tail(entity_state.inbox, inbox_limit)
        ],
        "context_limits": {
            "inbox_limit": inbox_limit,
            "public_timeline_limit": timeline_limit,
            "entity_local_timeline_limit": timeline_limit,
            "backchannel_thread_limit": backchannel_thread_limit,
            "backchannel_record_limit": backchannel_record_limit,
        },
    }
    backchannel_context = _backchannel_context(
        world_state,
        entity_state.entity_id,
        thread_limit=backchannel_thread_limit,
        record_limit=backchannel_record_limit,
    )
    if backchannel_context["threads"]:
        context["backchannel_threads"] = backchannel_context["threads"]
        context["context_limits"].update(backchannel_context["limits"])
    advisor_council = world_state.advisor_councils.get(entity_state.entity_id)
    if advisor_council is not None:
        context["advisor_council"] = {
            "player_entity_id": advisor_council.player_entity_id,
            "advisors": [
                {
                    "advisor_id": advisor.advisor_id,
                    "name": advisor.name,
                    "portfolio": advisor.portfolio,
                    "personality": advisor.personality,
                    "institutional_orientation": advisor.institutional_orientation,
                    "trust_player": advisor.trust_player,
                    "trust_channels": advisor.trust_channels,
                    "paranoia": advisor.paranoia,
                    "urgency": advisor.urgency,
                    "institutional_confidence": advisor.institutional_confidence,
                    "beliefs": [
                        belief.model_dump(mode="json")
                        for belief in advisor.beliefs.values()
                    ],
                    "memory_summary": advisor.memory_summary,
                    "recent_recommendations": advisor.recent_recommendations[-3:],
                    "recent_embarrassments": advisor.recent_embarrassments[-3:],
                }
                for advisor in advisor_council.advisors.values()
            ],
        }
    if action_catalog is not None:
        bounded_catalog = action_catalog[: max(action_catalog_limit, 0)]
        context["action_catalog"] = [
            _action_definition_excerpt(definition) for definition in bounded_catalog
        ]
        context["context_limits"].update(
            {
                "action_catalog_limit": action_catalog_limit,
                "action_catalog_total": len(action_catalog),
                "action_catalog_truncated": len(bounded_catalog) < len(action_catalog),
            }
        )
    if player_message is not None:
        context["player_message"] = player_message
    if extra:
        context["extra"] = extra
    return context


def build_task_request(
    *,
    label: str,
    system_prompt: str,
    visible_context: dict[str, Any],
    task_instruction: str,
    response_schema_name: str,
    metadata: dict[str, str | int | float | bool] | None = None,
    temperature: float = 0.2,
    top_p: float = 0.9,
    max_tokens: int = 1024,
) -> LLMRequest:
    contract_guidance = _SCHEMA_CONTRACT_GUIDANCE.get(response_schema_name)
    user_sections = [
        f"Visible context JSON:\n{json.dumps(visible_context, sort_keys=True)}",
        f"Task:\n{task_instruction}",
    ]
    if contract_guidance:
        user_sections.append(f"Contract guidance:\n{contract_guidance}")
    return LLMRequest(
        label=label,
        messages=[
            LLMMessage(
                role=ChatRole.SYSTEM,
                content=(
                    f"{system_prompt}\n\n"
                    "Return exactly one JSON object matching the requested schema. "
                    "Do not include markdown fences or explanatory text."
                ),
            ),
            LLMMessage(
                role=ChatRole.USER,
                content="\n\n".join(user_sections),
            ),
        ],
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        response_schema_name=response_schema_name,
        metadata=metadata or {},
    )


def _dump_entries(entries: list[TimelineEntry]) -> list[dict[str, Any]]:
    return [entry.model_dump(mode="json") for entry in entries]


def _latest_timeline_entries(
    timeline: Timeline | None,
    limit: int,
) -> list[TimelineEntry]:
    if timeline is None or limit <= 0:
        return []
    return timeline.latest(limit)


def _bounded_tail(values: list[Any], limit: int) -> list[Any]:
    if limit <= 0:
        return []
    return values[-limit:]


def _action_definition_excerpt(definition: ActionDefinition) -> dict[str, Any]:
    return {
        "action_id": definition.action_id,
        "title": definition.title,
        "category": definition.category.value,
        "actor_types_allowed": definition.actor_types_allowed,
        "targets_allowed": definition.targets_allowed,
        "channels_allowed": [channel.value for channel in definition.channels_allowed],
        "required_resources": definition.required_resources,
        "min_targets": definition.min_targets,
        "max_targets": definition.max_targets,
        "prompt_hints": definition.prompt_hints,
    }


def _backchannel_context(
    world_state: WorldStateV2,
    entity_id: str,
    *,
    thread_limit: int,
    record_limit: int,
) -> dict[str, Any]:
    threads = [
        thread
        for thread in world_state.backchannel_threads.values()
        if entity_id in thread.participant_entity_ids
        and thread.status == BackchannelThreadStatus.OPEN
    ]
    threads.sort(key=lambda thread: (thread.last_active_turn, thread.expires_turn), reverse=True)
    bounded_threads = threads[: max(thread_limit, 0)]
    return {
        "threads": [
            {
                "thread_id": thread.thread_id,
                "counterpart_entity_ids": [
                    participant_id
                    for participant_id in thread.participant_entity_ids
                    if participant_id != entity_id
                ],
                "status": thread.status.value,
                "last_active_turn": thread.last_active_turn,
                "expires_turn": thread.expires_turn,
                "trust_level": thread.trust_level,
                "leak_risk": thread.leak_risk,
                "player_messages_remaining": (
                    thread.player_messages_remaining
                    if thread.player_entity_id == entity_id
                    else None
                ),
                "recent_messages": [
                    {
                        "turn_number": record.turn_number,
                        "sender_entity_id": record.sender_entity_id,
                        "recipient_entity_ids": record.recipient_entity_ids,
                        "action_id": record.action_id,
                        "summary": record.summary,
                    }
                    for record in thread.message_records[-max(record_limit, 0) :]
                ],
            }
            for thread in bounded_threads
        ],
        "limits": {
            "backchannel_thread_total": len(threads),
            "backchannel_thread_truncated": len(bounded_threads) < len(threads),
        },
    }
