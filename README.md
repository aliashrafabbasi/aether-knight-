# Aether Knight

**Aether Knight** is a production-ready **real-time voice AI assistant** backend. Users talk naturally in the browser — the system listens, transcribes speech, generates an intelligent reply, speaks it back, and saves the full conversation for later. Think of it as a self-hosted, API-first voice companion with ChatGPT-style persistent chat sessions.

This repository is the **main development backend**. The deployed Hugging Face version lives in a separate repo: [aliashrafabbasi/Aether-knight](https://huggingface.co/spaces/aliashrafabbasi/Aether-knight) → https://aliashrafabbasi-aether-knight.hf.space

---

## Table of contents

1. [Introduction](#introduction)
2. [What the system does](#what-the-system-does)
3. [Key features explained](#key-features-explained)
4. [Architecture](#architecture)
5. [How a voice conversation works](#how-a-voice-conversation-works)
6. [Tech stack](#tech-stack)
7. [Project structure — every folder and file](#project-structure--every-folder-and-file)
8. [Database design](#database-design)
9. [Authentication and authorization](#authentication-and-authorization)
10. [API reference (complete)](#api-reference-complete)
11. [WebSocket protocol (voice live)](#websocket-protocol-voice-live)
12. [Browser voice client](#browser-voice-client)
13. [Agent personality — YAML configuration](#agent-personality--yaml-configuration)
14. [Environment variables](#environment-variables)
15. [Local development setup](#local-development-setup)
16. [Docker](#docker)
17. [React frontend integration](#react-frontend-integration)
18. [Hugging Face deployment](#hugging-face-deployment)
19. [Troubleshooting](#troubleshooting)
20. [Design decisions](#design-decisions)

---

## Introduction

Aether Knight solves one problem: **natural spoken conversation with an AI that remembers context**. Unlike text-only chatbots, it handles the full audio loop:

- Captures microphone input in the browser
- Converts speech to text (STT)
- Reasons over conversation history (LLM)
- Speaks the answer aloud (TTS)
- Persists every message in a database

The backend is built with **FastAPI** and exposes:

- **REST APIs** for auth, admin, and session management
- **WebSockets** for low-latency duplex voice
- **Built-in HTML demo pages** at `/voice/demo` and `/voice/join/{id}` (no separate frontend required to test)
- **Optional React + TypeScript UI** in a sibling repo (`aether-knight-frontend`)

---

## What the system does

| Step | Component | What happens |
|------|-----------|--------------|
| 1 | Browser | User speaks into the microphone |
| 2 | `voice_client.js` | Detects speech, records WebM audio, sends over WebSocket |
| 3 | `audio.py` | Converts WebM/OGG → WAV for STT compatibility |
| 4 | `stt.py` | Groq Whisper transcribes audio to text |
| 5 | `voice_agent.py` | Checks intents (goodbye, hello, repeat) or calls LLM |
| 6 | `llm.py` | Groq LLM generates a short, voice-friendly reply |
| 7 | `tts.py` | Edge TTS converts reply to MP3 (base64) |
| 8 | `chat_sessions.py` | Saves user + assistant messages to SQLite |
| 9 | Browser | Plays TTS audio; user can interrupt and speak again |

After the first real exchange, the system **auto-generates a chat title** (like ChatGPT) using the LLM.

---

## Key features explained

### Duplex voice (always listening)

The microphone stays open for the entire session. You do not press a button for each sentence — the client uses **voice activity detection (VAD)** to know when you start and stop speaking.

### Barge-in (interrupt the AI)

While the AI is **speaking** or **thinking**, you can talk over it. The client:
1. Detects sustained loud speech (~500 ms)
2. Stops TTS playback immediately
3. Sends `{ "type": "cancel" }` to abort in-flight LLM processing
4. Starts recording your new utterance

### Saved chat sessions

Every conversation is tied to a `session_id` (UUID). You can:
- List all past chats
- Resume any chat with full history
- Delete chats you no longer need

### Auto titles

New chats start as `"New conversation"`. After the first meaningful user + assistant exchange, `llm.generate_chat_title()` creates a short title (e.g. *"Python homework help"*) and pushes a `title_updated` WebSocket event to the UI.

### Voice-triggered end

Say phrases like *"end the conversation"*, *"goodbye"*, or *"stop the chat"* — the agent replies with a farewell and closes the session. You can also click **Stop Chat** or call `POST /voice/stop`.

### JWT auth with logout

All protected routes require `Authorization: Bearer <token>`. Logout **revokes** the token server-side (stored in `revoked_tokens` by JWT `jti`), so stolen tokens cannot be reused after logout.

### Admin user management

Users with `role: "admin"` can list, update, and delete other users via `/admin/*` endpoints. Regular users only access their own voice sessions.

### YAML-driven personality

Agent tone, greeting, STT vocabulary, quick intents, and safety rules live in `config/prompts/aether_knight.yaml` — change behavior without redeploying Python logic.

---

## Architecture

### High-level system diagram

```mermaid
flowchart TB
    subgraph clients [Clients]
        Demo["Built-in /voice/demo"]
        Join["Built-in /voice/join"]
        React["React TypeScript UI"]
        Swagger["Swagger /docs"]
        Curl["curl / Postman"]
    end

    subgraph server [FastAPI Backend — Uvicorn]
        Main["app/main.py"]
        AuthR["auth routes"]
        AdminR["admin routes"]
        VoiceR["voice routes + WebSocket"]
        VC["voice_client.js served at /voice/client.js"]
    end

    subgraph services [Service Layer]
        VA["voice_agent.py"]
        CS["chat_sessions.py"]
        CI["conversation_intents.py"]
        PR["prompts.py → YAML"]
    end

    subgraph ai [AI Integrations]
        STT["stt.py → Groq Whisper"]
        LLM["llm.py → Groq LLM"]
        TTS["tts.py → Edge TTS"]
        AU["audio.py → PyAV"]
    end

    subgraph data [Persistence]
        DB[("SQLite test.db")]
        TMP["temp/ audio files"]
    end

    Demo --> AuthR
    Demo --> VoiceR
    Join --> VoiceR
    Join --> VC
    React --> AuthR
    React --> VoiceR
    Swagger --> Main

    VoiceR --> VA
    VoiceR --> CS
    VA --> STT
    VA --> LLM
    VA --> TTS
    VA --> CI
    VA --> PR
    STT --> AU
    CS --> DB
    STT --> TMP
```

### Layered backend design

```mermaid
flowchart LR
    subgraph L1 [Presentation]
        R1["auth.py"]
        R2["admin.py"]
        R3["voice.py"]
    end

    subgraph L2 [Application]
        S1["voice_agent"]
        S2["chat_sessions"]
        S3["conversation_intents"]
    end

    subgraph L3 [Integration]
        I1["stt"]
        I2["llm"]
        I3["tts"]
        I4["audio utils"]
    end

    subgraph L4 [Data]
        M["models.py"]
        D["database.py"]
    end

    subgraph X [Cross-cutting]
        SEC["security.py — JWT, bcrypt"]
        DEP["dependencies.py"]
        CFG["config.py + .env"]
    end

    R1 --> SEC
    R2 --> SEC
    R3 --> S1
    R3 --> S2
    S1 --> I1 & I2 & I3
    S2 --> M
    M --> D
```

| Layer | Responsibility | Key modules |
|-------|----------------|-------------|
| **Presentation** | HTTP routes, WebSocket handler, inline HTML pages | `app/api/routes/` |
| **Application** | Business logic: voice turns, sessions, intents | `voice_agent`, `chat_sessions`, `conversation_intents` |
| **Integration** | External APIs and audio processing | `stt`, `llm`, `tts`, `audio` |
| **Data** | ORM models, SQLite connection | `models.py`, `database.py` |
| **Cross-cutting** | Auth, config, prompts | `security`, `dependencies`, `config`, `prompts` |

### Data model (ER diagram)

```mermaid
erDiagram
    User ||--o{ ChatSession : "owns"
    ChatSession ||--o{ ChatMessage : "contains"

    User {
        uuid id PK
        string name
        string email UK
        string hashed_password
        string role "admin | user"
    }

    ChatSession {
        uuid id PK
        uuid user_id FK
        string title
        string language
        datetime created_at
        datetime updated_at
    }

    ChatMessage {
        int id PK
        uuid session_id FK
        string role "user | assistant"
        text content
        datetime created_at
    }

    RevokedToken {
        int id PK
        string jti UK
        datetime revoked_at
    }
```

### Authentication flow

```mermaid
sequenceDiagram
    participant C as Client
    participant A as /auth
    participant S as security.py
    participant DB as SQLite

    Note over C,DB: Registration
    C->>A: POST /register { name, email, password, role? }
    A->>DB: insert User (role defaults to "user")
    A-->>C: { success, data: UserOut }

    Note over C,DB: Login
    C->>A: POST /login { email, password }
    A->>S: verify_password + create_access_token
    A-->>C: { token, user }

    Note over C,DB: Protected request
    C->>A: GET /voice/sessions + Bearer token
    A->>S: decode JWT, check revoked_tokens
    A->>DB: load user by email (sub claim)
    A-->>C: session list

    Note over C,DB: Logout
    C->>A: POST /logout + Bearer token
    A->>DB: insert jti into revoked_tokens
    A-->>C: token invalidated
```

---

## How a voice conversation works

### End-to-end sequence (one utterance)

```mermaid
sequenceDiagram
    participant U as User
    participant B as voice_client.js
    participant WS as WebSocket /voice/live
    participant VA as voice_agent
    participant STT as Groq Whisper
    participant LLM as Groq LLM
    participant TTS as Edge TTS
    participant DB as SQLite

    U->>B: speaks sentence
    B->>B: VAD detects silence (~1s)
    B->>WS: {type:start} + webm bytes + {type:stop}
    WS->>VA: process_voice(audio)
    VA->>STT: transcribe_bytes
    STT-->>VA: { text, language }

    alt end conversation phrase
        VA->>VA: farewell_message()
    else quick intent (hello, thanks)
        VA->>VA: match_quick_intent from YAML
    else normal chat
        VA->>LLM: chat with history + system prompt
        LLM-->>VA: reply text
    end

    VA->>DB: append user + assistant messages
    VA->>LLM: generate_chat_title (first exchange only)
    VA->>TTS: text_to_speech_base64
    TTS-->>WS: MP3 base64
    WS-->>B: transcript → reply → speech events
    B->>U: plays audio (can interrupt)
```

### UI states during a session

| State | What the user sees | What is happening |
|-------|-------------------|-------------------|
| `idle` | Connect button | Not connected |
| `calibrating` | "Calibrating mic…" | Measuring background noise (~1.2 s) |
| `listening` | "Speak — pause 1 sec when done" | Waiting for speech |
| `recording` | "Hearing you…" | MediaRecorder capturing utterance |
| `processing` | "Thinking…" | STT + LLM running |
| `speaking` | "Speaking — talk over me to interrupt" | TTS audio playing |
| `paused` | "Chat ended — saved" | Session closed |

### Starting a new chat (step by step)

1. **Login** — `POST /auth/login` → save `token`
2. **Start session** — `POST /voice/start` (Bearer token, no body) → get `session_id` + `join_url`
3. **Open join URL** — browser loads `/voice/join/{session_id}?token=...`
4. **Click "Start Conversation"** — WebSocket connects, agent speaks greeting
5. **Allow microphone** — duplex client starts VAD loop
6. **Talk naturally** — pause ~1 second after each sentence
7. **End** — say goodbye, click Stop, or `POST /voice/stop`

---

## Tech stack

| Layer | Technology | Version / notes | Why |
|-------|------------|-----------------|-----|
| API framework | FastAPI | 0.137+ | Async REST + WebSocket, OpenAPI docs |
| ASGI server | Uvicorn | 0.49+ | Production server with `--reload` for dev |
| Auth | python-jose + bcrypt | JWT Bearer tokens | Stateless auth + secure passwords |
| ORM | SQLAlchemy | 2.0+ | SQLite models and queries |
| Database | SQLite | `test.db` default | Zero-config, file-based |
| STT (default) | Groq Whisper | `whisper-large-v3` | Fast, accurate cloud transcription |
| STT (fallback) | faster-whisper | local CPU | Offline mode via `STT_PROVIDER=local` |
| LLM | Groq | `llama-3.1-8b-instant` | Low-latency replies for voice |
| TTS | edge-tts | Microsoft voices | Free, natural speech, no API key |
| Audio | PyAV (`av`) | WebM → WAV | No ffmpeg binary required |
| Config | PyYAML + python-dotenv | `.env` + YAML prompts | Secrets + personality |
| Validation | Pydantic | v2 | Request/response schemas |

---

## Project structure — every folder and file

```
aether-knight-/
├── app/
│   ├── main.py                      # FastAPI app, CORS, exception handlers, router mount
│   │
│   ├── api/routes/
│   │   ├── auth.py                  # POST /register, /login, /logout; GET /me
│   │   ├── admin.py                 # GET/PUT/DELETE /admin/users (admin only)
│   │   └── voice.py                 # Voice REST, WebSocket /live, demo HTML, join page
│   │
│   ├── assets/
│   │   └── voice_client.js          # Browser duplex mic client (VAD, barge-in, WebSocket)
│   │
│   ├── core/
│   │   ├── config.py                # Loads .env: GROQ_API_KEY, models, STT provider, paths
│   │   ├── dependencies.py          # get_db, get_current_user, get_admin_user, bearer_scheme
│   │   └── security.py              # hash_password, verify_password, create/decode JWT
│   │
│   ├── db/
│   │   ├── database.py              # SQLAlchemy engine, SessionLocal, DATABASE_URL
│   │   └── models.py                # User, ChatSession, ChatMessage, RevokedToken
│   │
│   ├── schemas/
│   │   ├── auth.py                  # UserCreate, UserLogin, UserOut, AuthToken, UserUpdate
│   │   ├── voice.py                 # ChatMessage, VoiceSessionOut, ChatSessionSummary, etc.
│   │   └── response.py              # ApiResponse[T] envelope used by all REST endpoints
│   │
│   ├── services/
│   │   ├── voice_agent.py           # Orchestrates one voice turn: STT → intent/LLM → TTS
│   │   ├── stt.py                   # Groq Whisper + optional local faster-whisper
│   │   ├── llm.py                   # Groq chat completion + generate_chat_title()
│   │   ├── tts.py                   # edge-tts → MP3 base64
│   │   ├── chat_sessions.py         # Create/list/resume/delete sessions; load/save messages
│   │   ├── prompts.py               # Load YAML; build system prompt, greeting, STT hints
│   │   ├── conversation_intents.py  # End-conversation phrase detection + farewell text
│   │   ├── language.py              # Language code helpers
│   │   └── sessions.py              # Legacy session helpers (if used)
│   │
│   └── utils/
│       └── audio.py                 # save_audio_bytes, convert_to_wav (PyAV), cleanup
│
├── config/prompts/
│   └── aether_knight.yaml           # Full agent personality, intents, STT vocabulary
│
├── temp/                            # Runtime temp audio (gitignored)
├── requirements.txt                 # All Python dependencies
├── Dockerfile                       # Local Docker image (port 8000)
├── docker-compose.yml               # Local Docker Compose (+ optional React frontend)
├── .env.example                     # Environment variable template
├── .dockerignore
├── .gitignore
└── README.md                        # This file
```

### Module responsibilities in detail

#### `app/main.py`
- Creates FastAPI application
- Configures CORS for React dev server (`localhost:5173`)
- Registers global exception handlers (returns `{ success: false, message }` JSON)
- Mounts `auth`, `admin`, `voice` routers
- On startup: validates `GROQ_API_KEY` is present

#### `app/api/routes/voice.py`
The largest route file. Handles:
- **REST**: start, resume, list/delete sessions, stop, text chat
- **WebSocket** `/voice/live`: real-time voice pipeline
- **HTML pages**: `/voice/demo` (login hub), `/voice/join/{id}` (voice room)
- **Static JS**: `/voice/client.js` serves `voice_client.js`
- **Auto-title**: calls LLM after first exchange
- **Proxy-aware URLs**: uses `X-Forwarded-Host` / `X-Forwarded-Proto` for correct `join_url` behind HTTPS

#### `app/services/voice_agent.py`
Core orchestrator for one spoken turn:
1. Transcribe audio via `stt.transcribe_bytes`
2. Check `is_end_conversation()` → farewell
3. Check `match_quick_intent()` → instant YAML response
4. Else call `llm.chat()` with history
5. Generate TTS via `text_to_speech_base64`
6. 28-second timeout per turn

#### `app/services/chat_sessions.py`
- `create_chat_session()` — new UUID session for user
- `list_user_sessions()` — all chats with preview + message count
- `load_history()` — last N messages for LLM context
- `append_messages()` — persist user + assistant turns
- `set_session_title()` / `needs_auto_title()` — title management
- `stop_live_session()` — mark session as no longer live

---

## Database design

### Tables

**`users`**
| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `name` | string | Display name |
| `email` | string | Unique login email |
| `hashed_password` | string | bcrypt hash |
| `role` | string | `admin` or `user` (default `user`) |

**`chat_sessions`**
| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Session ID used in URLs |
| `user_id` | FK → users | Owner |
| `title` | string | Auto or default "New conversation" |
| `language` | string | Detected language code (default `en`) |
| `created_at` / `updated_at` | datetime | Timestamps |

**`chat_messages`**
| Column | Type | Description |
|--------|------|-------------|
| `id` | integer | Auto-increment PK |
| `session_id` | FK → chat_sessions | Parent chat |
| `role` | string | `user` or `assistant` |
| `content` | text | Message text |
| `created_at` | datetime | When saved |

**`revoked_tokens`**
| Column | Type | Description |
|--------|------|-------------|
| `jti` | string | JWT ID blacklisted on logout |

### Default database path

- **Local dev:** `./test.db` (project root) unless `DATABASE_URL` is set
- **Docker:** `/data/test.db` (volume `aether-data`)

Tables are created automatically on first request via `models.Base.metadata.create_all()`.

---

## Authentication and authorization

### Registration — `POST /auth/register`

**Request body:**
```json
{
  "name": "Ali Ashraf",
  "email": "you@example.com",
  "password": "yourpassword",
  "role": "user"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `name` | Yes | Display name |
| `email` | Yes | Must be unique |
| `password` | Yes | Stored as bcrypt hash |
| `role` | No | Defaults to `"user"`. Must be `admin` or `user` if provided |

**Response:**
```json
{
  "success": true,
  "message": "Account created",
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Ali Ashraf",
    "email": "you@example.com",
    "role": "user"
  }
}
```

> **Production note:** The Hugging Face deployment repo removes `role` from registration and assigns `admin` to the first user only. This local repo still accepts optional `role` on register.

### Login — `POST /auth/login`

**Request:**
```json
{
  "email": "you@example.com",
  "password": "yourpassword"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Login successful",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "type": "bearer",
    "user": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Ali Ashraf",
      "email": "you@example.com",
      "role": "admin"
    }
  }
}
```

Use on all protected routes:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Current user — `GET /auth/me`

Returns the logged-in user object. Requires Bearer token.

### Logout — `POST /auth/logout`

Revokes the current JWT. The token's `jti` is stored in `revoked_tokens` and rejected on future requests.

### Roles

| Role | Permissions |
|------|-------------|
| `user` | Own voice sessions, register/login/logout, `/auth/me` |
| `admin` | All user permissions + `/admin/users` CRUD |

---

## API reference (complete)

### Response envelope

Every REST endpoint returns:

```json
{
  "success": true,
  "message": "Optional human-readable message",
  "data": { }
}
```

Errors:
```json
{
  "success": false,
  "message": "Error description"
}
```

HTTP status codes: `400` bad request, `401` unauthorized, `403` forbidden, `404` not found, `422` validation error.

---

### Auth endpoints — `/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/register` | No | Create new account |
| `POST` | `/auth/login` | No | Login → JWT token |
| `GET` | `/auth/me` | Bearer | Current user profile |
| `POST` | `/auth/logout` | Bearer | Revoke current token |

---

### Admin endpoints — `/admin` (admin role required)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/users` | List all users `{ total, users[] }` |
| `PUT` | `/admin/users/{user_id}` | Update name, email, password, or role |
| `DELETE` | `/admin/users/{user_id}` | Delete user (cannot delete yourself) |

**Update user example:**
```json
PUT /admin/users/550e8400-e29b-41d4-a716-446655440000
{
  "name": "New Name",
  "email": "new@example.com",
  "role": "admin",
  "password": "newpassword123"
}
```

All fields are optional — only include what you want to change.

---

### Voice endpoints — `/voice`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/voice/start` | Bearer | Create new voice chat (no body needed) |
| `POST` | `/voice/resume` | Bearer | Resume chat `{ "session_id": "..." }` |
| `GET` | `/voice/sessions` | Bearer | List your saved chats |
| `GET` | `/voice/sessions/{id}` | Bearer | Full message history for one chat |
| `DELETE` | `/voice/sessions/{id}` | Bearer | Delete a saved chat |
| `POST` | `/voice/stop?session_id=` | Bearer | End live voice session |
| `POST` | `/voice/chat` | Bearer | Text-only chat (no microphone) |
| `WebSocket` | `/voice/live?session_id=` | Query token/session | Real-time voice pipeline |
| `GET` | `/voice/demo` | No | Built-in browser UI |
| `GET` | `/voice/join/{session_id}` | No | Voice room page |
| `GET` | `/voice/client.js` | No | Browser voice client JavaScript |

#### `POST /voice/start` — response example

```json
{
  "success": true,
  "message": "New chat started — open join_url in your browser, then talk",
  "data": {
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "ws_url": "ws://127.0.0.1:8000/voice/live?session_id=a1b2c3d4-...",
    "join_url": "http://127.0.0.1:8000/voice/join/a1b2c3d4-...?token=eyJ...",
    "title": "New conversation",
    "resumed": false,
    "message_count": 0
  }
}
```

Open `join_url` in the browser to start talking.

#### `GET /voice/sessions` — response example

```json
{
  "success": true,
  "message": "Chat sessions loaded",
  "data": [
    {
      "id": "a1b2c3d4-...",
      "title": "Python homework help",
      "language": "en",
      "message_count": 12,
      "preview": "Can you explain loops in Python?",
      "created_at": "2026-07-07T10:00:00",
      "updated_at": "2026-07-07T10:15:00",
      "join_url": "http://127.0.0.1:8000/voice/join/a1b2c3d4-..."
    }
  ]
}
```

#### `POST /voice/chat` — text-only chat

```json
{
  "message": "What is photosynthesis?",
  "history": [],
  "session_id": "optional-existing-session-id"
}
```

---

## WebSocket protocol (voice live)

### Connect

```
ws://127.0.0.1:8000/voice/live?session_id=<SESSION_ID>
```

Production / HF:
```
wss://aliashrafabbasi-aether-knight.hf.space/voice/live?session_id=<SESSION_ID>
```

### Client → server messages

| Message | Format | When |
|---------|--------|------|
| Start recording | `{ "type": "start", "format": "webm" }` | Before sending audio bytes |
| Audio data | Raw binary (WebM/OGG) | The recorded utterance |
| Stop recording | `{ "type": "stop" }` | After audio bytes — triggers processing |
| Cancel / barge-in | `{ "type": "cancel" }` | User interrupts AI |
| End session | `{ "type": "end_session" }` | User clicks Stop or says goodbye |

### Server → client messages

| `type` | Payload | Description |
|--------|---------|-------------|
| `ready` | `{ user, session_id, title, resumed }` | Connected; agent about to greet |
| `history` | `{ messages[], title }` | Previous messages when resuming |
| `listening` | — | Ready for user speech |
| `processing` | `{ message }` | STT or LLM running |
| `transcript` | `{ text, language }` | What the user said |
| `reply` | `{ reply, model }` | AI text response |
| `speech` | `{ text, audio_base64, format: "mp3" }` | TTS audio to play |
| `title_updated` | `{ title, session_id }` | Auto-generated chat title |
| `session_ended` | `{ message }` | Conversation closed |
| `error` | `{ message }` | Something failed |

### Typical event order (new chat)

1. `ready` — connection established
2. `speech` — agent greeting (TTS)
3. *(user speaks)*
4. `processing` → `transcript` → `reply` → `speech`
5. `title_updated` — after first exchange
6. *(repeat 3–5)*
7. `session_ended` — on goodbye

---

## Browser voice client

File: `app/assets/voice_client.js` — served at `/voice/client.js`

Class: `NaturalVoiceClient`

### What it does

| Feature | Implementation |
|---------|----------------|
| Microphone | `getUserMedia` — echo cancellation, 48 kHz mono |
| VAD | RMS from `AnalyserNode` — speech vs silence detection |
| Recording | `MediaRecorder` → WebM/Opus per utterance |
| Silence detection | ~1000 ms silence after speech → send utterance |
| Min speech length | 700 ms — ignores accidental clicks |
| Max recording | 22 seconds per utterance |
| Barge-in | 500 ms loud speech while AI busy → cancel + record |
| TTS playback | `Audio` element from `data:audio/mp3;base64,...` |
| Cooldown | 400 ms after server ready before next recording |

### Constructor options

```javascript
new NaturalVoiceClient(ws, {
  onLog: (text, cls) => {},      // transcript log: "user", "ai", "sys"
  onStatus: (state, text) => {}, // UI state updates
  onStop: () => {}               // called when session ends
});
```

### Key methods

| Method | Description |
|--------|-------------|
| `start()` | Open mic, start VAD monitoring loop |
| `stop()` | Release mic, close audio context |
| `playSpeech(b64)` | Play TTS; returns Promise resolved on end |
| `requestEnd()` | Send `end_session` to server |
| `onServerReady()` | Called on `ready` event — resume listening |

---

## Agent personality — YAML configuration

File: `config/prompts/aether_knight.yaml`

Edit this file to change agent behavior **without modifying Python code**.

### Sections explained

| Section | Purpose |
|---------|---------|
| `agent` | Name, title, high-level description |
| `greeting` | First-time welcome — `{user_name}` placeholder |
| `resume` | Welcome back message — `{user_name}`, `{session_title}` |
| `personality` | List of tone/style rules for the LLM system prompt |
| `user_context` | Template injected so LLM knows who it is talking to |
| `accessibility` | Simple language rules for voice (short sentences, no jargon) |
| `response_strategy` | `max_sentences: 2`, `target_words: 30`, voice-first rules |
| `intelligence` | How to handle kids, adults, unclear speech, unsafe requests |
| `rules` | Safety, no markdown/emojis in spoken output |
| `language` | Default English + multilingual reply instructions |
| `llm` | `temperature: 0.4`, `max_tokens: 75` |
| `stt` | Whisper prompt template + vocabulary hints for better transcription |
| `quick_intents` | Instant responses for hello, thanks, repeat, clarify |
| `rephrase` | Instruction when user says "I don't understand" |
| `end_conversation` | Phrases that trigger farewell + session close |

### Quick intents

Predefined patterns bypass the LLM for common phrases:

| Intent | Example phrases | Action |
|--------|----------------|--------|
| `greeting` | hello, hi, how are you | Instant friendly reply |
| `thanks` | thank you, thanks | You're welcome |
| `acknowledgment` | ok, got it, makes sense | Prompt for next question |
| `repeat` | say that again, pardon | Repeats last assistant message |
| `clarify` | I don't understand, simplify | Rephrases last answer simpler |

### Custom prompts file

Set in `.env`:
```
AGENT_PROMPTS_FILE=config/prompts/my_custom_agent.yaml
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in values.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | **Yes** | — | API key from [console.groq.com](https://console.groq.com) |
| `GROQ_MODEL` | No | `llama-3.1-8b-instant` | LLM model for replies |
| `GROQ_WHISPER_MODEL` | No | `whisper-large-v3` | STT model |
| `STT_PROVIDER` | No | `groq` | `groq` (cloud) or `local` (faster-whisper CPU) |
| `WHISPER_MODEL` | No | `base` | Local whisper model size (if `STT_PROVIDER=local`) |
| `WHISPER_DEVICE` | No | `cpu` | Device for local whisper |
| `WHISPER_COMPUTE_TYPE` | No | `int8` | Quantization for local whisper |
| `TEMP_DIR` | No | `temp` | Folder for temporary audio files |
| `MAX_AUDIO_SIZE_MB` | No | `25` | Max audio upload size |
| `DATABASE_URL` | No | `sqlite:///./test.db` | SQLite connection string |
| `CORS_ORIGINS` | No | `localhost:5173,...` | Comma-separated allowed origins for React |
| `AGENT_PROMPTS_FILE` | No | `config/prompts/aether_knight.yaml` | Custom agent YAML path |

**Never commit `.env` or expose `GROQ_API_KEY` in client-side code.**

---

## Local development setup

### Prerequisites

- Python 3.12+
- `GROQ_API_KEY` from [console.groq.com](https://console.groq.com)
- Microphone + headphones (recommended)

### Step-by-step

```bash
# 1. Clone and enter project
cd aether-knight-

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — add your GROQ_API_KEY

# 5. Start server
uvicorn app.main:app --reload --port 8000
```

### URLs (local)

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8000/voice/demo | Browser UI — login and start chats |
| http://127.0.0.1:8000/docs | Swagger API documentation |
| http://127.0.0.1:8000/redoc | ReDoc API documentation |

### First-time test

1. Open http://127.0.0.1:8000/voice/demo
2. Register a new account
3. Click **New Voice Chat**
4. Allow microphone access
5. Click **Start Conversation**
6. Say: *"Hello, what can you help me with?"*
7. Pause ~1 second — wait for the reply

---

## Docker

### Backend only

```bash
cp .env.example .env    # add GROQ_API_KEY
docker compose up --build
```

| Setting | Value |
|---------|-------|
| API URL | http://localhost:8000 |
| Docs | http://localhost:8000/docs |
| Database | Docker volume `aether-data` → `/data/test.db` |
| Temp audio | `/data/temp` |

### Backend + React frontend

Place repos side by side:

```
Desktop/
├── aether-knight-/              # this repo
└── aether-knight-frontend/
    └── frontend/
```

```bash
docker compose --profile frontend up --build
```

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| React UI | http://localhost:5173 |

Set in `.env`:
```
VITE_API_URL=http://localhost:8000
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### Useful Docker commands

```bash
docker compose down              # stop containers
docker compose down -v           # stop + delete database volume
docker compose logs -f api       # follow API logs
docker compose build --no-cache  # full rebuild
```

---

## React frontend integration

Separate repo: `aether-knight-frontend` (React + TypeScript + Vite)

### Environment

```env
# Local backend
VITE_API_URL=http://127.0.0.1:8000

# Hugging Face production
VITE_API_URL=https://aliashrafabbasi-aether-knight.hf.space
```

### API usage from React

| Concern | How |
|---------|-----|
| Login | `POST /auth/login` → store `token` + `user` in Zustand/localStorage |
| Auth header | `Authorization: Bearer ${token}` on all protected calls |
| New chat | `POST /voice/start` → navigate to `/voice/:sessionId` |
| Voice | WebSocket to `ws(s)://host/voice/live?session_id=...` |
| Admin page | Show `/admin` route only when `user.role === "admin"` |
| Stop chat | `POST /voice/stop?session_id=...` on session end |

### CORS

Backend allows `http://localhost:5173` by default. Add more origins via `CORS_ORIGINS` in `.env`.

---

## Hugging Face deployment

Production Space: **https://aliashrafabbasi-aether-knight.hf.space**

Source repo: `~/Desktop/Aether-knight` (separate from this dev repo)

| Item | Detail |
|------|--------|
| SDK | Docker |
| Port | 7860 |
| Secrets | `GROQ_API_KEY` in Space Settings |
| STT | Groq only (`requirements-hf.txt` — no local Whisper) |
| Database | `/data/aether_knight.db` with persistent storage enabled |
| Registration | No `role` field — first user becomes admin |

To deploy updates:
```bash
cd ~/Desktop/Aether-knight
git add . && git commit -m "message" && git push
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `GROQ_API_KEY is missing` | No key in `.env` | Add key, restart server |
| `No speech detected` | Too quiet or too short | Speak louder, full sentences, pause 1 s |
| `Invalid token` | Expired or logged out | Login again |
| WebSocket closes immediately | Bad `session_id` or no auth | Use `join_url` from `/voice/start` |
| Echo / feedback loop | Speakers too loud | Use headphones |
| AI keeps talking over you | No headphones | Use headphones; barge-in needs clear mic signal |
| CORS error from React | Origin not allowed | Add URL to `CORS_ORIGINS` in `.env` |
| Slow replies | Groq latency or long question | Use shorter questions; check Groq status |
| `Too slow — try a shorter question` | 28 s turn timeout | Ask something shorter |
| Database empty after Docker rebuild | Volume not mounted | Use `docker compose` volume or set `DATABASE_URL` |
| STT wrong language | Mixed language | YAML locks English by default; multilingual in `language` section |

---

## Design decisions

| Decision | Rationale |
|----------|-----------|
| **WebSocket for voice** | Bidirectional, low-latency; status events + binary audio in one connection |
| **Per-utterance WebM recording** | Reliable chunks; streaming concatenation caused corrupt audio |
| **Groq for STT + LLM** | Fast cloud inference; good for real-time voice |
| **Edge TTS** | Free, natural voices, no extra API key |
| **SQLite** | Zero-config; sufficient for single-server deployment |
| **JWT + revocation table** | Stateless auth with secure logout |
| **YAML prompts** | Non-developers can tune personality without code changes |
| **Duplex + barge-in** | Natural conversation feel; user never waits for a button |
| **Auto titles** | ChatGPT-like session list UX |
| **PyAV not ffmpeg** | Pure Python audio conversion; simpler Docker image |
| **ApiResponse envelope** | Consistent `{ success, message, data }` across all endpoints |
| **Inline HTML demo** | Test full voice flow without building a frontend |

---

## License

MIT
