# JARVIS v1.4: Knowledge, Dashboard, and Automation

local memory, web intelligence, push-to-talk input, Piper speech output, and
wake-word detection. Phase 10 combines these capabilities into one voice-agent
loop while keeping model inference local.

## Full voice agent

The `/agent` command starts continuous wake-word mode. JARVIS listens for
`Hey Jarvis`, transcribes the next command with Whisper, routes it through the
same Agent, approved tools, memory, web access, and permission checks as text
chat, then optionally speaks the response through Piper. Say `stop listening`
or press Ctrl+C to return to text mode.

JARVIS now starts in voice-only mode by default. To start directly in
voice-agent mode, set:

```env
JARVIS_VOICE_AGENT_ENABLED=true
```

Voice-only mode activates the microphone at startup. Say `Hey Jarvis`, speak
your command, and JARVIS responds through Piper. Say `stop listening` or press
Ctrl+C to exit. Approval prompts also use push-to-talk voice confirmation.
Set `JARVIS_VOICE_AGENT_ENABLED=false` only if you want the old text terminal.

Phase 11 adds bounded coding assistance for the approved JARVIS and Sentrix
projects. Sentrix's approved test command is registered in `.jarvis-projects.json`;
file inspection still requires its directory to be listed in `JARVIS_ALLOWED_ROOTS`.
Set `JARVIS_CODING_MODEL` to an installed Ollama coding model, such as a Qwen
Coder model, to route coding-oriented requests to that model. When unset,
JARVIS uses the general model for all requests.

## Local knowledge

Phase 12 provides private document retrieval through `index_knowledge` and
`search_knowledge`. Index approved Markdown, text, source, JSON, YAML, HTML,
CSS, PDF, or DOCX folders into `data/knowledge.db`; document contents stay
local. The `rag` extra enables ChromaDB and local Sentence-Transformers
semantic retrieval, with SQLite lexical retrieval as the fallback.

```text
Index D:\Projects\sentrixv1 for local knowledge.
Search my local knowledge for the attendance workflow.
```

Retrieval is bounded and local; no cloud embeddings or external document service
is required.

## Dashboard

Install the optional dashboard dependencies:

```powershell
pip install -e ".[dashboard]"
python -m jarvis.api.server
```

Open `http://127.0.0.1:8765`. The dashboard exposes local health/status,
memory, tasks, and chat endpoints and does not bind beyond localhost.

## Scheduled tasks

Phase 14 runs a lightweight scheduler during the terminal session. Schedule a
reminder with an ISO-8601 time:

```text
Schedule a task to check the deployment at 2026-09-11T18:00:00+08:00.
```

Due reminders are marked complete in SQLite and printed by JARVIS. The current
scheduler supports one-time, daily, and weekly reminders during the session.
Persistent OS startup and service monitoring remain future improvements.

## Web intelligence

Run `python main.py` and try:

```text
What is the weather in Taipei?
Find recent technology news and cite the sources.
Look up the official Python documentation.
Read https://docs.python.org/3/ and tell me which version it documents.
Read https://api.github.com/repos/python/cpython/releases/latest.
```

The tools are `web_search` (Bing RSS), `news_search` (Google News RSS),
`read_web` (public HTTPS HTML, text, or JSON), and `get_weather`
([Open-Meteo](https://open-meteo.com/en/docs), with its
[geocoding API](https://open-meteo.com/en/docs/geocoding-api)). Weather results
include the resolved location, provider units, current conditions, and a
three-day forecast. Check the resolved city when a place name is ambiguous.

Web access is enabled by default and occurs only when a tool is called. Set
`JARVIS_WEB_ENABLED=false` in `.env` to disable it. Local chat, files, memory,
and other local tools continue working when web access is disabled or fails.
No additional Python dependency or API key is required for these web tools.
Open-Meteo's public service is intended for non-commercial use; review its
provider terms before deploying this personal assistant commercially.

Results carry source URLs and UTC retrieval timestamps. The agent is instructed
to cite sources, verify changing facts, and report when current information
cannot be checked. Feed dates come from the provider and are not independently
verified article publication dates. Search feeds may change, rate-limit requests,
or return incomplete results; failures are reported instead of invented answers.

Web requests use GET only, with no cookies, authentication headers, uploads, or
JavaScript execution. Only HTTPS port 443 is supported. Private/local addresses
are blocked, including after redirects, and TLS connections use validated public
IP addresses while verifying the original hostname. Downloads are limited to
512 KiB; extracted text to 16,000 characters; searches to five results. There
are at most three redirects and a 12-second request budget after DNS resolution
begins (DNS itself follows the operating system's timeout). PDFs, authenticated
APIs, and pages requiring JavaScript are not supported.

Queries, city names, URLs, and your public IP reach the relevant provider. The
agent is instructed not to send private file contents, memories, or credentials
without explicit authorization; this instruction is not an automatic secret
detector. Keep sensitive information out of web requests.

## Prerequisites

- Windows with Python 3.10 or newer
- [Ollama](https://ollama.com/download/windows)
- The Qwen3 8B model, or another Ollama chat model
- A microphone for voice input

Install and prepare Ollama:

```powershell
ollama pull qwen3:8b
ollama serve
```

Ollama may already run as a Windows background service. If port `11434` is
available, the application connects to `http://127.0.0.1:11434` by default.

## Run

Create and activate a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[voice]"
# Optional speech output support:
pip install -e ".[voice-output]"
# Optional wake-word support:
pip install -e ".[wake-word]"
# PDF/DOCX and semantic local retrieval:
pip install -e ".[rag]"
```

Start JARVIS:

```powershell
python main.py
```

Use `/reset` to clear the conversation, `/exit` to quit, or `/voice` to start
push-to-talk input. Hold Space while speaking and release it when finished.
Ctrl+C also ends the session while the model is generating.

Type `/wake` to listen continuously for the configured wake word. The default
is `Hey Jarvis`; after detection, JARVIS records up to six seconds of speech,
transcribes it locally, and sends it through the normal agent and tool system.
Press Ctrl+C to leave wake-word mode.

`/wake` and `/agent` are aliases for the full voice-agent mode. `/agent` is the
recommended name for the Phase 10 workflow.

The default Whisper model is `base.en` and runs on CPU with `int8` inference,
which avoids requiring CUDA DLLs on Windows. The first voice request downloads
the model locally through faster-whisper. Set `JARVIS_WHISPER_MODEL` to another
Whisper model, `JARVIS_AUDIO_SAMPLE_RATE` to change the audio settings, or
`JARVIS_WHISPER_DEVICE=auto` when CUDA is fully installed.

## Speech output

Download a Piper `.onnx` voice model from [Hugging Face Piper Voices](https://huggingface.co/rhasspy/piper-voices) and place it at the configured path.

**Female voices (JARVIS Girl Mode):**
- `en_US-amy-medium.onnx` — Friendly, natural female voice (recommended)
- `en_US-libritts-high.onnx` — Clear, expressive female voice (high quality, ~1GB)
- `en_GB-semaine-medium.onnx` — British female voice

**Male voices:**
- `en_US-lessac-medium.onnx` — Natural male voice (default)
- `en_US-joe-medium.onnx` — Deep male voice

Example setup with female voice:

```env
JARVIS_TTS_ENABLED=true
JARVIS_PIPER_MODEL=models/piper/en_US-amy-medium.onnx
```

**Quick setup:** See [VOICE_SETUP.md](VOICE_SETUP.md) for detailed instructions and a download script.

The model path may be absolute or relative to the project root. Piper output is
disabled by default. JARVIS prints responses and continues normally if the
configured model or playback dependency is unavailable.

## External project access

File and project tools are restricted to the JARVIS folder unless additional
folders are explicitly approved. Set `JARVIS_ALLOWED_ROOTS` to a semicolon-
separated list of existing absolute directories:

```env
JARVIS_ALLOWED_ROOTS=D:\Projects\sentrixv1;D:\Projects\another-project
```

The JARVIS folder is always included. Use `list_allowed_roots` to see the
active boundary, then provide absolute paths when asking JARVIS to inspect an
external project. Hidden paths, credential files, symlink escapes, and
arbitrary shell commands remain blocked.

## Coding assistant

Phase 11 adds bounded coding tools for approved roots and configured projects:
`search_code`, `read_source_file`, `analyze_project`, `git_status`,
`git_diff`, `create_file`, `edit_file`, `run_tests`, and `run_project`.
Source reads and Git inspection are read-only. File changes, tests, and project
execution require the normal explicit confirmation prompt. Project execution
uses only command aliases from `.jarvis-projects.json`; model-generated shell
commands are never executed directly.

## Wake word

Install the optional dependency with `pip install -e ".[wake-word]"`. The
first use may download openWakeWord's model files. Configure the behavior with:

```env
JARVIS_WAKEWORD_MODEL=hey_jarvis
JARVIS_WAKEWORD_THRESHOLD=0.5
JARVIS_WAKEWORD_COMMAND_SECONDS=6
```

Raise the threshold if false detections occur; lower it if the wake word is
missed. Wake-word mode is opt-in through `/wake` and is not active at startup.

## Tools and memory

Try these requests:

```text
What time is it?
Check my operating system and CPU count.
List the files in the project root.
Read README.md.
Open the project folder.
Open VS Code.
```

Available tools include `get_time`, `get_system_info`, `list_files`, `read_file`,
`open_folder`, `open_application`, `remember_memory`, `set_preference`,
`get_preference`, `list_memory`, `add_task`, `schedule_task`, `index_knowledge`,
and `search_knowledge`. The model selects structured calls,
the registry validates and executes them, and the model receives their results
to compose its reply. This follows [Ollama's tool-calling interface](https://docs.ollama.com/capabilities/tool-calling).

File and folder access is restricted to the JARVIS directory plus configured
`JARVIS_ALLOWED_ROOTS`, including when paths contain `..` or symbolic links.
Hidden paths, `node_modules`, `__pycache__`,
and common private-key file extensions are blocked. File reads accept UTF-8 text
up to 32 KiB; directory listings return up to 200 entries. These filters do not
detect secrets embedded in otherwise readable files.

Application launches support only `vscode`, `notepad`, and `calculator` on Windows.
VS Code must be installed in its standard per-user or Program Files directory.
Launches use fixed executable paths with no model-supplied command arguments or
shell. A successful result confirms that a launch was requested, not that the
application is ready.

These six tools are classified as safe under the project's permission model.
The registry denies unknown tools and requires an explicit confirmation callback
for any future tool marked `confirm` or `dangerous`; without one it denies execution.
Each turn allows at most four tool rounds with eight calls per round. Tool results
already executed remain in conversation history if the final model reply fails.
Resetting history does not undo actions.

## Configuration

Copy `.env.example` to `.env` in the project root, or set the variables in
PowerShell. Environment variables override `.env` values; missing settings use
the defaults. The `.env` file supports `KEY=value`, optional matching quotes,
blank lines, and full-line `#` comments. Values are literal, without variable
expansion or inline comments. The timeout must be a finite positive number:

```powershell
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
$env:JARVIS_MODEL = "qwen3:8b"
$env:JARVIS_TIMEOUT_SECONDS = "120"
```

## Test

The client tests use a fake response and do not require Ollama to be running:

```powershell
python -m unittest discover -s tests -v
```

The database is stored at `data/jarvis.db` and contains conversations,
conversation messages, memories, preferences, tasks, and tool history. It is
created automatically when JARVIS starts and is excluded from version control.
Memory remains local to this computer.

Try these requests:

```text
Remember that my preferred editor is VS Code.
What is my preferred editor?
Add a task to check the deployment.
What do you remember?
```

## Architecture boundary

The `Agent` class owns system prompts, conversation context, reset behavior, and
response handling, and memory persistence. The Ollama client and memory store
are injected into the agent, so the brain can be tested without a live model.

File editing and arbitrary command execution remain outside this
milestone. Camera vision and broader continuous automation remain future
phases.
