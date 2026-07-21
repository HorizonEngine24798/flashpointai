from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from crisis_room.app.session import GameSession
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.loader import DEFAULT_SCENARIO_ID
from crisis_room.web.api import create_app


def test_game_view_exposes_room_contract(tmp_path: Path) -> None:
    session = GameSession(
        llm_client=ScriptedLLMClient(),
        output_dir=tmp_path / "debug",
        save_dir=tmp_path / "saves",
    )

    view = session.get_view()
    payload = view.model_dump(mode="json")

    assert {
        "scenario",
        "turn",
        "scene",
        "control_room",
        "advisor_room",
        "media_room",
        "agenda",
        "settings",
        "asset_manifest",
    }.issubset(payload)
    assert 0 <= view.scene.tension_level <= 4
    assert view.scene.room_asset_key.startswith("rooms/control_tension_")
    assert view.ticker
    assert {badge.room for badge in view.nav_badges} == {
        "control",
        "advisors",
        "media",
    }
    assert view.control_room.situation_summary
    assert view.control_room.open_problems
    assert view.advisor_room.figures
    assert sum(figure.side == "left" for figure in view.advisor_room.figures) == sum(
        figure.side == "right" for figure in view.advisor_room.figures
    )
    assert all(figure.asset_key.startswith("advisors/") for figure in view.advisor_room.figures)
    assert all("faceless" not in key for key in view.asset_manifest.advisor_asset_keys)
    assert {
        figure.asset_key
        for figure in view.advisor_room.figures
    }.issubset(set(view.asset_manifest.advisor_asset_keys))
    assert view.media_room.news_items
    assert view.settings.fields

    view = session.end_turn()

    media_item = next(
        (
            item
            for item in view.media_room.news_items
            if item.source == "event_creator" and item.title == "Reconnaissance Confusion"
        ),
        None,
    )
    assert media_item is not None
    assert any(item.item_id == media_item.item_id for item in view.ticker)
    assert any(entry.entry_id == media_item.item_id for entry in view.media_room.timeline)
    assert any(
        "Reconnaissance Confusion" in line
        for line in view.control_room.recent_results
    )


def test_card_agenda_and_freeform_plan_are_mutually_exclusive(tmp_path: Path) -> None:
    session = GameSession(
        llm_client=ScriptedLLMClient(),
        output_dir=tmp_path / "debug",
        save_dir=tmp_path / "saves",
    )
    card = next(
        card
        for proposal in session.get_view().advisor_room.proposals
        for card in proposal.cards
        if card.legal_now
    )

    selected = session.select_action_card(card.card_id)
    assert selected.agenda.items
    assert selected.plan_preview is None

    planned = session.preview_plan(
        "open a private Kremlin backchannel for reciprocal restraint"
    )
    assert planned.plan_preview is not None
    assert not planned.agenda.items

    selected_again = session.select_action_card(card.card_id)
    assert selected_again.plan_preview is None
    assert selected_again.agenda.items

    session.preview_plan("open a private Kremlin backchannel for reciprocal restraint")
    cancelled = session.cancel_plan()
    assert cancelled.plan_preview is None


def test_scenario_and_new_session_endpoints_use_room_contract(tmp_path: Path) -> None:
    def session_factory(**kwargs) -> GameSession:
        return GameSession(llm_client=ScriptedLLMClient(), **kwargs)

    app = create_app(
        session_factory=session_factory,
        output_dir=tmp_path / "debug",
        save_dir=tmp_path / "saves",
    )

    with TestClient(app) as client:
        scenarios = client.get("/api/scenarios")
        assert scenarios.status_code == 200
        assert scenarios.json()[0]["scenario_id"] == DEFAULT_SCENARIO_ID

        response = client.post(
            "/api/session/new",
            json={"scenario_id": DEFAULT_SCENARIO_ID},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["start_menu"]["title"] == "The Crisis Room"
    assert payload["control_room"]["situation_summary"]
    assert "action_groups" not in payload
    assert "backchannels" not in payload
    assert "timeline" not in payload
