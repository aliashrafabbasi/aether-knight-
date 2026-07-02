import re

from app.services.prompts import load_prompts

_DEFAULT_END_PHRASES = [
    "close the conversation",
    "end the conversation",
    "end this conversation",
    "close this conversation",
    "let's end the conversation",
    "lets end the conversation",
    "let us end the conversation",
    "stop the conversation",
    "stop this conversation",
    "stop the chat",
    "end the chat",
    "close the chat",
    "end our conversation",
    "that's all for now",
    "thats all for now",
    "i'm done",
    "im done",
    "we are done",
    "goodbye",
    "good bye",
    "bye bye",
    "bye for now",
]


def _normalize(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"[^\w\s']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_end_conversation(text: str) -> bool:
    """Detect when the user wants to close/end the voice chat."""
    if not text or not text.strip():
        return False

    norm = _normalize(text)
    data = load_prompts()
    phrases = data.get("end_conversation", {}).get("phrases") or []

    for phrase in phrases + _DEFAULT_END_PHRASES:
        p = _normalize(phrase)
        if p and p in norm:
            return True

    if norm in {"bye", "goodbye", "good bye", "see you", "see ya"}:
        return True

    return False


def farewell_message(user_name: str | None = None, language: str = "en") -> str:
    data = load_prompts()
    template = data.get("end_conversation", {}).get(
        "farewell_template",
        "Of course, {user_name}. This conversation is now closed. Take care.",
    )
    name = user_name or "there"
    return template.format(user_name=name).strip()
