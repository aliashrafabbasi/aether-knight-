from groq import Groq

from app.core.config import get_settings
from app.schemas.voice import ChatMessage
from app.services.language import DEFAULT_LANGUAGE
from app.services.prompts import build_system_prompt


def _get_client() -> Groq:
    settings = get_settings()
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not configured")
    return Groq(api_key=settings.groq_api_key)


def chat(
    message: str,
    history: list[ChatMessage] | None = None,
    language: str = DEFAULT_LANGUAGE,
    user_name: str | None = None,
    user_email: str | None = None,
) -> dict:
    settings = get_settings()
    client = _get_client()

    messages = [
        {
            "role": "system",
            "content": build_system_prompt(
                language=language,
                user_name=user_name,
                user_email=user_email,
            ),
        }
    ]
    if history:
        messages.extend(msg.model_dump() for msg in history)
    messages.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        temperature=0.4,
        max_tokens=150,
    )

    reply = response.choices[0].message.content or ""
    return {
        "reply": reply.strip(),
        "model": settings.groq_model,
        "language": language,
    }


def generate_chat_title(user_message: str, assistant_reply: str) -> str:
    """Short contextual title from the first exchange — like ChatGPT."""
    settings = get_settings()
    client = _get_client()

    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Generate a very short chat title (3–6 words) that summarizes "
                    "what this conversation is about. "
                    "Reply with only the title — no quotes, no punctuation at the end. "
                    "Examples: Node.js Help, Python API Question, Trip to Lahore"
                ),
            },
            {
                "role": "user",
                "content": f"User: {user_message}\nAssistant: {assistant_reply}",
            },
        ],
        temperature=0.3,
        max_tokens=24,
    )

    title = (response.choices[0].message.content or "").strip()
    title = title.strip("\"'").rstrip(".")
    if not title:
        title = " ".join(user_message.split())[:60] or "New conversation"
    return title[:60]
