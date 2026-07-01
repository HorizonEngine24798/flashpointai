from __future__ import annotations

import json
from typing import Any

from crisis_room.engine.actions import ActionDefinition, ActionResolver, ScenarioCapability
from crisis_room.config.gameplay import (
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_LLM_TOP_P,
    HARD_ACTION_BUDGET,
    NORMAL_ACTION_BUDGET,
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
from crisis_room.state.backchannels import BackchannelThreadStatus
from crisis_room.state.timelines import Timeline, TimelineEntry
from crisis_room.state.world import EntityState, WorldStateV2


_ADVISOR_COUNCIL_RESPONSE_GUIDANCE = (
    "AdvisorCouncilResponse contract: answer should directly address "
    "player_message. advisor_views must use advisor_id values copied from "
    "advisor_council.allowed_advisor_ids, with advisor_name matching the council. "
    "Do not invent advisors. council_summary should synthesize the room without "
    "numeric state. risk_warnings must be concrete hazards. "
    "suggested_capability_ids must be capability_id values copied from visible "
    "action_catalog entries; suggested_action_ids may name the matching generic "
    "action ids. information_gaps and visible_context_limits should mark "
    "uncertainty or unavailable information. proposed_advisor_deltas are optional "
    "small state hints for the existing advisor update step; they must use known "
    "advisor ids, explain reasons, and avoid exposing numbers to the player."
)


_SCHEMA_CONTRACT_GUIDANCE = {
    "AdvisorCouncilResponse": _ADVISOR_COUNCIL_RESPONSE_GUIDANCE,
    "AdvisorResponse": _ADVISOR_COUNCIL_RESPONSE_GUIDANCE,
    "BackchannelCounterpartResponse": (
        "BackchannelCounterpartResponse contract: respond as the target entity to "
        "one incoming direct backchannel message using only visible context. "
        "response_text must be concise, bounded, and suitable to route as a "
        "confidential signal. Deltas are small mechanical hints, not guaranteed "
        "outcomes: keep trust_delta, leak_risk_delta, and relationship_delta within "
        "the schema bounds and do not reveal hidden state."
    ),
    "BackchannelAvailabilityCheck": (
        "BackchannelAvailabilityCheck contract: decide whether the requested "
        "backchannel target maps to an available scenario actor. A message can be "
        "allowed even when it is not available; available means target_entity_id is "
        "one visible actor with gamestate in actor_public_profiles. Do not invent "
        "actors for people or groups that are not present in the scenario."
    ),
    "BackchannelStateChange": (
        "BackchannelStateChange contract: determine the bounded actor-local state "
        "changes caused by one completed backchannel exchange. Prefer belief_updates, "
        "memory_note, unresolved_thread, and small trust/leak/relationship deltas. "
        "Do not change global truth, public metrics, resources, or deterministic "
        "action outcomes."
    ),
    "SignalDistortionResponse": (
        "SignalDistortionResponse contract: rewrite only the observed message as "
        "received through a noisy crisis channel. Preserve the broad subject and "
        "source, but omit, garble, soften, harden, or introduce uncertainty in "
        "details. Do not add new hard facts, actors, numbers, commitments, or "
        "omniscient knowledge."
    ),
    "IntentCompilation": (
        "IntentCompilation contract: if accepted is true, action_id must be one "
        "visible generic action id and capability_id must be one visible capability "
        "bound to that action. target_ids must be visible entity ids allowed by that "
        "capability, channel must be allowed, parameters must contain only keys "
        "listed in parameter_schema, and intent_summary must be non-empty. If "
        "accepted is false, set action_id and capability_id to null, target_ids to "
        "an empty list, and explain the rejection in errors."
    ),
    "MultiIntentCompilation": (
        "MultiIntentCompilation contract: translate the player ACTION text into zero "
        f"to {HARD_ACTION_BUDGET} candidates. The normal action budget is "
        f"{NORMAL_ACTION_BUDGET}; report obvious extra requested intents as "
        "additional candidates so they can be marked unprocessed. Split clearly "
        "separate concrete intents, but prefer one "
        "candidate when wording describes one integrated action. Each accepted "
        "candidate must use one visible generic action_id plus one visible "
        "capability_id bound to it, visible target_ids, an allowed channel, strict "
        "parameters from parameter_schema, and a non-empty intent_summary. Reject "
        "individual intents that cannot be represented legally; do not invent more "
        f"than {HARD_ACTION_BUDGET} actions."
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
        "stable label. preferred_action_id must be a visible generic action id or "
        "null, and preferred_capability_id should name the visible capability when "
        "one fits. target_entity_ids must be visible entity ids. synthesis must be "
        "non-empty."
    ),
    "FactionDecision": (
        "FactionDecision contract: to act, use a visible generic action_id, a "
        "visible capability_id bound to it, visible target_ids, an allowed channel, "
        "strict parameters from parameter_schema, and a non-empty intent_summary. "
        "To choose no action, set action_id and capability_id to null, target_ids "
        "to an empty list, and provide no_action_reason. Do not narrate "
        "deterministic effects as facts."
    ),
    "FactionTurnResponse": (
        "FactionTurnResponse contract: produce one coherent faction turn in a "
        "single response. perception_update must be entity-local and evidence-bound; "
        "internal_debate must stage distinct internal narratives with real tension, "
        "preferred catalog actions when useful, and a synthesis; decision must be "
        "legal against visible action_catalog or explicitly choose no action. "
        "self_critique should name doubts, red-team objections, or uncertainty that "
        "tempered the final decision. Do not expose hidden state or deterministic "
        "effects as facts."
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
    "EventCreatorResponse": (
        "EventCreatorResponse contract: always return a public_brief suitable for "
        "headline news using only public timeline, public metrics, public actor "
        "profiles, and scenario-public event context. event_candidate is optional "
        "and should be non-null only when a major historically grounded, chaotic, "
        "institutional, local-initiative, or media-leak pressure event is relevant. "
        "Candidate effects are hints only; deterministic code decides whether an "
        "event actually fires."
    ),
}


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
    temperature: float = DEFAULT_LLM_TEMPERATURE,
    top_p: float = DEFAULT_LLM_TOP_P,
    max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
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
        "min_targets": definition.min_targets,
        "max_targets": definition.max_targets,
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
    beliefs = list(values)
    return [belief.model_dump(mode="json") for belief in beliefs[: max(limit, 0)]]


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
