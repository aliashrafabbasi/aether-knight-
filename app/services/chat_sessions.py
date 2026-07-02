import logging
import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models
from app.schemas.voice import ChatMessage

logger = logging.getLogger(__name__)

MAX_LLM_HISTORY = 40
DEFAULT_TITLE = "New conversation"


def create_chat_session(
    db: Session,
    user: models.User,
) -> models.ChatSession:
    session = models.ChatSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title=DEFAULT_TITLE,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_chat_session(db: Session, session_id: str) -> models.ChatSession | None:
    return (
        db.query(models.ChatSession)
        .filter(models.ChatSession.id == session_id)
        .first()
    )


def get_user_session(
    db: Session, session_id: str, user_id: str
) -> models.ChatSession | None:
    return (
        db.query(models.ChatSession)
        .filter(
            models.ChatSession.id == session_id,
            models.ChatSession.user_id == user_id,
        )
        .first()
    )


def list_user_sessions(db: Session, user_id: str, limit: int = 50) -> list[models.ChatSession]:
    return (
        db.query(models.ChatSession)
        .filter(models.ChatSession.user_id == user_id)
        .order_by(models.ChatSession.updated_at.desc())
        .limit(limit)
        .all()
    )


def get_session_messages(
    db: Session, session_id: str, limit: int | None = None
) -> list[models.ChatMessage]:
    q = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session_id)
        .order_by(models.ChatMessage.id.asc())
    )
    if limit:
        q = q.limit(limit)
    return q.all()


def message_count(db: Session, session_id: str) -> int:
    return (
        db.query(func.count(models.ChatMessage.id))
        .filter(models.ChatMessage.session_id == session_id)
        .scalar()
        or 0
    )


def last_message_preview(db: Session, session_id: str) -> str | None:
    row = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session_id)
        .order_by(models.ChatMessage.id.desc())
        .first()
    )
    if not row:
        return None
    text = row.content.strip()
    return text[:80] + "…" if len(text) > 80 else text


def messages_to_history(messages: list[models.ChatMessage]) -> list[ChatMessage]:
    recent = messages[-MAX_LLM_HISTORY:] if len(messages) > MAX_LLM_HISTORY else messages
    return [ChatMessage(role=m.role, content=m.content) for m in recent]


def load_history(db: Session, session_id: str) -> list[ChatMessage]:
    return messages_to_history(get_session_messages(db, session_id))


def append_messages(
    db: Session,
    session: models.ChatSession,
    user_text: str,
    assistant_text: str,
) -> None:
    db.add(
        models.ChatMessage(
            session_id=session.id,
            role="user",
            content=user_text,
        )
    )
    db.add(
        models.ChatMessage(
            session_id=session.id,
            role="assistant",
            content=assistant_text,
        )
    )
    session.updated_at = datetime.utcnow()
    db.commit()


def needs_auto_title(session: models.ChatSession) -> bool:
    return session.title == DEFAULT_TITLE


def set_session_title(db: Session, session: models.ChatSession, title: str) -> str:
    clean = " ".join(title.split()).strip()[:60] or DEFAULT_TITLE
    session.title = clean
    session.updated_at = datetime.utcnow()
    db.commit()
    return clean


def update_session_language(
    db: Session, session: models.ChatSession, language: str
) -> None:
    session.language = language
    session.updated_at = datetime.utcnow()
    db.commit()


def delete_chat_session(db: Session, session: models.ChatSession) -> None:
    db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session.id
    ).delete()
    db.delete(session)
    db.commit()


def stop_live_session(db: Session, session: models.ChatSession) -> None:
    """Mark a voice session as stopped (chat remains saved for resume)."""
    session.updated_at = datetime.utcnow()
    db.commit()
    logger.info("Voice session stopped: %s (user=%s)", session.id, session.user_id)
