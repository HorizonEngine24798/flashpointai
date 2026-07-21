from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.agents.gamemaster import Gamemaster, GamemasterCompilation
from crisis_room.config.gameplay import (
    ACTION_CARD_LEAK_RISK_THRESHOLD,
    HIGH_ESCALATION_RISK_THRESHOLD,
    MEANINGFUL_ESCALATION_RISK_THRESHOLD,
    PLAN_PREVIEW_BACKCHANNEL_LIMIT,
    PLAN_PREVIEW_CONSEQUENCE_LIMIT,
    PLAN_PREVIEW_FLASH_RISK_LIMIT,
    PLAN_PREVIEW_PENDING_ACTION_LIMIT,
    PLAN_PREVIEW_RECENT_EVENT_LIMIT,
    PLAN_PREVIEW_RESOURCE_PRESSURE_LIMIT,
    VISIBLE_CHANGE_THRESHOLD,
)
from crisis_room.engine.actions import (
    ActionDefinition,
    ActionPackage,
    ActionResolver,
    ScenarioCapability,
)
from crisis_room.engine.batch_validation import (
    BatchValidationReport,
    build_batch_validation_report,
    format_batch_warning,
)
from crisis_room.scenario.events import ScenarioEventDefinition
from crisis_room.state.backchannels import BackchannelThreadStatus
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import WorldStateV2


class PlayerPlanPreview(BaseModel):
    turn_number: int
    player_entity_id: str
    player_intent: str
    compilation: GamemasterCompilation
    batch_validation_report: BatchValidationReport
    known_pending_actions: list[str] = Field(default_factory=list)
    resource_pressure: list[str] = Field(default_factory=list)
    open_backchannel_constraints: list[str] = Field(default_factory=list)
    recent_event_context: list[str] = Field(default_factory=list)
    visible_flash_event_risks: list[str] = Field(default_factory=list)
    known_consequences: list[str] = Field(default_factory=list)

    @property
    def is_committable(self) -> bool:
        return not self.compilation.rejected and bool(self.compilation.action_packages)


def build_player_plan_preview(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    player_intent: str,
    gamemaster: Gamemaster,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None = None,
    scenario_events: list[ScenarioEventDefinition] | None = None,
) -> PlayerPlanPreview:
    compilation = gamemaster.compile_player_intent(
        world_state,
        player_entity_id,
        player_intent,
    )
    action_packages = [] if compilation.rejected else compilation.action_packages
    batch_validation_report = build_batch_validation_report(
        world_state,
        action_packages,
        action_catalog,
        player_entity_id=player_entity_id,
        capabilities=capabilities,
        action_budget=compilation.action_budget,
    )
    return PlayerPlanPreview(
        turn_number=world_state.turn_number,
        player_entity_id=player_entity_id,
        player_intent=player_intent,
        compilation=compilation,
        batch_validation_report=batch_validation_report,
        known_pending_actions=_known_pending_actions(
            world_state,
            player_entity_id,
            action_catalog,
            capabilities,
        ),
        resource_pressure=_resource_pressure(
            world_state,
            action_packages,
            player_entity_id,
            action_catalog,
            capabilities,
        ),
        open_backchannel_constraints=_open_backchannel_constraints(
            world_state,
            player_entity_id,
        ),
        recent_event_context=_recent_event_context(world_state, player_entity_id),
        visible_flash_event_risks=_visible_flash_event_risks(
            world_state,
            player_entity_id,
            action_packages,
            scenario_events or [],
        ),
        known_consequences=_known_consequences(
            action_packages,
            action_catalog,
            capabilities,
        ),
    )


def render_player_plan_preview(
    preview: PlayerPlanPreview,
    *,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None = None,
) -> str:
    resolver = ActionResolver(action_catalog, capabilities)
    lines = [
        "PLAN PREVIEW",
        f"Turn: {preview.turn_number}",
        f"Intent: {preview.player_intent}",
        "",
    ]
    if preview.compilation.rejected:
        lines.append("No committable plan was compiled.")
    elif not preview.compilation.action_packages:
        lines.append("No formal actions were compiled.")
    else:
        lines.append("Compiled actions:")
        for index, package in enumerate(preview.compilation.action_packages, start=1):
            lines.append(f"{index}. {_action_line(package, resolver)}")
        lines.extend(
            [
                "",
                f"Action budget: {len(preview.compilation.action_packages)} / "
                f"{preview.compilation.action_budget} slots used.",
            ]
        )
        if len(preview.compilation.action_packages) > 1:
            lines.append("Each compiled action consumes one formal action slot.")

    if preview.compilation.compiled_intents:
        lines.extend(["", "Compiled intents:"])
        lines.extend(f"- {intent}" for intent in preview.compilation.compiled_intents)
    if preview.compilation.rejected_intents:
        lines.extend(["", "Rejected intents:"])
        lines.extend(f"- {intent}" for intent in preview.compilation.rejected_intents)
    if preview.compilation.unprocessed_intents:
        lines.extend(["", "Unprocessed intents:"])
        lines.extend(f"- {intent}" for intent in preview.compilation.unprocessed_intents)

    visible_warnings = [
        format_batch_warning(warning)
        for warning in preview.batch_validation_report.warnings
        if warning.player_visible
    ]
    if visible_warnings:
        lines.extend(["", "Agenda warnings:"])
        lines.extend(f"- {warning}" for warning in visible_warnings)
    if preview.compilation.errors:
        lines.extend(["", "Compiler errors:"])
        lines.extend(f"- {error}" for error in preview.compilation.errors)
    if preview.compilation.notes:
        lines.extend(["", "Compiler notes:"])
        lines.extend(f"- {note}" for note in preview.compilation.notes[:6])
    if preview.known_pending_actions:
        lines.extend(["", "Known pending actions:"])
        lines.extend(f"- {item}" for item in preview.known_pending_actions)
    if preview.resource_pressure:
        lines.extend(["", "Resource pressure:"])
        lines.extend(f"- {item}" for item in preview.resource_pressure)
    if preview.open_backchannel_constraints:
        lines.extend(["", "Open backchannel constraints:"])
        lines.extend(f"- {item}" for item in preview.open_backchannel_constraints)
    if preview.recent_event_context:
        lines.extend(["", "Recent event context:"])
        lines.extend(f"- {item}" for item in preview.recent_event_context)
    if preview.visible_flash_event_risks:
        lines.extend(["", "Visible flash-event risks:"])
        lines.extend(f"- {item}" for item in preview.visible_flash_event_risks)
    if preview.known_consequences:
        lines.extend(["", "Known consequences and risks:"])
        lines.extend(f"- {item}" for item in preview.known_consequences)
    if preview.is_committable:
        lines.extend(["", "Type COMMIT to resolve this exact plan."])
    else:
        lines.extend(
            [
                "",
                "Try next:",
                "- Type ACTIONS to inspect legal action names.",
                (
                    "- Name the action and target directly, for example: "
                    "ACTION open a private Kremlin channel to soviet_presidium."
                ),
            ]
        )
    return "\n".join(lines)


def _action_line(
    package: ActionPackage,
    resolver: ActionResolver,
) -> str:
    definition, errors = resolver.resolve_package(package)
    title = definition.title if definition is not None and not errors else package.mechanical_id
    targets = ", ".join(package.target_ids) if package.target_ids else "no direct target"
    return f"{title} via {package.channel.value} to {targets}"


def _known_pending_actions(
    world_state: WorldStateV2,
    player_entity_id: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None,
) -> list[str]:
    resolver = ActionResolver(action_catalog, capabilities)
    lines: list[str] = []
    for package in world_state.pending_actions:
        if not _pending_action_visible_to_player(package, player_entity_id):
            continue
        definition, errors = resolver.resolve_package(package)
        title = definition.title if definition is not None and not errors else package.mechanical_id
        ready_turn = package.metadata.get("ready_turn")
        timing = f" due turn {ready_turn}" if isinstance(ready_turn, int) else " still pending"
        actor = world_state.actors.get(package.actor_id)
        actor_name = actor.name if actor is not None else package.actor_id
        lines.append(f"{actor_name}: {title}{timing}.")
    return lines[:PLAN_PREVIEW_PENDING_ACTION_LIMIT]


def _resource_pressure(
    world_state: WorldStateV2,
    action_packages: list[ActionPackage],
    player_entity_id: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None,
) -> list[str]:
    player = world_state.actors.get(player_entity_id)
    if player is None:
        return []
    resolver = ActionResolver(action_catalog, capabilities)
    costs: dict[str, int] = {}
    requirements: dict[str, int] = {}
    for package in action_packages:
        if package.actor_id != player_entity_id:
            continue
        definition, errors = resolver.resolve_package(package)
        if definition is None or errors:
            continue
        for resource, amount in _resource_spend(definition).items():
            costs[resource] = costs.get(resource, 0) + amount
        for resource, amount in definition.required_resources.items():
            requirements[resource] = max(requirements.get(resource, 0), amount)

    lines: list[str] = []
    for resource, amount in sorted(costs.items()):
        available = int(player.resources.get(resource, 0))
        if amount > available:
            lines.append(f"{resource}: {amount} requested, {available} available.")
        else:
            lines.append(f"{resource}: {amount} committed out of {available} available.")
    for resource, amount in sorted(requirements.items()):
        if resource in costs:
            continue
        available = int(player.resources.get(resource, 0))
        lines.append(f"{resource}: requires {amount}, {available} available.")
    return lines[:PLAN_PREVIEW_RESOURCE_PRESSURE_LIMIT]


def _open_backchannel_constraints(
    world_state: WorldStateV2,
    player_entity_id: str,
) -> list[str]:
    lines: list[str] = []
    for thread in world_state.backchannel_threads.values():
        if player_entity_id not in thread.participant_entity_ids:
            continue
        if thread.status != BackchannelThreadStatus.OPEN:
            continue
        if thread.expires_turn < world_state.turn_number:
            continue
        counterparts = [
            world_state.actors[entity_id].name
            for entity_id in thread.participant_entity_ids
            if entity_id != player_entity_id and entity_id in world_state.actors
        ]
        counterpart = ", ".join(counterparts) or "unknown counterpart"
        turns_left = max(0, thread.expires_turn - world_state.turn_number)
        lines.append(
            f"{counterpart}: "
            f"{thread.player_messages_remaining_for_turn(world_state.turn_number)} "
            "direct message(s) left, "
            f"expires in {turns_left} turn(s)."
        )
    return lines[:PLAN_PREVIEW_BACKCHANNEL_LIMIT]


def _recent_event_context(
    world_state: WorldStateV2,
    player_entity_id: str,
) -> list[str]:
    lines: list[str] = []
    for record in reversed(world_state.event_history):
        if not record.active_for(world_state.turn_number, player_entity_id):
            continue
        title = record.problem_title or record.title
        summary = record.problem_summary or record.summary
        lines.append(f"{title}: {summary}")
    return lines[:PLAN_PREVIEW_RECENT_EVENT_LIMIT]


def _visible_flash_event_risks(
    world_state: WorldStateV2,
    player_entity_id: str,
    action_packages: list[ActionPackage],
    scenario_events: list[ScenarioEventDefinition],
) -> list[str]:
    action_ids = {package.mechanical_id for package in action_packages}
    lines: list[str] = []
    for event in scenario_events:
        if not event.enabled:
            continue
        if event.trigger.once and any(
            record.event_id == event.event_id for record in world_state.event_history
        ):
            continue
        required_any = set(event.trigger.required_any_action_ids)
        required_all = set(event.trigger.required_action_ids)
        if required_any and not required_any.intersection(action_ids):
            continue
        if required_all and not required_all.issubset(action_ids):
            continue
        if not required_any and not required_all:
            continue
        if event.visible_to and player_entity_id not in event.visible_to:
            continue
        title = event.problem_title or event.title
        summary = event.problem_summary or event.summary
        lines.append(f"{title}: {summary}")
    return lines[:PLAN_PREVIEW_FLASH_RISK_LIMIT]


def _known_consequences(
    action_packages: list[ActionPackage],
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None,
) -> list[str]:
    resolver = ActionResolver(action_catalog, capabilities)
    lines: list[str] = []
    for package in action_packages:
        definition, errors = resolver.resolve_package(package)
        if definition is None or errors:
            continue
        pressure = _expected_pressure_summary(definition)
        risk = _risk_summary(definition)
        timing = ""
        if definition.preparation_turns + max(0, definition.execution_turns - 1) > 0:
            timing = " Resolves later."
        lines.append(f"{definition.title}: {pressure}; {risk}.{timing}".strip())
    return lines[:PLAN_PREVIEW_CONSEQUENCE_LIMIT]


def _pending_action_visible_to_player(package: ActionPackage, player_entity_id: str) -> bool:
    if package.actor_id == player_entity_id:
        return True
    if package.channel == SignalChannel.PUBLIC:
        return True
    return player_entity_id in package.target_ids and package.channel in {
        SignalChannel.INTEL,
        SignalChannel.MILITARY,
    }


def _resource_spend(definition: ActionDefinition) -> dict[str, int]:
    spend = dict(definition.resource_costs)
    for resource, delta in definition.actor_resource_effects.items():
        if delta < 0 and resource not in spend:
            spend[resource] = abs(delta)
    return spend


def _expected_pressure_summary(definition: ActionDefinition) -> str:
    phrases: list[str] = []
    for key, delta in {
        **definition.truth_metric_effects,
        **definition.public_metric_effects,
        **definition.clock_effects,
    }.items():
        phrase = _effect_phrase(key, float(delta))
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    if definition.deescalation_potential >= MEANINGFUL_ESCALATION_RISK_THRESHOLD:
        phrases.append("off-ramp pressure improves")
    return ", ".join(phrases) or "effects uncertain before resolution"


def _effect_phrase(key: str, delta: float) -> str:
    if abs(delta) < VISIBLE_CHANGE_THRESHOLD:
        return ""
    direction = "rises" if delta > 0 else "falls"
    if "offramp" in key or "off-ramp" in key or "backchannel" in key:
        return f"off-ramp viability {direction}"
    if "alliance" in key or "allied" in key:
        return f"alliance cohesion {direction}"
    if "alarm" in key or "anxiety" in key:
        return f"public pressure {direction}"
    if "escalation" in key or "risk" in key or "invasion" in key:
        return f"incident risk {direction}"
    if "missile" in key:
        return f"missile clarity {direction}"
    return f"{key.replace('_', ' ')} {direction}"


def _risk_summary(definition: ActionDefinition) -> str:
    pieces: list[str] = []
    if definition.escalation_risk >= HIGH_ESCALATION_RISK_THRESHOLD:
        pieces.append("high escalation risk")
    elif definition.escalation_risk >= MEANINGFUL_ESCALATION_RISK_THRESHOLD:
        pieces.append("meaningful escalation risk")
    else:
        pieces.append("contained escalation risk")
    if definition.signal_leak_risk >= ACTION_CARD_LEAK_RISK_THRESHOLD:
        pieces.append("leak risk")
    return ", ".join(pieces)
