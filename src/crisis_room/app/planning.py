from __future__ import annotations

from pydantic import BaseModel

from crisis_room.agents.gamemaster import Gamemaster, GamemasterCompilation
from crisis_room.engine.actions import ActionDefinition, ActionPackage
from crisis_room.engine.batch_validation import (
    BatchValidationReport,
    build_batch_validation_report,
    format_batch_warning,
)
from crisis_room.state.world import WorldStateV2


class PlayerPlanPreview(BaseModel):
    turn_number: int
    player_entity_id: str
    player_intent: str
    compilation: GamemasterCompilation
    batch_validation_report: BatchValidationReport

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
    )
    return PlayerPlanPreview(
        turn_number=world_state.turn_number,
        player_entity_id=player_entity_id,
        player_intent=player_intent,
        compilation=compilation,
        batch_validation_report=batch_validation_report,
    )


def render_player_plan_preview(
    preview: PlayerPlanPreview,
    *,
    action_catalog: list[ActionDefinition],
) -> str:
    catalog = {definition.action_id: definition for definition in action_catalog}
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
            lines.append(f"{index}. {_action_line(package, catalog)}")

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
    if preview.is_committable:
        lines.extend(["", "Type COMMIT to resolve this exact plan."])
    return "\n".join(lines)


def _action_line(
    package: ActionPackage,
    catalog: dict[str, ActionDefinition],
) -> str:
    definition = catalog.get(package.action_id)
    title = definition.title if definition is not None else package.action_id
    targets = ", ".join(package.target_ids) if package.target_ids else "no direct target"
    timing = ""
    if package.requested_timing and package.requested_timing != "current_turn":
        timing = f", timing {package.requested_timing}"
    fallback = f", fallback if {package.fallback_condition}" if package.fallback_condition else ""
    return f"{title} via {package.channel.value} to {targets}{timing}{fallback}"
