from __future__ import annotations

from crisis_room.engine.actions import ActionPackage
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.state.events import (
    EventChoiceOption,
    ScenarioEventChoiceRecord,
    ScenarioEventChoiceStatus,
)
from crisis_room.state.world import WorldStateV2


def expire_event_choices(world_state: WorldStateV2) -> None:
    for choice in world_state.pending_event_choices:
        if (
            choice.status == ScenarioEventChoiceStatus.PENDING
            and choice.expires_turn is not None
            and world_state.turn_number > choice.expires_turn
        ):
            choice.status = ScenarioEventChoiceStatus.EXPIRED


def build_event_choice_action(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    choice_query: str,
    option_query: str,
) -> tuple[ActionPackage | None, list[str]]:
    choice = _find_pending_choice(
        world_state,
        player_entity_id=player_entity_id,
        choice_query=choice_query,
    )
    if choice is None:
        return None, [f"pending event choice not found: {choice_query}"]
    option = _find_choice_option(choice, option_query)
    if option is None:
        return None, [f"event choice option not found: {option_query}"]
    package = ActionPackage(
        actor_id=player_entity_id,
        action_id=option.action_id,
        capability_id=option.capability_id,
        target_ids=option.target_ids,
        channel=option.channel,
        intent_summary=option.summary or option.label,
        submitted_turn=world_state.turn_number,
        parameters=option.parameters,
        metadata={
            "event_choice_id": choice.choice_id,
            "event_choice_event_id": choice.event_id,
            "event_choice_option_id": option.option_id,
            "consumes_normal_action_budget": option.consumes_normal_action_budget,
            "event_only_extra_budget": option.event_only_extra_budget,
        },
    )
    return package, []


def update_event_choices_from_actions(
    world_state: WorldStateV2,
    deterministic_result: DeterministicTurnResult,
) -> None:
    resolved = [
        *deterministic_result.accepted_actions,
        *deterministic_result.completed_pending_actions,
    ]
    for package in resolved:
        choice_id = package.metadata.get("event_choice_id")
        option_id = package.metadata.get("event_choice_option_id")
        if not isinstance(choice_id, str) or not isinstance(option_id, str):
            continue
        for choice in world_state.pending_event_choices:
            if choice.choice_id != choice_id:
                continue
            choice.status = ScenarioEventChoiceStatus.RESOLVED
            choice.selected_option_id = option_id


def _find_pending_choice(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    choice_query: str,
) -> ScenarioEventChoiceRecord | None:
    query = choice_query.strip().lower()
    active = [
        choice
        for choice in world_state.pending_event_choices
        if choice.active_for(world_state.turn_number, player_entity_id)
    ]
    for choice in active:
        if choice.choice_id.lower() == query:
            return choice
    for choice in active:
        if choice.choice_id.lower().startswith(query) or choice.event_id.lower().startswith(query):
            return choice
    return active[0] if query in {"latest", "current", "event"} and active else None


def _find_choice_option(
    choice: ScenarioEventChoiceRecord,
    option_query: str,
) -> EventChoiceOption | None:
    query = option_query.strip().lower()
    for option in choice.options:
        if option.option_id.lower() == query:
            return option
    for option in choice.options:
        if option.option_id.lower().startswith(query) or option.label.lower().startswith(query):
            return option
    return None
