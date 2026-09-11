# JARVIS — Local AI Assistant

## Brief

JARVIS is a local-first personal AI assistant designed to run primarily on a personal Windows PC without requiring paid AI APIs.

The core architecture uses **Ollama** as the local LLM runtime, with **Qwen3 8B** as the initial general-purpose brain. Python acts as the main agent/controller and connects the LLM to voice, memory, computer-control, web, coding, document, and IoT tools.

### Target Hardware

- Intel Core i5
- 16 GB RAM
- NVIDIA GTX 1660 Super 6 GB VRAM

The system should prioritize practical capability, low cost, modularity, privacy, and offline functionality where possible.

## Core Stack

| Layer | Technology | Purpose |
|---|---|---|
| LLM Runtime | Ollama | Run local language models |
| Main LLM | Qwen3 8B | General reasoning and conversation |
| Coding LLM | Qwen Coder model | Programming assistance |
| Language | Python | JARVIS core and orchestration |
| Speech-to-Text | faster-whisper | Voice input |
| Text-to-Speech | Piper | Voice output |
| Wake Word | openWakeWord | "Hey Jarvis" detection |
| Memory | SQLite | Conversations, preferences, tasks |
| RAG | ChromaDB + local embeddings | Local document knowledge |
| Backend | FastAPI | Local API and dashboard backend |
| Frontend | HTML/CSS/JavaScript | JARVIS dashboard |
| PC Control | subprocess, pathlib, PyAutoGUI | Windows automation |
| Web Access | HTTPX + search/API tools | Current information and external services |
| IoT | MQTT | ESP32/Raspberry Pi integration |
| Version Control | Git/GitHub | Source-code management |

## Architecture

```text
                         USER
                          │
                          ▼
                  ┌───────────────┐
                  │   Wake Word   │
                  │ openWakeWord  │
                  └───────┬───────┘
                          │
                          ▼
                  ┌───────────────┐
                  │    Whisper    │
                  │ Speech → Text │
                  └───────┬───────┘
                          │
                          ▼
                ┌─────────────────────┐
                │    JARVIS CORE      │
                │       Python        │
                └──────────┬──────────┘
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
         ┌───────┐     ┌────────┐    ┌────────┐
         │Ollama │     │ Memory │    │ Tools  │
         │Qwen3  │     │ SQLite │    │        │
         └───┬───┘     └────────┘    └───┬────┘
             │                           │
             │                ┌──────────┼──────────┐
             │                ▼          ▼          ▼
             │             Windows     Files       Web
             │             Apps        Code       APIs
             │
             ▼
          Response
             │
             ▼
         Piper TTS
             │
             ▼
          SPEAKER
```

# Development Phases

## Phase 1 — JARVIS v0.1: Local Brain

### Goal
Create the first working local AI assistant.

### Build
- Install Python
- Install Ollama
- Download Qwen3 8B
- Create Python-to-Ollama connection
- Create basic system prompt
- Implement terminal chat

### Expected result

```text
You: Hello Jarvis.

JARVIS: Good evening. How can I assist you?
```

### Success criteria
- Ollama runs locally
- Qwen3 responds reliably
- Python can send/receive messages
- No paid API is required

---

## Phase 2 — JARVIS v0.2: Personality and Agent Core

### Goal
Separate JARVIS logic from the user interface and model.

### Build
- Agent class
- LLM client
- System prompt
- Conversation context
- Response handling
- Configuration system

### Structure

```text
jarvis/
├── main.py
├── config.py
└── brain/
    ├── agent.py
    ├── llm.py
    └── prompts.py
```

### Success criteria
- JARVIS has a consistent personality
- LLM code is separated from application logic
- Model can be changed through configuration

---

## Phase 3 — JARVIS v0.3: Tool System

### Goal
Allow JARVIS to perform actions instead of only answering questions.

### Initial tools

```text
get_time()
get_system_info()
open_application()
open_folder()
list_files()
read_file()
```

### Architecture

```text
User
 ↓
JARVIS
 ↓
Qwen3
 ↓
Tool selection
 ↓
Python tool
 ↓
Tool result
 ↓
Qwen3
 ↓
Response
```

### Success criteria
Example:

```text
User: Jarvis, open VS Code.

JARVIS → open_application("vscode")

Windows → VS Code opens

JARVIS: VS Code is open.
```

---

## Phase 4 — JARVIS v0.4: Computer Control

### Goal
Give JARVIS controlled access to the Windows PC.

### Capabilities
- Launch applications
- Close applications
- Open folders
- Search files
- Read files
- Check CPU/RAM/GPU
- Start development projects
- Stop development projects
- Run approved project commands

### Important rule

Do not allow:

```text
LLM → arbitrary shell command → execute
```

Use:

```text
LLM
 ↓
Approved tool
 ↓
Permission check
 ↓
Execute
```

---

## Phase 5 — JARVIS v0.5: Memory

### Goal
Give JARVIS persistent local memory.

### Database

```text
SQLite
```

### Tables

```text
conversations
memories
preferences
tasks
tool_history
```

### Memory types

**Short-term**
- Current conversation
- Current task
- Recent tool results

**Long-term**
- User preferences
- Important project information
- Reusable facts
- Saved tasks

### Success criteria

```text
User:
My preferred editor is VS Code.

JARVIS:
I'll remember that.

Later:

User:
Open my editor.

JARVIS:
Opening VS Code.
```

---

## Phase 6 — JARVIS v0.6: Voice Input

### Goal
Allow JARVIS to understand spoken commands.

### Stack

```text
Microphone
 ↓
faster-whisper
 ↓
Text
 ↓
JARVIS
```

### First implementation

Use push-to-talk instead of a wake word.

Example:

```text
[Hold SPACE]

"Open VS Code"

[Release]
```

### Success criteria
- Speech is transcribed locally
- Text is passed to JARVIS
- Existing tools work with voice commands

---

## Phase 7 — JARVIS v0.7: Voice Output

### Goal
Make JARVIS speak.

### Stack

```text
JARVIS
 ↓
Ollama
 ↓
Text response
 ↓
Piper TTS
 ↓
Speaker
```

### Expected result

```text
You:
Open VS Code.

JARVIS:
VS Code is open.
```

---

## Phase 8 — JARVIS v0.8: Wake Word

### Goal
Remove the need for push-to-talk.

### Stack

```text
Microphone
 ↓
openWakeWord
 ↓
"Hey Jarvis"
 ↓
Whisper
 ↓
JARVIS
```

### Expected interaction

```text
You:
Hey Jarvis, open Chrome.

JARVIS:
Chrome is open.
```

---

## Phase 9 — JARVIS v0.9: Web Intelligence

### Goal
Allow JARVIS to obtain current information.

### Capabilities
- Web search
- Current news
- Documentation lookup
- Weather
- API requests
- Current software information

### Decision flow

```text
User request
     ↓
Qwen3
     ↓
Current information required?
     │
 ┌───┴────┐
NO       YES
 │         │
 ▼         ▼
Local     Web tool
answer       │
             ▼
          Results
             │
             ▼
            Qwen3
             │
             ▼
           Answer
```

JARVIS should remain useful when the internet is unavailable.

---

## Phase 10 — JARVIS v1.0: Full Voice Agent

### Goal
Combine the core capabilities into one usable assistant.

### Features

- Wake word
- Voice input
- Local LLM
- Tool calling
- Computer control
- Memory
- Voice output
- Web access
- Permission system

### Target interaction

```text
You:
Hey Jarvis, check my Sentrix project.

JARVIS:
I'll check it.

→ Searches project
→ Checks files
→ Runs approved diagnostics
→ Analyzes results

JARVIS:
The project is running, but the service log
shows an error in the configuration.
```

---

## Phase 11 — JARVIS v1.1: Coding Assistant

### Goal
Make JARVIS useful for software development.

### Tools

```text
search_code()
read_source_file()
analyze_project()
create_file()
edit_file()
run_tests()
run_project()
git_status()
git_diff()
```

### Example

```text
User:
Jarvis, check why my project isn't starting.

JARVIS:
1. Checks project status
2. Reads logs
3. Inspects configuration
4. Identifies likely problem
5. Explains the problem
6. Requests permission before changing files
```

### Coding model

Use a separate Qwen Coder model when programming tasks require it.

```text
General task → Qwen3
Coding task  → Qwen Coder
```

---

## Phase 12 — JARVIS v1.2: Local Knowledge / RAG

### Goal
Allow JARVIS to understand your own documents.

### Pipeline

```text
PDF / DOCX / TXT
       ↓
Text extraction
       ↓
Chunking
       ↓
Local embeddings
       ↓
ChromaDB
       ↓
Relevant context
       ↓
Qwen3
       ↓
Answer
```

### Knowledge areas

```text
knowledge/
├── projects/
├── research/
├── programming/
├── documentation/
└── other/
```

### Example

```text
User:
Jarvis, what does my Sentrix documentation
say about the attendance workflow?

JARVIS:
Searches the local knowledge base
and answers from the relevant documents.
```

---

## Phase 13 — JARVIS v1.3: Dashboard

### Goal
Create a local JARVIS interface.

### Stack

```text
FastAPI
+
HTML
+
CSS
+
JavaScript
```

### Dashboard

```text
┌──────────────────────────────────────┐
│              J.A.R.V.I.S             │
├──────────────────────────────────────┤
│                                      │
│          ● SYSTEM ONLINE             │
│                                      │
│  CPU       32%                       │
│  RAM       9.2 / 16 GB               │
│  GPU       4.1 GB                    │
│  Ollama    ONLINE                    │
│  Voice     READY                     │
│                                      │
├──────────────────────────────────────┤
│                                      │
│  You: __________________________      │
│                                      │
└──────────────────────────────────────┘
```

---

## Phase 14 — JARVIS v1.4: Tasks and Automation

### Goal
Allow JARVIS to perform scheduled tasks.

### Examples

```text
"Remind me tomorrow to check the deployment."

"Every Monday at 8 AM, check my projects."

"Monitor this service and tell me if it stops."
```

### Components

```text
SQLite
+
Python scheduler
+
Tool system
```

---

## Phase 15 — JARVIS v1.5: IoT

### Goal
Connect JARVIS to ESP32 and Raspberry Pi devices.

### Stack

```text
JARVIS
 ↓
Python
 ↓
MQTT
 ↓
ESP32 / Raspberry Pi
 ↓
Sensors / Devices
```

### Examples

```text
"Jarvis, what's the temperature?"

"Turn on the lab fan."

"Check the Raspberry Pi."

"Is the sensor online?"
```

---

## Phase 16 — JARVIS v2.0: Vision and Advanced Computer Control

### Goal
Give JARVIS visual understanding.

### Future capabilities

- Read screenshots
- Understand application interfaces
- Analyze images
- Read diagrams
- Inspect hardware
- Assist with GUI workflows
- Understand camera input

### Architecture

```text
Screen / Camera
      ↓
Vision model
      ↓
JARVIS
      ↓
Reasoning
      ↓
Tool
      ↓
Computer
```

Vision should be added only after the core agent is stable.

# Recommended Project Structure

```text
JARVIS/
│
├── main.py
├── config.py
├── requirements.txt
├── .env
│
├── brain/
│   ├── __init__.py
│   ├── agent.py
│   ├── llm.py
│   ├── router.py
│   └── prompts.py
│
├── voice/
│   ├── __init__.py
│   ├── stt.py
│   ├── tts.py
│   ├── wakeword.py
│   └── audio.py
│
├── tools/
│   ├── __init__.py
│   ├── apps.py
│   ├── system.py
│   ├── files.py
│   ├── browser.py
│   ├── web.py
│   ├── coding.py
│   └── iot.py
│
├── memory/
│   ├── __init__.py
│   ├── database.py
│   ├── memory.py
│   └── embeddings.py
│
├── rag/
│   ├── loader.py
│   ├── chunker.py
│   ├── retriever.py
│   └── vectorstore.py
│
├── api/
│   ├── server.py
│   └── routes.py
│
├── scheduler/
│   └── tasks.py
│
├── ui/
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── data/
│   ├── jarvis.db
│   ├── chroma/
│   └── logs/
│
├── knowledge/
│
└── tests/
    ├── test_agent.py
    ├── test_tools.py
    └── test_memory.py
```

# Security Rules

JARVIS should use a permission system.

### Level 1 — Safe

```text
get_time()
get_system_info()
open_application()
open_folder()
read_file()
search_files()
```

### Level 2 — Confirmation required

```text
edit_file()
install_package()
stop_service()
restart_service()
modify_configuration()
```

### Level 3 — Dangerous

```text
delete_file()
delete_directory()
execute_arbitrary_command()
modify_security_settings()
```

Never allow unrestricted:

```text
LLM → Shell → Execute
```

Instead:

```text
LLM
 ↓
Approved tool
 ↓
Permission check
 ↓
Execution
 ↓
Result
 ↓
LLM
```

# Development Priority

Build in this order:

```text
1. Ollama + Qwen3
        ↓
2. Python JARVIS core
        ↓
3. Tool calling
        ↓
4. Windows control
        ↓
5. SQLite memory
        ↓
6. Whisper
        ↓
7. Piper
        ↓
8. Wake word
        ↓
9. Web tools
        ↓
10. Coding tools
        ↓
11. RAG
        ↓
12. Dashboard
        ↓
13. Automation
        ↓
14. IoT
        ↓
15. Vision
```

# First Milestone

The first practical target is **JARVIS v0.1**:

```text
Windows PC
    │
    ├── Python
    │
    └── Ollama
          │
          └── Qwen3 8B
                │
                ▼
           JARVIS Core
                │
                ▼
             Response
```

Then immediately move toward:

```text
"Jarvis, open VS Code."

        ↓

      Qwen3

        ↓

open_application("vscode")

        ↓

     Windows

        ↓

   VS Code opens

        ↓

"VS Code is open."
```

The final objective is not simply a local chatbot. It is a **local AI agent that can understand, remember, reason, use tools, control your computer, work with your projects, access information when needed, and interact with IoT devices — while keeping sensitive processing local whenever practical.**
