import os
from pathlib import Path
import subprocess
import sys

from crisis_room import __version__


def test_skeleton_imports() -> None:
    assert __version__ == "0.0.0"


def test_scenario_schema_imports_in_fresh_process() -> None:
    env = os.environ.copy()
    src_path = str(Path.cwd() / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from crisis_room.scenario.schema import "
                "build_cuban_missile_crisis_1962_scenario as build; "
                "print(build().scenario_id)"
            ),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "cuban_missile_crisis_1962"
