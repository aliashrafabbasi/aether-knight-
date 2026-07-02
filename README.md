# Aether Knight

A **real-time voice AI assistant** backend built with FastAPI. Talk naturally over the browser — the agent listens, thinks, and speaks back. Chats are saved like ChatGPT and can be resumed later.

## What it does

1. **You speak** in the browser (microphone).
2. **Speech → text** via Groq Whisper.
3. **AI reply** via Groq LLM (configurable in `.env`).
4. **Text → speech** via Edge TTS.
5. **Conversation is saved** in SQLite — auto-titled from context after the first exchange.

Features include duplex voice (interrupt the agent while it talks), voice commands to end a chat, saved sessions, JWT auth, and admin user APIs.

## Tech stack

| Layer | Technology |
|-------|------------|
| API | FastAPI, WebSockets |
| Auth | JWT + bcrypt |
| Database | SQLite (SQLAlchemy) |
| STT | Groq Whisper |
| LLM | Groq |
| TTS | edge-tts |
| Agent prompts | `config/prompts/aether_knight.yaml` |

## Quick start

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your GROQ_API_KEY
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/docs** for the API, or **http://127.0.0.1:8000/voice/demo** for the browser UI.

### Voice flow

1. `POST /auth/login` → get token  
2. `POST /voice/start` → get `join_url`  
3. Open `join_url` in the browser → **Start Conversation**  
4. Speak; pause ~1 second after each sentence  

**Resume a chat:** `POST /voice/resume` with `session_id`, or pick a saved chat on `/voice/demo`.

**End a chat:** say *"end the conversation"*, click **Stop Chat**, or `POST /voice/stop?session_id=...`.

## Project layout

```
app/
├── api/routes/     # auth, admin, voice endpoints
├── assets/         # browser voice client JS (mic + WebSocket)
├── core/           # config, security, dependencies
├── db/             # models, database
├── services/       # STT, LLM, TTS, sessions, voice agent
└── utils/          # audio conversion (WebM → WAV)
config/prompts/     # agent personality & STT hints (YAML)
```

There is **no separate frontend app**. Demo and voice room pages are served inline from `app/api/routes/voice.py`. The only browser script lives in `app/assets/voice_client.js` and is served at `/voice/client.js`.

## Main API routes

| Route | Description |
|-------|-------------|
| `POST /auth/register` | Create account |
| `POST /auth/login` | Get JWT |
| `POST /voice/start` | New voice chat |
| `POST /voice/resume` | Continue saved chat |
| `GET /voice/sessions` | List saved chats |
| `POST /voice/stop` | End live session |
| `GET /voice/demo` | Browser login + chat hub |
| `GET /voice/join/{id}` | Voice room |

## Configuration

See `.env.example`. Required: `GROQ_API_KEY`.

Edit agent behavior in `config/prompts/aether_knight.yaml` without changing code.
