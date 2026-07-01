from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import re

from pydantic import ValidationError

from crisis_room.scenario.schema import Scenario, build_cuban_missile_crisis_1962_scenario
from crisis_room.state.timelines import TimelineEntry


DEFAULT_SCENARIO_ID = "cuban_missile_crisis_1962"

_BUILT_IN_SCENARIOS: dict[str, Callable[[], Scenario]] = {
    DEFAULT_SCENARIO_ID: build_cuban_missile_crisis_1962_scenario,
}

_SCENARIO_ALIASES: dict[str, str] = {
    "default": DEFAULT_SCENARIO_ID,
    "cuba": DEFAULT_SCENARIO_ID,
    "cuban_missile_crisis": DEFAULT_SCENARIO_ID,
}

_STABLE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class ScenarioLoadError(ValueError):
    """Raised when a launch-time scenario cannot be loaded safely."""


@dataclass
class ScenarioValidationReport:
    scenario_id: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def format_errors(self) -> str:
        if not self.errors:
            return "scenario validation passed"
        return "\n".join(f"- {error}" for error in self.errors)


def load_scenario(
    selection: str | Path | None = None,
    *,
    scenario_dir: str | Path | None = None,
) -> Scenario:
    """Load a built-in or JSON-authored scenario once at launch."""

    query = _normalize_selection(selection)
    source_path = _resolve_scenario_file(query, scenario_dir=scenario_dir)
    if source_path is not None:
        scenario = load_scenario_file(source_path)
    else:
        scenario_id = _SCENARIO_ALIASES.get(query, query)
        builder = _BUILT_IN_SCENARIOS.get(scenario_id)
        if builder is None:
            known = ", ".join(available_scenario_ids(scenario_dir=scenario_dir))
            raise ScenarioLoadError(
                f"unknown scenario {query!r}. Available scenarios: {known or '(none)'}"
            )
        scenario = builder()

    report = validate_scenario(scenario)
    if not report.ok:
        raise ScenarioLoadError(
            f"scenario {scenario.scenario_id!r} failed validation:\n{report.format_errors()}"
        )
    return scenario


def load_scenario_file(path: str | Path) -> Scenario:
    scenario_path = Path(path)
    try:
        raw = scenario_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScenarioLoadError(f"failed to read scenario file {scenario_path}: {exc}") from exc
    try:
        return Scenario.model_validate_json(raw)
    except ValidationError as exc:
        raise ScenarioLoadError(
            f"scenario file {scenario_path} is not a valid Scenario JSON: {exc}"
        ) from exc


def available_scenario_ids(*, scenario_dir: str | Path | None = None) -> list[str]:
    ids = set(_BUILT_IN_SCENARIOS)
    if scenario_dir is not None:
        for path in _iter_scenario_files(Path(scenario_dir)):
            scenario_id = _peek_scenario_id(path)
            ids.add(scenario_id or path.stem)
    return sorted(ids)


def validate_scenario(scenario: Scenario) -> ScenarioValidationReport:
    report = ScenarioValidationReport(scenario_id=scenario.scenario_id)
    entity_ids = [entity.entity_id for entity in scenario.entities]
    entity_id_set = set(entity_ids)
    action_ids = [action.action_id for action in scenario.action_catalog]
    action_id_set = set(action_ids)
    capability_ids = [capability.capability_id for capability in scenario.capabilities]
    capability_id_set = set(capability_ids)
    mechanical_ids = action_id_set | capability_id_set
    event_ids = [event.event_id for event in scenario.scenario_events]
    event_id_set = set(event_ids)
    ending_ids = [ending.ending_id for ending in scenario.scenario_endings]
    ending_id_set = set(ending_ids)

    _validate_stable_id(report, "scenario.scenario_id", scenario.scenario_id)
    _validate_unique_ids(report, "entities", entity_ids)
    _validate_unique_ids(report, "action_catalog", action_ids)
    _validate_unique_ids(report, "capabilities", capability_ids)
    _validate_unique_ids(report, "scenario_events", event_ids)
    _validate_unique_ids(report, "scenario_endings", ending_ids)
    _validate_entity_references(report, scenario, entity_id_set)
    _validate_action_and_capability_references(
        report,
        scenario,
        entity_id_set=entity_id_set,
        action_id_set=action_id_set,
        capability_id_set=capability_id_set,
    )
    _validate_event_references(
        report,
        scenario,
        entity_id_set=entity_id_set,
        action_id_set=action_id_set,
        capability_id_set=capability_id_set,
        mechanical_ids=mechanical_ids,
        event_id_set=event_id_set,
    )
    _validate_ending_references(
        report,
        scenario,
        entity_id_set=entity_id_set,
        event_id_set=event_id_set,
        ending_id_set=ending_id_set,
    )
    if not scenario.action_catalog:
        report.warnings.append("scenario.action_catalog is empty; gameplay compilation will be limited")
    if not scenario.capabilities:
        report.warnings.append("scenario.capabilities is empty; generated scenarios should define capabilities")
    return report


def _normalize_selection(selection: str | Path | None) -> str:
    if selection is None:
        return DEFAULT_SCENARIO_ID
    query = str(selection).strip()
    return query or DEFAULT_SCENARIO_ID


def _resolve_scenario_file(
    query: str,
    *,
    scenario_dir: str | Path | None,
) -> Path | None:
    direct = Path(query)
    if direct.is_file():
        return direct
    if scenario_dir is None:
        return None
    directory = Path(scenario_dir)
    candidates = [directory / query]
    if not direct.suffix:
        candidates.extend(
            [
                directory / f"{query}.json",
                directory / f"{query}.scenario.json",
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for path in _iter_scenario_files(directory):
        if _peek_scenario_id(path) == query:
            return path
    return None


def _iter_scenario_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def _peek_scenario_id(path: Path) -> str | None:
    try:
        return Scenario.model_validate_json(path.read_text(encoding="utf-8")).scenario_id
    except (OSError, ValidationError):
        return None


def _validate_entity_references(
    report: ScenarioValidationReport,
    scenario: Scenario,
    entity_id_set: set[str],
) -> None:
    _validate_stable_ids(report, "entities[*].entity_id", entity_id_set)
    _require_known_reference(
        report,
        "scenario.player_entity_id",
        scenario.player_entity_id,
        known=entity_id_set,
        kind="entity",
    )
    for entity in scenario.entities:
        _validate_stable_id(report, f"entities.{entity.entity_id}.entity_id", entity.entity_id)
    _require_known_references(
        report,
        "initial_entity_timelines",
        scenario.initial_entity_timelines.keys(),
        known=entity_id_set,
        kind="entity",
    )
    for entity_id, entries in scenario.initial_entity_timelines.items():
        for index, entry in enumerate(entries):
            _validate_timeline_references(
                report,
                f"initial_entity_timelines.{entity_id}[{index}]",
                entry,
                entity_id_set,
            )
    for index, entry in enumerate(scenario.initial_public_timeline):
        _validate_timeline_references(
            report,
            f"initial_public_timeline[{index}]",
            entry,
            entity_id_set,
        )
    for index, entry in enumerate(scenario.initial_omniscient_timeline):
        _validate_timeline_references(
            report,
            f"initial_omniscient_timeline[{index}]",
            entry,
            entity_id_set,
        )
    for owner_id, council in scenario.initial_advisor_councils.items():
        _require_known_reference(
            report,
            "initial_advisor_councils",
            owner_id,
            known=entity_id_set,
            kind="entity",
        )
        if council.player_entity_id and council.player_entity_id != owner_id:
            report.errors.append(
                "initial_advisor_councils."
                f"{owner_id} has mismatched player_entity_id {council.player_entity_id!r}"
            )
        _validate_stable_ids(
            report,
            f"initial_advisor_councils.{owner_id}.advisors",
            council.advisors.keys(),
        )


def _validate_action_and_capability_references(
    report: ScenarioValidationReport,
    scenario: Scenario,
    *,
    entity_id_set: set[str],
    action_id_set: set[str],
    capability_id_set: set[str],
) -> None:
    _validate_stable_ids(report, "action_catalog[*].action_id", action_id_set)
    _validate_stable_ids(report, "capabilities[*].capability_id", capability_id_set)
    for action in scenario.action_catalog:
        _require_known_references(
            report,
            f"action_catalog.{action.action_id}.actor_ids_allowed",
            action.actor_ids_allowed,
            known=entity_id_set,
            kind="entity",
        )
        _require_known_references(
            report,
            f"action_catalog.{action.action_id}.target_ids_allowed",
            action.target_ids_allowed,
            known=entity_id_set,
            kind="entity",
        )
    for capability in scenario.capabilities:
        _require_known_reference(
            report,
            f"capabilities.{capability.capability_id}.generic_action_id",
            capability.generic_action_id,
            known=action_id_set,
            kind="generic action",
        )
        _require_known_references(
            report,
            f"capabilities.{capability.capability_id}.actor_ids_allowed",
            capability.actor_ids_allowed,
            known=entity_id_set,
            kind="entity",
        )
        _require_known_references(
            report,
            f"capabilities.{capability.capability_id}.target_ids_allowed",
            capability.target_ids_allowed,
            known=entity_id_set,
            kind="entity",
        )


def _validate_event_references(
    report: ScenarioValidationReport,
    scenario: Scenario,
    *,
    entity_id_set: set[str],
    action_id_set: set[str],
    capability_id_set: set[str],
    mechanical_ids: set[str],
    event_id_set: set[str],
) -> None:
    _validate_stable_ids(report, "scenario_events[*].event_id", event_id_set)
    capability_by_id = {capability.capability_id: capability for capability in scenario.capabilities}
    for event in scenario.scenario_events:
        path = f"scenario_events.{event.event_id}"
        for suffix, values, known, kind in [
            ("trigger.required_action_ids", event.trigger.required_action_ids, mechanical_ids, "mechanical action"),
            (
                "trigger.required_any_action_ids",
                event.trigger.required_any_action_ids,
                mechanical_ids,
                "mechanical action",
            ),
            ("trigger.excluded_action_ids", event.trigger.excluded_action_ids, mechanical_ids, "mechanical action"),
            (
                "trigger.required_any_leaked_signal_action_ids",
                event.trigger.required_any_leaked_signal_action_ids,
                action_id_set,
                "generic action",
            ),
            (
                "trigger.required_any_leaked_signal_capability_ids",
                event.trigger.required_any_leaked_signal_capability_ids,
                capability_id_set,
                "capability",
            ),
            ("related_entity_ids", event.related_entity_ids, entity_id_set, "entity"),
            ("related_action_ids", event.related_action_ids, mechanical_ids, "mechanical action"),
            ("visible_to", event.visible_to, entity_id_set, "entity"),
        ]:
            _require_known_references(report, f"{path}.{suffix}", values, known=known, kind=kind)
        _validate_relationship_effect_pairs(
            report,
            f"{path}.effects.relationship_effects",
            event.effects.relationship_effects.keys(),
            entity_id_set,
        )
        for signal_index, signal in enumerate(event.signals):
            _require_known_references(
                report,
                f"{path}.signals[{signal_index}].target_entity_ids",
                signal.target_entity_ids,
                known=entity_id_set,
                kind="entity",
            )
        _validate_event_choice_references(
            report,
            event_path=path,
            event=event,
            entity_id_set=entity_id_set,
            action_id_set=action_id_set,
            capability_by_id=capability_by_id,
        )


def _validate_event_choice_references(
    report: ScenarioValidationReport,
    *,
    event_path: str,
    event: object,
    entity_id_set: set[str],
    action_id_set: set[str],
    capability_by_id: dict[str, object],
) -> None:
    choice_ids = [choice.choice_id for choice in event.choices]
    _validate_unique_ids(report, f"{event_path}.choices", choice_ids)
    _validate_stable_ids(report, f"{event_path}.choices[*].choice_id", choice_ids)
    for choice in event.choices:
        choice_path = f"{event_path}.choices.{choice.choice_id}"
        _require_known_references(
            report,
            f"{choice_path}.visible_to",
            choice.visible_to,
            known=entity_id_set,
            kind="entity",
        )
        option_ids = [option.option_id for option in choice.options]
        _validate_unique_ids(report, f"{choice_path}.options", option_ids)
        _validate_stable_ids(report, f"{choice_path}.options[*].option_id", option_ids)
        for option in choice.options:
            option_path = f"{choice_path}.options.{option.option_id}"
            _require_known_reference(
                report,
                f"{option_path}.action_id",
                option.action_id,
                known=action_id_set,
                kind="generic action",
            )
            capability = capability_by_id.get(option.capability_id)
            if capability is None:
                report.errors.append(
                    f"{option_path}.capability_id references unknown capability "
                    f"{option.capability_id!r}"
                )
            elif capability.generic_action_id != option.action_id:
                report.errors.append(
                    f"{option_path} uses action {option.action_id!r}, but capability "
                    f"{option.capability_id!r} requires {capability.generic_action_id!r}"
                )
            _require_known_references(
                report,
                f"{option_path}.target_ids",
                option.target_ids,
                known=entity_id_set,
                kind="entity",
            )


def _validate_ending_references(
    report: ScenarioValidationReport,
    scenario: Scenario,
    *,
    entity_id_set: set[str],
    event_id_set: set[str],
    ending_id_set: set[str],
) -> None:
    _validate_stable_ids(report, "scenario_endings[*].ending_id", ending_id_set)
    event_or_ending_ids = event_id_set | ending_id_set
    for ending in scenario.scenario_endings:
        path = f"scenario_endings.{ending.ending_id}"
        for suffix, values, known, kind in [
            ("visible_to", ending.visible_to, entity_id_set, "entity"),
            ("related_entity_ids", ending.related_entity_ids, entity_id_set, "entity"),
            ("required_event_ids", ending.required_event_ids, event_or_ending_ids, "event or ending"),
            ("excluded_event_ids", ending.excluded_event_ids, event_or_ending_ids, "event or ending"),
        ]:
            _require_known_references(report, f"{path}.{suffix}", values, known=known, kind=kind)


def _validate_timeline_references(
    report: ScenarioValidationReport,
    path: str,
    entry: TimelineEntry,
    entity_id_set: set[str],
) -> None:
    _require_known_references(
        report,
        f"{path}.visible_to",
        entry.visible_to,
        known=entity_id_set,
        kind="entity",
    )


def _validate_relationship_effect_pairs(
    report: ScenarioValidationReport,
    path: str,
    pairs: object,
    entity_id_set: set[str],
) -> None:
    for pair in pairs:
        if not isinstance(pair, str) or "->" not in pair:
            report.errors.append(f"{path} has invalid relationship pair {pair!r}")
            continue
        for entity_id in pair.split("->", 1):
            _require_known_reference(
                report,
                path,
                entity_id,
                known=entity_id_set,
                kind="entity",
            )


def _validate_unique_ids(
    report: ScenarioValidationReport,
    path: str,
    ids: object,
) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in ids:
        if not isinstance(item, str):
            continue
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    if duplicates:
        report.errors.append(f"{path} has duplicate IDs: {', '.join(sorted(duplicates))}")


def _validate_stable_ids(
    report: ScenarioValidationReport,
    path: str,
    ids: object,
) -> None:
    for item in ids:
        if isinstance(item, str):
            _validate_stable_id(report, path, item)


def _validate_stable_id(
    report: ScenarioValidationReport,
    path: str,
    value: str,
) -> None:
    if not value or not _STABLE_ID_RE.fullmatch(value):
        report.errors.append(
            f"{path} has unstable ID {value!r}; use lowercase letters, digits, "
            "underscore, or hyphen, starting with a letter"
        )


def _require_known_references(
    report: ScenarioValidationReport,
    path: str,
    values: object,
    *,
    known: set[str],
    kind: str,
) -> None:
    for value in values:
        if isinstance(value, str):
            _require_known_reference(report, path, value, known=known, kind=kind)


def _require_known_reference(
    report: ScenarioValidationReport,
    path: str,
    value: str,
    *,
    known: set[str],
    kind: str,
) -> None:
    if value not in known:
        report.errors.append(f"{path} references unknown {kind} {value!r}")
