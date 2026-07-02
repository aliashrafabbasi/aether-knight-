import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


def _load_env() -> None:
    load_dotenv(ENV_FILE, override=True)


class Settings:
    def __init__(self) -> None:
        _load_env()
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        # Fast model for low latency voice replies
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.groq_whisper_model = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")
        self.stt_provider = os.getenv("STT_PROVIDER", "groq").lower()
        self.whisper_model = os.getenv("WHISPER_MODEL", "base")
        self.whisper_device = os.getenv("WHISPER_DEVICE", "cpu")
        self.whisper_compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        self.temp_dir = os.getenv("TEMP_DIR", "temp")
        self.max_audio_size_mb = int(os.getenv("MAX_AUDIO_SIZE_MB", "25"))
        self.agent_prompts_file = os.getenv("AGENT_PROMPTS_FILE", "").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return Settings()
