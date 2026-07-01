from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from crisis_room.app.gui_assets import scenario_thumbnail_key
from crisis_room.app.gui_schema import GameView, SaveSummaryView, ScenarioOptionView
from crisis_room.app.session import GameSession
from crisis_room.scenario.loader import (
    DEFAULT_SCENARIO_ID,
    available_scenario_ids,
    load_scenario,
)


class TextRequest(BaseModel):
    text: str


class AdvisorAskRequest(BaseModel):
    question: str


class CardRequest(BaseModel):
    card_id: str


class AgendaItemRequest(BaseModel):
    agenda_item_id: str


class SaveRequest(BaseModel):
    name: str | None = None


class LoadSaveRequest(BaseModel):
    save_id: str


class DebugToggleRequest(BaseModel):
    enabled: bool | None = None


class BackchannelRequest(BaseModel):
    target_query: str
    message_text: str


class EndingRequest(BaseModel):
    query: str = "latest"


class NewSessionRequest(BaseModel):
    scenario_id: str | None = None


def create_app(
    session: GameSession | None = None,
    *,
    frontend_dist: str | Path | None = None,
    scenario_dir: str | Path | None = None,
    seed: int = 7,
    output_dir: str | Path = "output/debug_sessions",
    save_dir: str | Path = "saves",
    action_budget: int | None = None,
    hard_action_limit: int | None = None,
    max_turns: int = 10,
    session_factory: Callable[..., GameSession] = GameSession,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.session.close()

    app = FastAPI(
        title="Crisis Room Local GUI",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    session_options = {
        "scenario_dir": scenario_dir,
        "seed": seed,
        "output_dir": output_dir,
        "save_dir": save_dir,
        "max_turns": max_turns,
    }
    if action_budget is not None:
        session_options["action_budget"] = action_budget
    if hard_action_limit is not None:
        session_options["hard_action_limit"] = hard_action_limit
    app.state.session_options = session_options
    app.state.session_factory = session_factory
    app.state.session = session or session_factory(**session_options)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/state", response_model=GameView)
    def state() -> GameView:
        return app.state.session.get_view()

    @app.get("/api/scenarios", response_model=list[ScenarioOptionView])
    def scenarios() -> list[ScenarioOptionView]:
        return [
            _scenario_option(scenario_id, scenario_dir=app.state.session_options["scenario_dir"])
            for scenario_id in available_scenario_ids(
                scenario_dir=app.state.session_options["scenario_dir"]
            )
        ]

    @app.post("/api/session/new", response_model=GameView)
    def new_session(request: NewSessionRequest) -> GameView:
        scenario_id = (request.scenario_id or DEFAULT_SCENARIO_ID).strip()
        return _replace_session(
            app,
            scenario_selection=scenario_id,
        )

    @app.post("/api/session/continue", response_model=GameView)
    def continue_latest() -> GameView:
        save = next(
            (item for item in app.state.session.list_saves() if item.compatible),
            None,
        )
        if save is None:
            raise HTTPException(status_code=404, detail="no compatible save is available")
        save_path = Path(app.state.session_options["save_dir"]) / f"{save.save_id}.json"
        return _replace_session(
            app,
            scenario_selection=save.scenario_id or DEFAULT_SCENARIO_ID,
            load_save_path=save_path,
        )

    @app.post("/api/advisors/ask", response_model=GameView)
    def ask_advisors(request: AdvisorAskRequest) -> GameView:
        return _call(lambda: app.state.session.ask_advisors(request.question))

    @app.post("/api/plan/preview", response_model=GameView)
    def preview_plan(request: TextRequest) -> GameView:
        return _call(lambda: app.state.session.preview_plan(request.text))

    @app.post("/api/plan/commit", response_model=GameView)
    def commit_plan() -> GameView:
        return _call(app.state.session.commit_plan)

    @app.post("/api/action/freeform", response_model=GameView)
    def freeform_action(request: TextRequest) -> GameView:
        return _call(lambda: app.state.session.submit_freeform_action(request.text))

    @app.post("/api/agenda/select", response_model=GameView)
    def select_agenda_card(request: CardRequest) -> GameView:
        return _call(lambda: app.state.session.select_action_card(request.card_id))

    @app.post("/api/agenda/remove", response_model=GameView)
    def remove_agenda_item(request: AgendaItemRequest) -> GameView:
        return _call(lambda: app.state.session.remove_agenda_item(request.agenda_item_id))

    @app.post("/api/agenda/clear", response_model=GameView)
    def clear_agenda() -> GameView:
        return _call(app.state.session.clear_agenda)

    @app.post("/api/agenda/commit", response_model=GameView)
    def commit_agenda() -> GameView:
        return _call(app.state.session.commit_agenda)

    @app.post("/api/turn/end", response_model=GameView)
    def end_turn() -> GameView:
        return _call(app.state.session.end_turn)

    @app.get("/api/saves", response_model=list[SaveSummaryView])
    def saves() -> list[SaveSummaryView]:
        return app.state.session.list_saves()

    @app.post("/api/saves", response_model=GameView)
    def save_game(request: SaveRequest) -> GameView:
        return _call(lambda: app.state.session.save_game(request.name))

    @app.post("/api/saves/load", response_model=GameView)
    def load_save(request: LoadSaveRequest) -> GameView:
        return _call(lambda: app.state.session.load_save(request.save_id))

    @app.post("/api/debug/toggle", response_model=GameView)
    def toggle_debug(request: DebugToggleRequest) -> GameView:
        return _call(lambda: app.state.session.toggle_debug(request.enabled))

    @app.get("/api/backchannels", response_model=GameView)
    def backchannels() -> GameView:
        return app.state.session.get_view()

    @app.post("/api/backchannels/send", response_model=GameView)
    def send_backchannel(request: BackchannelRequest) -> GameView:
        return _call(
            lambda: app.state.session.send_backchannel(
                request.target_query,
                request.message_text,
            )
        )

    @app.post("/api/endings/accept", response_model=GameView)
    def accept_ending(request: EndingRequest) -> GameView:
        return _call(lambda: app.state.session.accept_ending(request.query))

    @app.post("/api/endings/reject", response_model=GameView)
    def reject_ending(request: EndingRequest) -> GameView:
        return _call(lambda: app.state.session.reject_ending(request.query))

    if frontend_dist is not None:
        static_dir = Path(frontend_dist)
        if static_dir.is_dir():
            app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def _replace_session(
    app: FastAPI,
    *,
    scenario_selection: str,
    load_save_path: Path | None = None,
) -> GameView:
    old_session = app.state.session
    try:
        next_session = app.state.session_factory(
            scenario_selection=scenario_selection,
            load_save_path=load_save_path,
            **app.state.session_options,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    app.state.session = next_session
    close = getattr(old_session, "close", None)
    if callable(close):
        close()
    return next_session.get_view()


def _scenario_option(
    scenario_id: str,
    *,
    scenario_dir: str | Path | None,
) -> ScenarioOptionView:
    scenario = load_scenario(scenario_id, scenario_dir=scenario_dir)
    return ScenarioOptionView(
        scenario_id=scenario.scenario_id,
        title=scenario.metadata.title,
        historical_period=scenario.metadata.historical_period,
        description=scenario.metadata.description,
        thumbnail_asset_key=scenario_thumbnail_key(scenario.scenario_id),
    )


def _call(operation):
    try:
        return operation()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
