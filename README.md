# Crisis Room Simulation

A local browser-based political-military crisis room simulator. The default
scenario is the Cuban Missile Crisis, with the player inhabiting U.S. EXCOMM.

## Start The GUI

The GUI has two local pieces:

- a Python FastAPI backend that owns the game session and talks to llama.cpp
- a React/Vite frontend that renders the room-based browser GUI

For day-to-day development, run them in two terminals.

### 1. Start The Backend

Open **Terminal 1** in the repo root and run:

```bash
conda activate polmil
python main.py
```

Expected output includes:

```text
Crisis Room API: http://127.0.0.1:8000/api/state
```

Leave this terminal running.

### 3. Start The Frontend

Open **Terminal 2** in the repo root and run:

```bash
conda activate polmil
npm run dev --prefix frontend
```

Expected output includes a local Vite URL, usually:

```text
http://127.0.0.1:5173
```

Open that URL in your browser. The GUI opens to `The Crisis Room` start screen.
Start a new Cuban Missile Crisis scenario to enter the Control Room.

### 4. Stop The GUI

Press `Ctrl+C` in both terminals. If a background backend is still running, find
and stop it from PowerShell:

```powershell
Get-Process python
Stop-Process -Id <PID>
```

### What The Backend Does

- loads `config/llama_cpp.local.json`
- starts `llama-server.exe` when the first LLM-backed action needs it
- loads the local HauhauCS Qwen3.5 35B uncensored GGUF model
- uses `http://127.0.0.1:8080/v1` for game LLM calls
- exposes the game API at `http://127.0.0.1:8000/api/state`

First LLM use can take a while because the model has to load. Logs are written
under `output/diagnostics/llama_server/`.

## One-Terminal Built GUI

After building the frontend, the Python backend can serve the browser files by
itself. This is less convenient for active UI editing, but simpler when you just
want to play.

From the repo root:

```powershell
cmd /c npm run build --prefix frontend
C:\Users\User\Miniconda3\Scripts\conda.exe run -n polmil python main.py
```

Then open:

```text
http://127.0.0.1:8000
```

## Terminal TUI

The terminal interface remains available as a fallback:

```powershell
C:\Users\User\Miniconda3\Scripts\conda.exe run -n polmil python main.py tui
```

Legacy commands:

```text
ASK <text>      Ask advisors a question
<text>          Same as ASK <text>
PLAN <text>     Preview compiled actions without resolving a turn
COMMIT          Resolve the last previewed plan
ACTION <text>   Submit up to 3 formal actions and resolve one turn
BACKCHANNEL <target> <message>
                Send one scarce direct message through an open thread
END             Take no formal action and let the turn resolve
BRIEFING        Reprint problems, pressure, agenda, and action cards
STATUS          Same as BRIEFING
ADVISORS        Show persistent council state
BACKCHANNELS    Show active backchannel threads
DEBUG           Toggle raw turn debug output
DUMP            Toggle full debug dump mode
PLAYER          Return to player-visible mode
SAVE            Save the session JSON now
HELP            Show commands
QUIT            Save, exit, and close the managed server
```

Turns can also produce authored flash events. These are scenario-defined
interruptions with deterministic effects, routed signals, and short-lived
problems in the next briefing.

Useful first moves:

```text
ASK How do we keep an off-ramp open?
PLAN announce a quarantine, open a private Kremlin channel, and authorize recon overflights
COMMIT
ACTION announce a naval quarantine while keeping a private Kremlin channel open
ACTION announce a quarantine, open a private Kremlin channel, and authorize recon overflights
ACTION open a private Kremlin backchannel for reciprocal restraint
BACKCHANNEL soviet_presidium Would a private non-invasion pledge make withdrawal possible?
ACTION float a secret Jupiter missile trade through the backchannel
ACTION offer a non-invasion pledge if the missiles are removed
ACTION authorize more U-2 reconnaissance overflights
END
```

## Config

The default local config is:

```text
config/llama_cpp.local.json
```

It is ignored by git so machine-specific paths stay local. To create it on
another machine:

```powershell
Copy-Item config/llama_cpp.example.json config/llama_cpp.local.json
```

Then edit these two values:

```text
server_executable    absolute path to llama-server.exe
server_model_path    absolute path to the Qwen GGUF model
```

Runtime gameplay uses the live local llama.cpp path. Automated tests may still
use isolated deterministic doubles so the fast suite does not require a loaded
model.

## Development Baseline

The supported test command for this repo is:

```powershell
C:\Users\User\Miniconda3\Scripts\conda.exe run -n polmil python -m pytest tests -q -p no:cacheprovider
```

As of 2026-06-24, the expected result is `77 passed, 4 skipped`.

Keep `config/llama_cpp.local.json` local. It contains machine-specific paths and
is intentionally ignored by git. Runtime diagnostics, saves, pytest caches, and
Python bytecode are also generated artifacts and should stay out of source
control.
