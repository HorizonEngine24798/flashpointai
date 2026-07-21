from __future__ import annotations

import json
from typing import Any

from crisis_room.engine.actions import ActionDefinition, ActionResolver, ScenarioCapability
from crisis_room.config.gameplay import (
    DEFAULT_LLM_MAX_TOKENS,
    ELEVATED_RISK_BAND_THRESHOLD,
    GUARDED_RISK_BAND_THRESHOLD,
    HIGH_RISK_BAND_THRESHOLD,
    LOW_RISK_BAND_THRESHOLD,
    VISIBLE_CONTEXT_ACTION_CATALOG_LIMIT,
    VISIBLE_CONTEXT_ACTION_PROMPT_HINT_LIMIT,
    VISIBLE_CONTEXT_ADVISOR_BELIEF_LIMIT,
    VISIBLE_CONTEXT_ADVISOR_LIMIT,
    VISIBLE_CONTEXT_ADVISOR_RECENT_NOTE_LIMIT,
    VISIBLE_CONTEXT_BACKCHANNEL_RECORD_LIMIT,
    VISIBLE_CONTEXT_BACKCHANNEL_THREAD_LIMIT,
    VISIBLE_CONTEXT_EVENT_HISTORY_LIMIT,
    VISIBLE_CONTEXT_INBOX_LIMIT,
    VISIBLE_CONTEXT_PENDING_CHOICE_LIMIT,
    VISIBLE_CONTEXT_TIMELINE_LIMIT,
)
from crisis_room.llm.contracts import ChatRole, LLMMessage, LLMRequest
from crisis_room.llm.prompts import JSON_OBJECT_SYSTEM_INSTRUCTION, schema_contract_guidance
from crisis_room.state.backchannels import BackchannelThreadStatus
from crisis_room.state.timelines import Timeline, TimelineEntry
from crisis_room.state.world import EntityState, WorldStateV2


def build_visible_context(
    entity_state: EntityState,
    world_state: WorldStateV2,
    *,
    action_catalog: list[ActionDefinition] | None = None,
    capabilities: list[ScenarioCapability] | None = None,
    player_message: str | None = None,
    extra: dict[str, Any] | None = None,
    inbox_limit: int = VISIBLE_CONTEXT_INBOX_LIMIT,
    timeline_limit: int = VISIBLE_CONTEXT_TIMELINE_LIMIT,
    event_history_limit: int = VISIBLE_CONTEXT_EVENT_HISTORY_LIMIT,
    pending_choice_limit: int = VISIBLE_CONTEXT_PENDING_CHOICE_LIMIT,
    action_catalog_limit: int = VISIBLE_CONTEXT_ACTION_CATALOG_LIMIT,
    action_prompt_hint_limit: int = VISIBLE_CONTEXT_ACTION_PROMPT_HINT_LIMIT,
    backchannel_thread_limit: int = VISIBLE_CONTEXT_BACKCHANNEL_THREAD_LIMIT,
    backchannel_record_limit: int = VISIBLE_CONTEXT_BACKCHANNEL_RECORD_LIMIT,
    advisor_limit: int = VISIBLE_CONTEXT_ADVISOR_LIMIT,
    advisor_belief_limit: int = VISIBLE_CONTEXT_ADVISOR_BELIEF_LIMIT,
    advisor_recent_note_limit: int = VISIBLE_CONTEXT_ADVISOR_RECENT_NOTE_LIMIT,
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
            "unresolved_threads": entity_state.unresolved_threads,
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
        "recent_events": _visible_event_history(
            world_state,
            entity_state.entity_id,
            limit=event_history_limit,
        ),
        "pending_event_choices": _visible_pending_choices(
            world_state,
            entity_state.entity_id,
            limit=pending_choice_limit,
        ),
        "inbox": [
            delivery.model_dump(mode="json")
            for delivery in _bounded_tail(entity_state.inbox, inbox_limit)
        ],
        "context_limits": {
            "inbox_limit": inbox_limit,
            "public_timeline_limit": timeline_limit,
            "entity_local_timeline_limit": timeline_limit,
            "event_history_limit": event_history_limit,
            "pending_event_choice_limit": pending_choice_limit,
            "backchannel_thread_limit": backchannel_thread_limit,
            "backchannel_record_limit": backchannel_record_limit,
            "advisor_limit": advisor_limit,
            "advisor_belief_limit": advisor_belief_limit,
            "advisor_recent_note_limit": advisor_recent_note_limit,
            "action_prompt_hint_limit": action_prompt_hint_limit,
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
        advisors = list(advisor_council.advisors.values())
        bounded_advisors = advisors[: max(advisor_limit, 0)]
        context["advisor_council"] = {
            "player_entity_id": advisor_council.player_entity_id,
            "allowed_advisor_ids": list(advisor_council.advisors),
            "advisors": [
                {
                    "advisor_id": advisor.advisor_id,
                    "name": advisor.name,
                    "portfolio": advisor.portfolio,
                    "personality": advisor.personality,
                    "institutional_orientation": advisor.institutional_orientation,
                    "hidden_metric_access": advisor.hidden_metric_access,
                    "loyal_to_player": advisor.loyal_to_player,
                    "trust_player": advisor.trust_player,
                    "trust_advisors": advisor.trust_advisors,
                    "trust_channels": advisor.trust_channels,
                    "paranoia": advisor.paranoia,
                    "urgency": advisor.urgency,
                    "institutional_confidence": advisor.institutional_confidence,
                    "beliefs": _bounded_advisor_beliefs(
                        advisor.beliefs.values(),
                        limit=advisor_belief_limit,
                    ),
                    "beliefs_total": len(advisor.beliefs),
                    "memory_summary": advisor.memory_summary,
                    "recent_recommendations": _bounded_tail(
                        advisor.recent_recommendations,
                        advisor_recent_note_limit,
                    ),
                    "recent_embarrassments": _bounded_tail(
                        advisor.recent_embarrassments,
                        advisor_recent_note_limit,
                    ),
                }
                for advisor in bounded_advisors
            ],
        }
        if any(advisor.hidden_metric_access for advisor in bounded_advisors):
            context["advisor_council"]["hidden_pressure_bands"] = _hidden_pressure_bands(
                world_state
            )
        context["context_limits"].update(
            {
                "advisor_total": len(advisors),
                "advisor_truncated": len(bounded_advisors) < len(advisors),
            }
        )
    if action_catalog is not None:
        visible_actions = _visible_action_entries(action_catalog, capabilities)
        bounded_catalog = visible_actions[: max(action_catalog_limit, 0)]
        context["action_catalog"] = [
            _action_definition_excerpt(
                definition,
                prompt_hint_limit=action_prompt_hint_limit,
            )
            for definition in bounded_catalog
        ]
        context["context_limits"].update(
            {
                "action_catalog_limit": action_catalog_limit,
                "action_catalog_total": len(visible_actions),
                "action_catalog_truncated": len(bounded_catalog) < len(visible_actions),
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
    max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
) -> LLMRequest:
    contract_guidance = schema_contract_guidance(response_schema_name)
    system_sections = [
        system_prompt,
        JSON_OBJECT_SYSTEM_INSTRUCTION,
        f"Task:\n{task_instruction}",
    ]
    if contract_guidance:
        system_sections.append(f"Contract guidance:\n{contract_guidance}")
    return LLMRequest(
        label=label,
        messages=[
            LLMMessage(
                role=ChatRole.SYSTEM,
                content="\n\n".join(system_sections),
            ),
            LLMMessage(
                role=ChatRole.USER,
                content=(
                    "Visible context JSON:\n"
                    f"{json.dumps(visible_context, sort_keys=True)}"
                ),
            ),
        ],
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


def _action_definition_excerpt(
    definition: ActionDefinition,
    *,
    prompt_hint_limit: int = VISIBLE_CONTEXT_ACTION_PROMPT_HINT_LIMIT,
) -> dict[str, Any]:
    excerpt = {
        "action_id": definition.action_id,
        "capability_id": definition.capability_id,
        "title": definition.title,
        "category": definition.category.value,
        "actor_types_allowed": definition.actor_types_allowed,
        "actor_ids_allowed": definition.actor_ids_allowed,
        "targets_allowed": definition.targets_allowed,
        "target_ids_allowed": definition.target_ids_allowed,
        "channels_allowed": [channel.value for channel in definition.channels_allowed],
        "required_resources": definition.required_resources,
        "resource_costs": definition.resource_costs,
        "preparation_turns": definition.preparation_turns,
        "execution_turns": definition.execution_turns,
        "min_targets": definition.min_targets,
        "max_targets": definition.max_targets,
        "escalation_risk": definition.escalation_risk,
        "deescalation_potential": definition.deescalation_potential,
        "signal_leak_risk": definition.signal_leak_risk,
        "signal_distortion_risk": definition.signal_distortion_risk,
        "information_outputs": [item.value for item in definition.information_outputs],
        "parameter_schema": {
            name: parameter.model_dump(mode="json")
            for name, parameter in definition.parameter_schema.items()
        },
        "prompt_hints": definition.prompt_hints[: max(prompt_hint_limit, 0)],
    }
    if definition.player_card_text:
        excerpt["player_card_text"] = definition.player_card_text
    return excerpt


def _visible_action_entries(
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None,
) -> list[ActionDefinition]:
    if capabilities:
        return ActionResolver(action_catalog, capabilities).resolved_capability_definitions()
    return action_catalog


def _visible_event_history(
    world_state: WorldStateV2,
    entity_id: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    visible = [
        record
        for record in world_state.event_history
        if record.public or not record.visible_to or entity_id in record.visible_to
    ]
    return [
        {
            "event_id": record.event_id,
            "title": record.title,
            "kind": record.kind,
            "turn_number": record.turn_number,
            "status": record.status.value,
            "urgency": record.urgency,
            "problem_title": record.problem_title,
            "problem_summary": record.problem_summary,
            "related_entity_ids": record.related_entity_ids,
            "public": record.public,
            "choice_ids": record.choice_ids,
        }
        for record in _bounded_tail(visible, limit)
    ]


def _visible_pending_choices(
    world_state: WorldStateV2,
    entity_id: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    active = [
        choice
        for choice in world_state.pending_event_choices
        if choice.active_for(world_state.turn_number, entity_id)
    ]
    return [
        {
            "choice_id": choice.choice_id,
            "event_id": choice.event_id,
            "title": choice.title,
            "prompt": choice.prompt,
            "turn_number": choice.turn_number,
            "expires_turn": choice.expires_turn,
            "options": [
                {
                    "option_id": option.option_id,
                    "label": option.label,
                    "summary": option.summary,
                    "action_id": option.action_id,
                    "capability_id": option.capability_id,
                    "target_ids": option.target_ids,
                    "channel": option.channel.value,
                    "consumes_normal_action_budget": option.consumes_normal_action_budget,
                    "event_only_extra_budget": option.event_only_extra_budget,
                }
                for option in choice.options
            ],
        }
        for choice in _bounded_tail(active, limit)
    ]


def _bounded_advisor_beliefs(values: object, *, limit: int) -> list[dict[str, Any]]:
    beliefs = sorted(
        values,
        key=lambda belief: belief.last_updated_turn,
        reverse=True,
    )
    return [belief.model_dump(mode="json") for belief in beliefs[: max(limit, 0)]]


def _hidden_pressure_bands(world_state: WorldStateV2) -> dict[str, str]:
    values = {**world_state.truth_metrics, **world_state.hidden_clocks}
    return {key: _pressure_band(float(value)) for key, value in sorted(values.items())}


def _pressure_band(value: float) -> str:
    if value < LOW_RISK_BAND_THRESHOLD:
        return "low"
    if value < GUARDED_RISK_BAND_THRESHOLD:
        return "guarded"
    if value < ELEVATED_RISK_BAND_THRESHOLD:
        return "rising"
    if value < HIGH_RISK_BAND_THRESHOLD:
        return "dangerous"
    return "critical"


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
        and thread.expires_turn >= world_state.turn_number
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
                    thread.player_messages_remaining_for_turn(world_state.turn_number)
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
