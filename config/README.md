# Config

The game uses this file automatically when it exists:

```text
config/llama_cpp.local.json
```

This workspace's local file points at the HauhauCS Qwen3.5 35B uncensored GGUF
model and a local `llama-server.exe`. It starts the server through the app and
sets `server_auto_stop` so the managed server closes when the game exits.

For another machine, copy the example and edit the two private paths:

```powershell
Copy-Item config/llama_cpp.example.json config/llama_cpp.local.json
```

```text
server_executable    absolute path to llama-server.exe
server_model_path    absolute path to the GGUF model file
```

Files matching `config/*.local.json` are ignored by git.
