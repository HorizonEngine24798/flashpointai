from __future__ import annotations

import sys

from crisis_room.llm.preflight import main as preflight_main
from crisis_room.llm.smoke import main as smoke_main


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "llm-preflight":
        preflight_main(args[1:])
        return
    if args and args[0] == "llm-smoke":
        smoke_main(args[1:])
        return
    if args and args[0] in {"tui", "legacy-tui"}:
        from crisis_room.app.tui import main as tui_main

        tui_main(args[1:])
        return

    from crisis_room.web.server import main as web_main

    web_main(args)


if __name__ == "__main__":
    main()
