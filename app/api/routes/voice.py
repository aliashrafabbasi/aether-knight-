import json
import logging

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketState

from app.core.dependencies import bearer_scheme, get_current_user, get_db, get_user_from_token
from app.db.database import SessionLocal
from app.db import models
from app.schemas.response import ApiResponse
from app.schemas.voice import (
    ChatIn,
    ChatMessage,
    ChatOut,
    ChatSessionDetail,
    ChatSessionSummary,
    VoiceSessionOut,
    VoiceSessionResumeIn,
)
from app.services import chat_sessions, llm
from app.services.conversation_intents import farewell_message
from app.services.prompts import format_greeting
from app.services.voice_agent import process_voice, speak

router = APIRouter(prefix="/voice", tags=["Voice"])
logger = logging.getLogger(__name__)

VOICE_CLIENT_JS = Path(__file__).resolve().parents[2] / "assets" / "voice_client.js"


async def _ws_send(websocket: WebSocket, payload: dict) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_json(payload)


def _session_urls(
    request: Request, session_id: str, token: str | None = None
) -> tuple[str, str]:
    host = request.headers.get("host", "127.0.0.1:8000")
    scheme = request.url.scheme
    proto = "wss" if scheme == "https" else "ws"
    ws_url = f"{proto}://{host}/voice/live?session_id={session_id}"
    join_url = f"{scheme}://{host}/voice/join/{session_id}"
    if token:
        join_url = f"{join_url}?token={token}"
    return ws_url, join_url


def _stop_session(db: Session, session_id: str, user_id: str) -> models.ChatSession:
    session = chat_sessions.get_user_session(db, session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    chat_sessions.stop_live_session(db, session)
    logger.info("POST /voice/stop — session %s", session_id)
    return session


async def _auto_title_if_needed(
    db: Session,
    session: models.ChatSession,
    user_text: str,
    assistant_text: str,
    websocket: WebSocket | None = None,
) -> str | None:
    if not chat_sessions.needs_auto_title(session):
        return None
    if not user_text.strip() or user_text.strip().lower() == "end conversation":
        return None
    try:
        title = await run_in_threadpool(
            llm.generate_chat_title, user_text, assistant_text
        )
        title = chat_sessions.set_session_title(db, session, title)
        if websocket:
            await _ws_send(websocket, {
                "success": True,
                "type": "title_updated",
                "data": {"title": title, "session_id": session.id},
            })
        return title
    except Exception as e:
        logger.warning("Auto title failed: %s", e)
        return None


async def _send_speech(websocket: WebSocket, text: str, language: str | None = None) -> None:
    try:
        speech = await speak(text, language)
        if not speech.get("audio_base64"):
            await _ws_send(websocket, {
                "success": True,
                "type": "reply",
                "data": {"reply": text, "model": "tts-unavailable"},
            })
            return
        await _ws_send(websocket, {
            "success": True,
            "type": "speech",
            "data": speech,
        })
    except Exception as e:
        await _ws_send(websocket, {
            "success": False,
            "type": "error",
            "message": f"Speech failed: {e}",
        })
        await _ws_send(websocket, {
            "success": True,
            "type": "reply",
            "data": {"reply": text, "model": "text-only"},
        })


@router.post(
    "/start",
    response_model=ApiResponse[VoiceSessionOut],
    summary="Start new voice chat",
    description=(
        "Creates a new chat session. **No request body needed** — just click Execute "
        "after authorizing with your Bearer token. Returns `session_id` and `join_url`."
    ),
)
def start_voice_chat(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    session = chat_sessions.create_chat_session(db, current_user)
    ws_url, join_url = _session_urls(request, session.id, credentials.credentials)

    return ApiResponse(
        message="New chat started — open join_url in your browser, then talk",
        data=VoiceSessionOut(
            session_id=session.id,
            ws_url=ws_url,
            join_url=join_url,
            title=session.title,
            resumed=False,
            message_count=0,
        ),
    )


@router.post(
    "/resume",
    response_model=ApiResponse[VoiceSessionOut],
    summary="Resume saved voice chat",
    description="Continue a previous chat using its `session_id`.",
)
def resume_voice_chat(
    request: Request,
    payload: VoiceSessionResumeIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    session = chat_sessions.get_user_session(db, payload.session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    ws_url, join_url = _session_urls(request, session.id, credentials.credentials)
    count = chat_sessions.message_count(db, session.id)

    return ApiResponse(
        message="Resuming saved chat — open join_url to continue",
        data=VoiceSessionOut(
            session_id=session.id,
            ws_url=ws_url,
            join_url=join_url,
            title=session.title,
            resumed=True,
            message_count=count,
        ),
    )


@router.get("/sessions", response_model=ApiResponse[list[ChatSessionSummary]])
def list_chat_sessions(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    sessions = chat_sessions.list_user_sessions(db, current_user.id)

    data = []
    for s in sessions:
        _, join_url = _session_urls(request, s.id)
        data.append(
            ChatSessionSummary(
                id=s.id,
                title=s.title,
                language=s.language or "en",
                message_count=chat_sessions.message_count(db, s.id),
                preview=chat_sessions.last_message_preview(db, s.id),
                created_at=s.created_at,
                updated_at=s.updated_at,
                join_url=join_url,
            )
        )

    return ApiResponse(message="Chat sessions loaded", data=data)


@router.get("/sessions/{session_id}", response_model=ApiResponse[ChatSessionDetail])
def get_chat_session_detail(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    session = chat_sessions.get_user_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    messages = chat_sessions.get_session_messages(db, session_id)
    return ApiResponse(
        message="Chat session loaded",
        data=ChatSessionDetail(
            id=session.id,
            title=session.title,
            language=session.language or "en",
            message_count=len(messages),
            created_at=session.created_at,
            updated_at=session.updated_at,
            messages=[
                ChatMessage(role=m.role, content=m.content) for m in messages
            ],
        ),
    )


@router.delete("/sessions/{session_id}", response_model=ApiResponse[None])
def delete_chat_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    session = chat_sessions.get_user_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    chat_sessions.delete_chat_session(db, session)
    return ApiResponse(message="Chat session deleted")


@router.post("/stop", response_model=ApiResponse[None])
def stop_voice_chat(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _stop_session(db, session_id, current_user.id)
    return ApiResponse(
        message="Disconnected. Your conversation is saved — resume anytime with the same session_id.",
    )


@router.websocket("/live")
async def voice_live(
    websocket: WebSocket,
    session_id: str = Query(None),
    token: str = Query(None),
):
    db = SessionLocal()
    user = None
    chat_session = None
    history: list[ChatMessage] = []

    if session_id:
        chat_session = chat_sessions.get_chat_session(db, session_id)
        if not chat_session:
            db.close()
            await websocket.close(code=4001, reason="Invalid session")
            return
        user = db.query(models.User).filter(
            models.User.id == chat_session.user_id
        ).first()
        history = chat_sessions.load_history(db, session_id)
    elif token:
        user = get_user_from_token(token, db)
    else:
        db.close()
        await websocket.close(code=4001, reason="Missing session_id or token")
        return

    if not user:
        db.close()
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    is_resume = len(history) > 0
    if is_resume:
        greeting = (
            f"Welcome back, {user.name}. "
            f"We can continue our conversation about {chat_session.title}."
        )
    else:
        greeting = format_greeting(user.name)

    await _ws_send(websocket, {
        "success": True,
        "type": "ready",
        "message": "Voice agent connected",
        "data": {
            "user": user.name,
            "session_id": session_id,
            "title": chat_session.title if chat_session else None,
            "resumed": is_resume,
        },
    })

    if is_resume:
        await _ws_send(websocket, {
            "success": True,
            "type": "history",
            "data": {
                "messages": [m.model_dump() for m in history],
                "title": chat_session.title,
            },
        })

    await _send_speech(websocket, greeting, language="en")

    audio_buffer = bytearray()
    audio_format = ".webm"
    request_generation = 0

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                audio_buffer.extend(message["bytes"])
                continue

            if "text" not in message:
                continue

            try:
                event = json.loads(message["text"])
            except json.JSONDecodeError:
                await _ws_send(websocket, {
                    "success": False,
                    "type": "error",
                    "message": "Invalid JSON message",
                })
                continue

            event_type = event.get("type")

            if event_type == "cancel":
                audio_buffer.clear()
                request_generation += 1
                continue

            if event_type == "end_session":
                farewell = farewell_message(user.name)
                if chat_session is not None:
                    chat_sessions.append_messages(
                        db, chat_session, "End conversation", farewell
                    )
                    chat_sessions.stop_live_session(db, chat_session)
                await _ws_send(websocket, {
                    "success": True,
                    "type": "transcript",
                    "data": {"text": "End conversation", "language": "en"},
                })
                await _ws_send(websocket, {
                    "success": True,
                    "type": "reply",
                    "data": {"reply": farewell, "model": "end-conversation"},
                })
                await _send_speech(websocket, farewell, language="en")
                await _ws_send(websocket, {
                    "success": True,
                    "type": "session_ended",
                    "message": "Conversation ended. Your chat is saved.",
                    "data": {"session_id": session_id, "call_stop_api": True},
                })
                break

            if event_type == "start":
                audio_buffer.clear()
                audio_format = event.get("format", "webm")
                if not audio_format.startswith("."):
                    audio_format = f".{audio_format}"
                await _ws_send(websocket, {
                    "success": True,
                    "type": "listening",
                    "message": "Speak now...",
                })
                continue

            if event_type == "stop":
                if not audio_buffer or len(audio_buffer) < 3000:
                    await _ws_send(websocket, {
                        "success": False,
                        "type": "error",
                        "message": "Audio too short — speak louder and pause after a full sentence",
                    })
                    audio_buffer.clear()
                    await _ws_send(websocket, {
                        "success": True,
                        "type": "ready",
                        "message": "Try again — speak clearly",
                    })
                    continue

                await _ws_send(websocket, {
                    "success": True,
                    "type": "processing",
                    "message": "Thinking...",
                })

                my_generation = request_generation
                session_lang = chat_session.language if chat_session else None
                user_name = user.name
                user_email = user.email

                async def status_cb(msg: str):
                    await _ws_send(websocket, {
                        "success": True,
                        "type": "processing",
                        "message": msg,
                    })

                async def reply_cb(partial: dict):
                    await _ws_send(websocket, {
                        "success": True,
                        "type": "transcript",
                        "data": {
                            "text": partial["transcript"],
                            "language": partial.get("language"),
                        },
                    })
                    await _ws_send(websocket, {
                        "success": True,
                        "type": "reply",
                        "data": {
                            "reply": partial["reply"],
                            "model": partial["model"],
                            "language": partial.get("language"),
                        },
                    })

                try:
                    result = await process_voice(
                        bytes(audio_buffer),
                        audio_format,
                        history,
                        session_lang,
                        user_name,
                        user_email,
                        on_status=status_cb,
                        on_reply=reply_cb,
                    )
                except ValueError as e:
                    await _ws_send(websocket, {
                        "success": False,
                        "type": "error",
                        "message": str(e),
                    })
                    audio_buffer.clear()
                    await _ws_send(websocket, {
                        "success": True,
                        "type": "ready",
                        "message": "Try again — speak clearly then pause",
                    })
                    continue
                except Exception as e:
                    logger.exception("Voice processing failed: %s", e)
                    await _ws_send(websocket, {
                        "success": False,
                        "type": "error",
                        "message": "Voice agent unavailable — check server logs",
                    })
                    audio_buffer.clear()
                    await _ws_send(websocket, {
                        "success": True,
                        "type": "ready",
                        "message": "Something went wrong — try again",
                    })
                    continue

                if my_generation != request_generation:
                    audio_buffer.clear()
                    continue

                history.append(ChatMessage(role="user", content=result["transcript"]))
                history.append(ChatMessage(role="assistant", content=result["reply"]))
                history = history[-chat_sessions.MAX_LLM_HISTORY:]

                if chat_session is not None:
                    should_title = chat_sessions.needs_auto_title(chat_session)
                    chat_sessions.append_messages(
                        db,
                        chat_session,
                        result["transcript"],
                        result["reply"],
                    )
                    if should_title and not result.get("end_session"):
                        await _auto_title_if_needed(
                            db,
                            chat_session,
                            result["transcript"],
                            result["reply"],
                            websocket,
                        )
                    if result.get("language"):
                        chat_sessions.update_session_language(
                            db, chat_session, result["language"]
                        )
                        session_lang = result["language"]

                await _ws_send(websocket, {
                    "success": True,
                    "type": "speech",
                    "data": {
                        "text": result["reply"],
                        "audio_base64": result["audio_base64"],
                        "format": "mp3",
                        "language": result.get("language"),
                        "turn": my_generation,
                    },
                })

                audio_buffer.clear()

                if result.get("end_session"):
                    if chat_session is not None:
                        chat_sessions.stop_live_session(db, chat_session)
                    await _ws_send(websocket, {
                        "success": True,
                        "type": "session_ended",
                        "message": "Conversation ended. Your chat is saved.",
                        "data": {"session_id": session_id, "call_stop_api": True},
                    })
                    break

                await _ws_send(websocket, {
                    "success": True,
                    "type": "ready",
                    "message": "Speak anytime — interrupt me if you want",
                    "data": {"turn": my_generation},
                })
                continue

            await _ws_send(websocket, {
                "success": False,
                "type": "error",
                "message": f"Unknown event: {event_type}",
            })

    except WebSocketDisconnect:
        pass
    finally:
        db.close()


@router.post("/chat", response_model=ApiResponse[ChatOut])
async def chat(
    payload: ChatIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    history = payload.history
    session_id = payload.session_id
    chat_session = None

    if session_id:
        chat_session = chat_sessions.get_user_session(db, session_id, current_user.id)
        if not chat_session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        if not history:
            history = chat_sessions.load_history(db, session_id)

    try:
        result = await run_in_threadpool(
            llm.chat,
            payload.message,
            history,
            user_name=current_user.name,
            user_email=current_user.email,
        )
        if session_id and chat_session:
            should_title = chat_sessions.needs_auto_title(chat_session)
            chat_sessions.append_messages(
                db,
                chat_session,
                payload.message,
                result["reply"],
            )
            if should_title:
                await _auto_title_if_needed(
                    db, chat_session, payload.message, result["reply"]
                )
            result["session_id"] = session_id
        return ApiResponse(message="Reply generated", data=ChatOut(**result))
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        raise HTTPException(status_code=502, detail="AI service unavailable")


@router.get("/client.js")
def voice_client_js():
    return FileResponse(
        VOICE_CLIENT_JS,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/join/{session_id}", response_class=HTMLResponse)
def voice_join(session_id: str, db: Session = Depends(get_db)):
    session = chat_sessions.get_chat_session(db, session_id)
    if not session:
        return HTMLResponse(
            "<h2>Session not found</h2><p>Call <b>POST /voice/start</b> or resume with <b>POST /voice/start</b> and your saved <b>session_id</b>.</p>",
            status_code=404,
        )

    title = session.title.replace('"', "&quot;")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Aether Knight — {title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; text-align: center; }}
    button {{ font-size: 18px; padding: 16px 32px; margin: 12px; cursor: pointer; border-radius: 12px; border: none; }}
    #connect {{ background: #16a34a; color: white; font-size: 20px; padding: 18px 36px; }}
    #status {{
      width: 120px; height: 120px; border-radius: 50%; margin: 24px auto;
      display: flex; align-items: center; justify-content: center;
      font-size: 48px; background: #333; transition: background 0.3s;
    }}
    #status.listening {{ background: #16a34a; box-shadow: 0 0 24px #16a34a88; }}
    #status.recording {{ background: #2563eb; box-shadow: 0 0 24px #2563eb88; animation: pulse 1s infinite; }}
    #status.processing {{ background: #ca8a04; box-shadow: 0 0 24px #ca8a0488; }}
    #status.speaking {{ background: #9333ea; box-shadow: 0 0 24px #9333ea88; }}
    @keyframes pulse {{ 0%,100%{{ transform:scale(1); }} 50%{{ transform:scale(1.05); }} }}
    #statusText {{ font-size: 18px; color: #444; margin-bottom: 8px; }}
    #log {{ background: #111; color: #0f0; padding: 16px; border-radius: 8px; min-height: 180px; text-align: left; white-space: pre-wrap; margin-top: 16px; font-size: 14px; }}
    .user {{ color: #6cf; }} .ai {{ color: #fc6; }} .sys {{ color: #aaa; }}
    .hint {{ color: #666; font-size: 14px; }}
    .nav {{ margin: 16px 0; }}
    .nav a, #newChat {{
      display: inline-block; margin: 6px; padding: 10px 18px;
      background: #2563eb; color: white; text-decoration: none; border-radius: 8px; font-size: 15px;
      border: none; cursor: pointer;
    }}
    #newChat {{ background: #7c3aed; }}
  </style>
</head>
<body>
  <div class="nav">
    <a href="/voice/demo">🏠 Chat Home</a>
    <button id="newChat" type="button">➕ Start New Chat</button>
  </div>
  <h1 id="pageTitle">🎙️ {title}</h1>
  <p class="hint"><b>Natural conversation</b> — talk anytime. Say <b>"end the conversation"</b> to close. Use <b>headphones</b>.</p>
  <button id="connect">▶ Start Conversation</button>
  <button id="stopChat" style="display:none;background:#dc2626;color:white;">⏹ Stop Chat</button>
  <div id="status" style="display:none">🎤</div>
  <div id="statusText"></div>
  <div id="log"></div>
  <script src="/voice/client.js"></script>
  <script>
    const sessionId = "{session_id}";
    const authToken = new URLSearchParams(location.search).get("token")
      || sessionStorage.getItem("voice_token");
    let ws, voiceClient, audioEnabled = false;
    let stopApiCalled = false;

    const log = (text, cls = "sys") => {{
      document.getElementById("log").innerHTML += `<div class="${{cls}}">${{text}}</div>`;
      document.getElementById("log").scrollTop = 99999;
    }};

    const showHistory = (messages) => {{
      if (!messages?.length) return;
      log("— Previous messages —", "sys");
      for (const m of messages) {{
        log((m.role === "user" ? "You: " : "AI: ") + m.content, m.role === "user" ? "user" : "ai");
      }}
      log("— Continuing conversation —", "sys");
    }};

    async function callStopApi() {{
      if (stopApiCalled || !authToken || !sessionId) {{
        if (!authToken) log("No auth token — stop API skipped (use join_url from /voice/start)", "sys");
        return;
      }}
      stopApiCalled = true;
      try {{
        const res = await fetch(`/voice/stop?session_id=${{encodeURIComponent(sessionId)}}`, {{
          method: "POST",
          headers: {{ Authorization: "Bearer " + authToken }},
        }});
        const data = await res.json();
        log(data.success ? ("✓ Stop API: " + data.message) : ("Stop API failed: " + data.message), "sys");
      }} catch (err) {{
        log("Stop API error: " + err, "sys");
        stopApiCalled = false;
      }}
    }}

    const setStatus = (state, text) => {{
      const el = document.getElementById("status");
      const txt = document.getElementById("statusText");
      el.style.display = "flex";
      el.className = state;
      txt.textContent = text;
      const icons = {{ listening: "🎤", recording: "🔵", processing: "🤔", speaking: "🔊", paused: "⏸" }};
      el.textContent = icons[state] || "🎤";
    }};

    const handleMessage = async (e) => {{
      const msg = JSON.parse(e.data);
      if (msg.type === "processing") {{
        setStatus("processing", msg.message);
        return;
      }}
      if (msg.type === "transcript") log("You (" + (msg.data.language || "?") + "): " + msg.data.text, "user");
      if (msg.type === "title_updated") {{
        const t = msg.data?.title;
        if (t) {{
          document.getElementById("pageTitle").textContent = "🎙️ " + t;
          document.title = "Aether Knight — " + t;
          log("Chat: " + t, "sys");
        }}
      }}
      if (msg.type === "reply") {{
        log("AI: " + msg.data.reply, "ai");
        setStatus("processing", "Reply ready — loading voice…");
      }}
      if (msg.type === "speech" && audioEnabled) {{
        log("🔊 " + msg.data.text, "ai");
        voiceClient.playSpeech(msg.data.audio_base64);
        return;
      }}
      if (msg.type === "error") {{
        log("Error: " + msg.message, "sys");
        voiceClient?.onServerReady();
        return;
      }}
      if (msg.type === "ready") {{
        voiceClient?.onServerReady();
        if (msg.message) setStatus("listening", msg.message);
      }}
      if (msg.type === "session_ended") {{
        log(msg.message || "Conversation ended.", "sys");
        setStatus("paused", "Chat ended — saved");
        await callStopApi();
        voiceClient?.endSession();
      }}
    }};

    document.getElementById("connect").onclick = async () => {{
      audioEnabled = true;
      document.getElementById("connect").style.display = "none";
      log("Connecting...", "sys");

      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${{proto}}://${{location.host}}/voice/live?session_id=${{sessionId}}`);

      ws.onopen = () => {{
        log("Connected — agent is greeting you...", "sys");
        voiceClient = new NaturalVoiceClient(ws, {{
          onLog: log,
          onStatus: setStatus,
        }});
        document.getElementById("stopChat").style.display = "inline-block";
      }};

      const startListening = async () => {{
        if (voiceClient.stream) return;
        await voiceClient.start();
        setStatus("listening", "Talk naturally — interrupt anytime");
        log("Duplex mic on — speak over the agent anytime", "sys");
      }};

      const playGreeting = (b64) => new Promise((resolve) => {{
        if (!b64) return resolve();
        const audio = new Audio("data:audio/mp3;base64," + b64);
        audio.onended = resolve;
        audio.onerror = resolve;
        audio.play().catch(resolve);
      }});

      let greeted = false;
      let pendingHistory = null;
      ws.onmessage = async (e) => {{
        const msg = JSON.parse(e.data);
        if (msg.type === "history") {{
          pendingHistory = msg.data?.messages || [];
          if (msg.data?.title) {{
            document.getElementById("pageTitle").textContent = "🎙️ " + msg.data.title;
          }}
          return;
        }}
        if (!greeted) {{
          if (msg.type === "ready") {{
            const name = msg.data?.user || "there";
            const resumed = msg.data?.resumed;
            log((resumed ? "Resuming chat for " : "Welcome, ") + name + ".", "sys");
            if (pendingHistory) showHistory(pendingHistory);
            return;
          }}
          greeted = true;
          ws.onmessage = handleMessage;
          await startListening();
          if (msg.type === "speech") {{
            log("🔊 " + msg.data.text, "ai");
            voiceClient.playSpeech(msg.data.audio_base64);
          }}
          if (msg.type === "reply") log("AI: " + msg.data.reply, "ai");
          return;
        }}
        await handleMessage(e);
      }};

      ws.onclose = () => {{
        log("Disconnected", "sys");
        voiceClient?.stop();
      }};

      ws.onerror = () => log("WebSocket error", "sys");
    }};

    document.getElementById("newChat").onclick = () => {{
      window.location.href = "/voice/demo";
    }};

    document.getElementById("stopChat").onclick = async () => {{
      if (!voiceClient) return;
      log("Ending conversation…", "sys");
      await callStopApi();
      voiceClient.requestEnd();
    }};
  </script>
</body>
</html>"""


@router.get("/demo", response_class=HTMLResponse)
def voice_demo():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Aether Knight Voice</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; }
    input, button { font-size: 16px; padding: 10px 14px; margin: 6px 0; }
    input { width: 100%; box-sizing: border-box; }
    button { cursor: pointer; margin-right: 8px; border-radius: 8px; border: none; }
    #start { background: #16a34a; color: white; font-size: 18px; padding: 14px 24px; }
    #login { background: #333; color: white; }
    #resume { background: #2563eb; color: white; }
    .steps { background: #f4f4f5; padding: 14px; border-radius: 8px; margin: 16px 0; text-align: left; font-size: 14px; }
    #log { background: #111; color: #0f0; padding: 16px; border-radius: 8px; min-height: 120px; white-space: pre-wrap; }
    .user { color: #6cf; } .ai { color: #fc6; } .sys { color: #aaa; }
  </style>
</head>
<body>
  <h1>🎙️ Aether Knight — Voice Chat</h1>
  <div class="steps">
    <b>How to start a NEW chat:</b><br>
    1. Login below<br>
    2. Click the green <b>New Voice Chat</b> button<br>
    3. Allow microphone → click <b>Start Conversation</b><br><br>
    <b>To continue an old chat:</b> click <b>Resume</b> on any saved chat below.
  </div>
  <input id="email" placeholder="Email" />
  <input id="password" type="password" placeholder="Password" />
  <br>
  <button id="login">1. Login</button>
  <button id="start" disabled>➕ 2. New Voice Chat</button>
  <div id="sessions" style="margin-top:16px"></div>
  <div id="log"></div>
  <script>
    let token, ws, mediaRecorder, savedSessions = [];

    const log = (text, cls = "sys") => {
      const el = document.getElementById("log");
      el.innerHTML += `<div class="${cls}">${text}</div>`;
      el.scrollTop = el.scrollHeight;
    };

    async function loadSessions() {
      const res = await fetch("/voice/sessions", {
        headers: { Authorization: "Bearer " + token },
      });
      const data = await res.json();
      if (!data.success) return;
      savedSessions = data.data || [];
      const box = document.getElementById("sessions");
      if (!savedSessions.length) {
        box.innerHTML = "<p style='color:#666'>No saved chats yet — click <b>New Voice Chat</b> above.</p>";
        return;
      }
      box.innerHTML = "<h3>Saved chats</h3>" + savedSessions.map((s, i) =>
        `<div style="border:1px solid #ddd;padding:10px;margin:8px 0;border-radius:8px">
          <b>${s.title}</b><br>
          <small>${s.message_count} messages · ${new Date(s.updated_at).toLocaleString()}</small><br>
          <button onclick="resumeChat('${s.id}')">Resume</button>
          <button onclick="deleteChat('${s.id}')">Delete</button>
        </div>`
      ).join("");
    }

    async function resumeChat(sessionId) {
      const res = await fetch("/voice/resume", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const data = await res.json();
      if (!data.success) return log("Resume failed: " + data.message, "sys");
      log("Resuming: " + data.data.title + " (" + data.data.message_count + " messages)", "sys");
      window.location.href = data.data.join_url;
    }

    async function deleteChat(sessionId) {
      if (!confirm("Delete this chat?")) return;
      await fetch("/voice/sessions/" + sessionId, {
        method: "DELETE",
        headers: { Authorization: "Bearer " + token },
      });
      loadSessions();
    }

    document.getElementById("login").onclick = async () => {
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: document.getElementById("email").value,
          password: document.getElementById("password").value,
        }),
      });
      const data = await res.json();
      if (!data.success) return log("Login failed: " + data.message, "sys");
      token = data.data.token;
      sessionStorage.setItem("voice_token", token);
      log("Logged in as " + data.data.user.name, "sys");
      document.getElementById("start").disabled = false;
      loadSessions();
    };

    document.getElementById("start").onclick = async () => {
      const res = await fetch("/voice/start", {
        method: "POST",
        headers: { Authorization: "Bearer " + token },
      });
      const data = await res.json();
      if (!data.success) return log("Start failed: " + data.message, "sys");
      log("New chat started — opening voice room...", "sys");
      window.location.href = data.data.join_url;
    };
  </script>
</body>
</html>"""
