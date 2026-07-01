from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import uvicorn

from crisis_room.app.session import GameSession
from crisis_room.config.gameplay import HARD_ACTION_BUDGET, NORMAL_ACTION_BUDGET
from crisis_room.scenario.loader import DEFAULT_SCENARIO_ID
from crisis_room.web.api import create_app


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    session = GameSession(
        scenario_selection=args.scenario,
        scenario_dir=args.scenario_dir,
        seed=args.seed,
        output_dir=args.output_dir,
        save_dir=args.save_dir,
        load_save_path=args.load_save,
        action_budget=args.action_budget,
        hard_action_limit=args.hard_action_limit,
        max_turns=args.max_turns,
    )
    frontend_dist = Path("frontend/dist")
    app = create_app(
        session,
        frontend_dist=frontend_dist if frontend_dist.is_dir() else None,
        scenario_dir=args.scenario_dir,
        seed=args.seed,
        output_dir=args.output_dir,
        save_dir=args.save_dir,
        action_budget=args.action_budget,
        hard_action_limit=args.hard_action_limit,
        max_turns=args.max_turns,
    )
    print(f"Crisis Room API: http://{args.host}:{args.port}/api/state")
    if frontend_dist.is_dir():
        print(f"Crisis Room GUI: http://{args.host}:{args.port}/")
    else:
        print("Frontend dev server: run `cmd /c npm run dev --prefix frontend`.")
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Crisis Room GUI API.")
    parser.add_argument("--host", default="127.0.0.1", help="local bind host")
    parser.add_argument("--port", type=int, default=8000, help="local API port")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="uvicorn log level",
    )
    parser.add_argument("--seed", type=int, default=7, help="deterministic scenario seed")
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO_ID,
        help=(
            "built-in scenario ID/alias or path to a Scenario JSON file "
            f"(default: {DEFAULT_SCENARIO_ID})"
        ),
    )
    parser.add_argument(
        "--scenario-dir",
        type=Path,
        default=None,
        help="directory of launch-time Scenario JSON files",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=10,
        help="reserved turn cap for local sessions; use 0 for unlimited",
    )
    parser.add_argument(
        "--action-budget",
        type=int,
        default=NORMAL_ACTION_BUDGET,
        help="normal number of formal player actions per turn",
    )
    parser.add_argument(
        "--hard-action-limit",
        type=int,
        default=HARD_ACTION_BUDGET,
        help="hard maximum compiler candidates before a player turn is rejected",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/debug_sessions"),
        help="directory for debug session JSON files",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=Path("saves"),
        help="directory for playable save JSON files",
    )
    parser.add_argument(
        "--load-save",
        type=Path,
        default=None,
        help="load a playable save JSON file before starting",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
