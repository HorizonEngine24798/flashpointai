from __future__ import annotations

import pytest

from crisis_room.app.tui import _parse_args
from crisis_room.scenario.loader import (
    ScenarioLoadError,
    available_scenario_ids,
    load_scenario,
    validate_scenario,
)
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario


def test_loader_defaults_to_valid_builtin_cuba_scenario() -> None:
    scenario = load_scenario()
    report = validate_scenario(scenario)

    assert scenario.scenario_id == "cuban_missile_crisis_1962"
    assert scenario.player_entity_id == "us_excomm"
    assert report.ok
    assert "cuban_missile_crisis_1962" in available_scenario_ids()


def test_loader_reads_explicit_scenario_json_file(tmp_path) -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    path = tmp_path / "cuba_export.json"
    path.write_text(scenario.model_dump_json(), encoding="utf-8")

    loaded = load_scenario(path)

    assert loaded.scenario_id == scenario.scenario_id
    assert loaded.metadata.title == scenario.metadata.title
    assert len(loaded.capabilities) == len(scenario.capabilities)


def test_loader_finds_scenario_by_id_in_directory(tmp_path) -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    path = tmp_path / "renamed_file.json"
    path.write_text(scenario.model_dump_json(), encoding="utf-8")

    loaded = load_scenario("cuban_missile_crisis_1962", scenario_dir=tmp_path)

    assert loaded.scenario_id == scenario.scenario_id


def test_loader_rejects_unknown_scenario_selection(tmp_path) -> None:
    with pytest.raises(ScenarioLoadError) as exc_info:
        load_scenario("missing_scenario", scenario_dir=tmp_path)

    assert "unknown scenario" in str(exc_info.value)
    assert "cuban_missile_crisis_1962" in str(exc_info.value)


def test_validation_rejects_broken_capability_generic_action_reference() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    scenario.capabilities[0] = scenario.capabilities[0].model_copy(
        update={"generic_action_id": "missing_generic_action"}
    )

    report = validate_scenario(scenario)

    assert not report.ok
    assert "missing_generic_action" in report.format_errors()
    assert "generic action" in report.format_errors()


def test_validation_rejects_broken_event_choice_capability_reference() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    choice = scenario.scenario_events[0].choices[0]
    choice.options[0] = choice.options[0].model_copy(
        update={"capability_id": "missing_capability"}
    )

    report = validate_scenario(scenario)

    assert not report.ok
    assert "missing_capability" in report.format_errors()
    assert "unknown capability" in report.format_errors()


def test_validation_rejects_broken_event_and_ending_entity_references() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    scenario.scenario_events[0] = scenario.scenario_events[0].model_copy(
        update={"related_entity_ids": ["missing_actor"]}
    )
    scenario.scenario_endings[0] = scenario.scenario_endings[0].model_copy(
        update={"required_event_ids": ["missing_event"]}
    )

    report = validate_scenario(scenario)
    formatted = report.format_errors()

    assert not report.ok
    assert "missing_actor" in formatted
    assert "missing_event" in formatted


def test_tui_accepts_launch_time_scenario_selection_args(tmp_path) -> None:
    args = _parse_args(
        [
            "--scenario",
            "cuba",
            "--scenario-dir",
            str(tmp_path),
        ]
    )

    assert args.scenario == "cuba"
    assert args.scenario_dir == tmp_path
