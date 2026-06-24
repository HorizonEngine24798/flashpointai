# Crisis Room Simulation

A text-first political-military crisis room simulator. The default scenario is
the Cuban Missile Crisis, with the player inhabiting U.S. EXCOMM.

## Start The Game

From this repo, run:

```powershell
C:\Users\User\Miniconda3\Scripts\conda.exe run -n polmil python main.py
```

If `conda` is already on your PATH, this is the same thing:

```powershell
conda run -n polmil python main.py
```

That default launch:

- loads `config/llama_cpp.local.json`
- starts `llama-server.exe` if the configured server is not already running
- loads the local HauhauCS Qwen3.5 35B uncensored GGUF model
- uses `http://127.0.0.1:8080/v1` for game LLM calls
- saves the session and closes the managed server when you type `QUIT`

First startup can take a while because the model has to load. The game prints
the llama-server log path after startup; logs are written under
`output/diagnostics/llama_server/`.

## Game Commands

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

For offline development without the live model, run:

```powershell
conda run -n polmil python main.py --llm scripted
```

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
