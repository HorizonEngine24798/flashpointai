from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from crisis_room.engine.actions import ActionPackage
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.engine.clocks import NumericChange, apply_numeric_effects, clamp
from crisis_room.scenario.events import ScenarioEventEffect
from crisis_room.state.signals import SignalChannel
from crisis_room.state.timelines import TimelineEntry, TimelineScope
from crisis_room.state.world import WorldStateV2


class PressureRule(BaseModel):
    rule_id: str
    title: str = ""
    applies_to_actor_ids: list[str] = Field(default_factory=list)
    applies_to_actor_types: list[str] = Field(default_factory=list)
    applies_to_action_ids: list[str] = Field(default_factory=list)
    applies_to_capability_ids: list[str] = Field(default_factory=list)
    applies_to_categories: list[str] = Field(default_factory=list)
    applies_to_channels: list[SignalChannel] = Field(default_factory=list)
    required_tags: list[str] = Field(default_factory=list)
    excluded_tags: list[str] = Field(default_factory=list)
    once_per_turn: bool = False
    effects: ScenarioEventEffect = Field(default_factory=ScenarioEventEffect)
    reason: str = ""
    visible_summary: str = ""


class HiddenObligation(BaseModel):
    obligation_id: str
    title: str
    covered_by_action_ids: list[str] = Field(default_factory=list)
    covered_by_capability_ids: list[str] = Field(default_factory=list)
    covered_by_categories: list[str] = Field(default_factory=list)
    covered_by_channels: list[SignalChannel] = Field(default_factory=list)
    covered_by_tags: list[str] = Field(default_factory=list)
    missed_effects: ScenarioEventEffect = Field(default_factory=ScenarioEventEffect)
    reason: str = ""
    visible_to_player: bool = False
    visible_summary: str = ""


class PressureApplication(BaseModel):
    rule_id: str
    source: str
    summary: str
    effect_summary: list[str] = Field(default_factory=list)
    hidden: bool = True


class PressureResolution(BaseModel):
    world_state: WorldStateV2
    applications: list[PressureApplication] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)


def apply_scenario_pressure(
    world_state: WorldStateV2,
    *,
    pressure_rules: list[PressureRule],
    hidden_obligations: list[HiddenObligation],
    deterministic_result: DeterministicTurnResult,
) -> PressureResolution:
    next_world = world_state.model_copy(deep=True)
    result = PressureResolution(world_state=next_world)
    actions = _turn_actions(deterministic_result)
    applied_once: set[str] = set()

    for rule in pressure_rules:
        for action in actions:
            if rule.once_per_turn and rule.rule_id in applied_once:
                break
            if not _rule_matches(next_world, rule, action):
                continue
            application = _apply_effects(
                next_world,
                rule.effects,
                rule_id=rule.rule_id,
                source=action.package_id,
                summary=rule.visible_summary or rule.reason or rule.title or rule.rule_id,
                hidden=True,
            )
            result.applications.append(application)
            result.trace.append(f"{rule.rule_id}: applied to {action.mechanical_id}")
            applied_once.add(rule.rule_id)

    for obligation in hidden_obligations:
        covered = any(_obligation_covered(obligation, action) for action in actions)
        if covered:
            result.trace.append(f"{obligation.obligation_id}: covered")
            continue
        application = _apply_effects(
            next_world,
            obligation.missed_effects,
            rule_id=obligation.obligation_id,
            source="hidden_obligation",
            summary=(
                obligation.visible_summary
                or obligation.reason
                or f"{obligation.title} was neglected."
            ),
            hidden=not obligation.visible_to_player,
        )
        result.applications.append(application)
        result.trace.append(f"{obligation.obligation_id}: missed")

    if result.applications:
        _append_pressure_audit(next_world, result.applications)
    result.world_state = next_world
    return result


def _turn_actions(result: DeterministicTurnResult) -> list[ActionPackage]:
    actions: list[ActionPackage] = []
    seen: set[str] = set()
    for action in [
        *result.accepted_actions,
        *result.scheduled_actions,
        *result.completed_pending_actions,
    ]:
        if action.package_id in seen:
            continue
        seen.add(action.package_id)
        actions.append(action)
    return actions


def _rule_matches(
    world_state: WorldStateV2,
    rule: PressureRule,
    action: ActionPackage,
) -> bool:
    actor = world_state.actors.get(action.actor_id)
    actor_type = actor.entity_type.value if actor is not None else ""
    tags = _action_tags(action)
    checks = [
        (rule.applies_to_actor_ids, action.actor_id),
        (rule.applies_to_actor_types, actor_type),
        (rule.applies_to_action_ids, action.action_id),
        (rule.applies_to_capability_ids, action.capability_id or ""),
        (rule.applies_to_categories, _action_category(action)),
    ]
    if any(values and value not in values for values, value in checks):
        return False
    if rule.applies_to_channels and action.channel not in rule.applies_to_channels:
        return False
    if rule.required_tags and not set(rule.required_tags).issubset(tags):
        return False
    if rule.excluded_tags and set(rule.excluded_tags).intersection(tags):
        return False
    return True


def _obligation_covered(obligation: HiddenObligation, action: ActionPackage) -> bool:
    tags = _action_tags(action)
    checks = [
        (obligation.covered_by_action_ids, action.action_id),
        (obligation.covered_by_capability_ids, action.capability_id or ""),
        (obligation.covered_by_categories, _action_category(action)),
    ]
    if any(values and value in values for values, value in checks):
        return True
    if obligation.covered_by_channels and action.channel in obligation.covered_by_channels:
        return True
    return bool(obligation.covered_by_tags and set(obligation.covered_by_tags).intersection(tags))


def _apply_effects(
    world_state: WorldStateV2,
    effects: ScenarioEventEffect,
    *,
    rule_id: str,
    source: str,
    summary: str,
    hidden: bool,
) -> PressureApplication:
    effect_summary: list[str] = []
    effect_summary.extend(
        _change_summaries(
            "truth",
            apply_numeric_effects(world_state.truth_metrics, effects.truth_metric_effects),
        )
    )
    effect_summary.extend(
        _change_summaries(
            "public",
            apply_numeric_effects(world_state.public_metrics, effects.public_metric_effects),
        )
    )
    effect_summary.extend(
        _change_summaries(
            "clock",
            apply_numeric_effects(world_state.hidden_clocks, effects.clock_effects),
        )
    )
    effect_summary.extend(_apply_relationship_effects(world_state, effects.relationship_effects))
    for commitment in effects.active_commitments_added:
        if commitment not in world_state.active_commitments:
            world_state.active_commitments.append(commitment)
            effect_summary.append(f"commitment added: {commitment}")
    return PressureApplication(
        rule_id=rule_id,
        source=source,
        summary=summary,
        effect_summary=effect_summary,
        hidden=hidden,
    )


def _apply_relationship_effects(
    world_state: WorldStateV2,
    effects: dict[str, dict[str, float]],
) -> list[str]:
    lines: list[str] = []
    for pair_key, metric_effects in effects.items():
        pair = world_state.relationships.setdefault(pair_key, {})
        changes = []
        for key, delta in metric_effects.items():
            before = float(pair.get(key, 0.0))
            after = round(clamp(before + float(delta)), 10)
            pair[key] = after
            changes.append(
                NumericChange(
                    key=f"{pair_key}.{key}",
                    before=before,
                    delta=float(delta),
                    after=after,
                )
            )
        lines.extend(_change_summaries("relationship", changes))
    return lines


def _change_summaries(scope: str, changes: list[NumericChange]) -> list[str]:
    lines: list[str] = []
    for change in changes:
        if abs(change.delta) < 0.001:
            continue
        direction = "rose" if change.delta > 0 else "fell"
        lines.append(
            f"{scope}:{change.key} {direction} from {change.before:.2f} to {change.after:.2f}"
        )
    return lines


def _append_pressure_audit(
    world_state: WorldStateV2,
    applications: list[PressureApplication],
) -> None:
    world_state.omniscient_timeline.append(
        TimelineEntry(
            entry_id=f"omn_pressure_{world_state.turn_number}",
            turn=world_state.turn_number,
            scope=TimelineScope.OMNISCIENT,
            title="Scenario Pressure Applied",
            summary="; ".join(application.rule_id for application in applications[:8]),
            source="scenario_pressure",
            tags=["scenario_pressure"],
            created_at=datetime.fromtimestamp(world_state.turn_number, tz=timezone.utc),
            metadata={"application_count": len(applications)},
        )
    )


def _action_category(action: ActionPackage) -> str:
    return str(action.metadata.get("action_category") or "")


def _action_tags(action: ActionPackage) -> set[str]:
    raw = str(action.metadata.get("action_tags") or "")
    return {tag.strip() for tag in raw.split(",") if tag.strip()}
