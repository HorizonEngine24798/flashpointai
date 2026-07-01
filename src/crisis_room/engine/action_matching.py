from __future__ import annotations

from collections.abc import Sequence

from crisis_room.engine.actions import ActionDefinition
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import EntityState, WorldStateV2


def actor_type_allowed(actor_type: str, allowed: Sequence[str]) -> bool:
    return not allowed or "*" in allowed or "any" in allowed or actor_type in allowed


def actor_allowed(actor: EntityState, definition: ActionDefinition) -> bool:
    if definition.actor_ids_allowed and actor.entity_id not in definition.actor_ids_allowed:
        return False
    return actor_type_allowed(actor.entity_type.value, definition.actor_types_allowed)


def target_allowed(
    target_id: str,
    target_type: str,
    allowed_types: Sequence[str],
    allowed_ids: Sequence[str],
) -> bool:
    if allowed_ids and target_id not in allowed_ids:
        return False
    return (
        not allowed_types
        or "*" in allowed_types
        or "any" in allowed_types
        or target_id in allowed_types
        or target_type in allowed_types
    )


def default_targets(
    world_state: WorldStateV2,
    player_entity_id: str,
    definition: ActionDefinition,
) -> list[str]:
    targets: list[str] = []
    for entity in world_state.actors.values():
        if entity.entity_id == player_entity_id:
            continue
        if target_allowed(
            entity.entity_id,
            entity.entity_type.value,
            definition.targets_allowed,
            definition.target_ids_allowed,
        ):
            targets.append(entity.entity_id)
    if definition.max_targets is not None:
        targets = targets[: definition.max_targets]
    if len(targets) < definition.min_targets:
        fallback = [
            entity_id
            for entity_id in world_state.actors
            if entity_id != player_entity_id
        ]
        targets.extend(target for target in fallback if target not in targets)
    return targets[: definition.max_targets or len(targets)]


def default_channel(definition: ActionDefinition) -> SignalChannel:
    if SignalChannel.BACKCHANNEL in definition.channels_allowed:
        return SignalChannel.BACKCHANNEL
    if SignalChannel.PRIVATE_DIPLOMATIC in definition.channels_allowed:
        return SignalChannel.PRIVATE_DIPLOMATIC
    if definition.channels_allowed:
        return definition.channels_allowed[0]
    return SignalChannel.PRIVATE_DIPLOMATIC
