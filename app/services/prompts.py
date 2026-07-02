from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import get_settings
from app.services.language import DEFAULT_LANGUAGE, LANGUAGE_NAMES

DEFAULT_PROMPTS_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "prompts" / "aether_knight.yaml"
)


def _prompts_path() -> Path:
    settings = get_settings()
    custom = getattr(settings, "agent_prompts_file", None)
    if custom:
        path = Path(custom)
        if path.is_file():
            return path
    return DEFAULT_PROMPTS_PATH


@lru_cache
def load_prompts() -> dict:
    path = _prompts_path()
    if not path.is_file():
        raise FileNotFoundError(f"Agent prompts file not found: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def reload_prompts() -> dict:
    load_prompts.cache_clear()
    return load_prompts()


def _agent_name(prompts: dict) -> str:
    return prompts.get("agent", {}).get("name", "Aether Knight")


def format_greeting(user_name: str, prompts: dict | None = None) -> str:
    data = prompts or load_prompts()
    template = data.get("greeting", {}).get("template", "Hello {user_name}.")
    return template.format(user_name=user_name).strip()


def build_stt_prompt(
    user_name: str,
    previous_transcript: str | None = None,
    prompts: dict | None = None,
) -> str:
    data = prompts or load_prompts()
    stt = data.get("stt", {})
    template = stt.get(
        "prompt_template",
        "Voice conversation with {user_name}.",
    )
    parts = [template.format(user_name=user_name).strip()]
    vocab = stt.get("vocabulary") or []
    if vocab:
        parts.append("Terms: " + ", ".join(vocab))
    if previous_transcript:
        parts.append(f"Previous: {previous_transcript}")
    return " ".join(parts)


def build_system_prompt(
    language: str = DEFAULT_LANGUAGE,
    user_name: str | None = None,
    user_email: str | None = None,
    prompts: dict | None = None,
) -> str:
    data = prompts or load_prompts()
    agent = data.get("agent", {})
    name = agent.get("name", "Aether Knight")
    title = agent.get("title", "professional voice assistant")
    description = (agent.get("description") or "").strip()

    lines = [
        f"You are {name}, a {title}.",
        description,
    ]

    if user_name:
        ctx_tpl = data.get("user_context", {}).get("template", "")
        if ctx_tpl:
            lines.append(
                ctx_tpl.format(
                    user_name=user_name,
                    user_email=user_email or "unknown",
                ).strip()
            )

    for item in data.get("personality") or []:
        lines.append(f"- {item}")

    lines.append("Rules:")
    for rule in data.get("rules") or []:
        lines.append(f"- {rule}")

    lang_cfg = data.get("language", {})
    if language == DEFAULT_LANGUAGE:
        lines.append(lang_cfg.get("english", "Reply in clear, professional English."))
    else:
        lang_name = LANGUAGE_NAMES.get(language, language)
        tpl = lang_cfg.get(
            "multilingual",
            "Reply only in {language_name}.",
        )
        lines.append(tpl.format(language_name=lang_name))

    return "\n".join(line for line in lines if line)
