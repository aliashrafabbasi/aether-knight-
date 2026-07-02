"""Legacy shim — chat sessions are persisted in the database."""

from app.services import chat_sessions as _cs


def create_session(user, db=None):
    raise RuntimeError("Use chat_sessions.create_chat_session(db, user) instead")


def get_session(session_id: str, db=None):
    if db is None:
        return None
    session = _cs.get_chat_session(db, session_id)
    if not session:
        return None
    return {
        "user_id": session.user_id,
        "user_name": None,
        "email": None,
        "history": _cs.load_history(db, session_id),
        "language": session.language,
        "created_at": session.created_at,
        "title": session.title,
    }


def end_session(session_id: str) -> None:
    """No-op — sessions are kept in the database for later resume."""
    pass
