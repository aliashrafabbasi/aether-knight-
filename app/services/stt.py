import logging

from groq import Groq

from app.core.config import get_settings
from app.services.language import DEFAULT_LANGUAGE
from app.services.prompts import build_stt_prompt
from app.utils.audio import prepare_stt_audio

logger = logging.getLogger(__name__)


def _groq_client() -> Groq:
    settings = get_settings()
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not configured")
    return Groq(api_key=settings.groq_api_key)


def _language_hint(session_lang: str | None) -> str:
    """Lock English by default — dramatically improves accuracy for English speakers."""
    if session_lang and session_lang != DEFAULT_LANGUAGE:
        return session_lang.split("-")[0]
    return "en"


def transcribe_groq(
    data: bytes,
    extension: str = ".webm",
    language_hint: str | None = None,
    user_name: str | None = None,
    previous_transcript: str | None = None,
) -> dict:
    settings = get_settings()

    try:
        wav_data, wav_ext = prepare_stt_audio(data, extension)
    except ValueError as e:
        raise ValueError(str(e)) from e
    except Exception as e:
        logger.exception("STT audio preparation failed")
        raise ValueError("Could not process microphone audio — try again") from e

    filename = f"audio{wav_ext}"
    client = _groq_client()

    prompt = build_stt_prompt(user_name, previous_transcript)

    kwargs = {
        "file": (filename, wav_data),
        "model": settings.groq_whisper_model,
        "response_format": "verbose_json",
        "temperature": 0.0,
        "language": _language_hint(language_hint),
        "prompt": prompt,
    }

    result = client.audio.transcriptions.create(**kwargs)

    text = (result.text or "").strip()
    language = getattr(result, "language", None) or "en"

    return {
        "text": text,
        "language": language,
        "duration": None,
    }


def _local_transcribe(data: bytes, extension: str) -> dict:
    from functools import lru_cache

    from faster_whisper import WhisperModel

    from app.utils.audio import cleanup_file, convert_to_wav, save_audio_bytes

    @lru_cache
    def _model():
        settings = get_settings()
        return WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )

    file_path = save_audio_bytes(data, extension)
    wav_path = None
    try:
        try:
            wav_path = convert_to_wav(file_path)
            source = wav_path
        except Exception:
            source = file_path

        model = _model()
        segments, info = model.transcribe(
            source,
            language="en",
            vad_filter=True,
            beam_size=5,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"text": text, "language": info.language, "duration": info.duration}
    finally:
        cleanup_file(file_path)
        if wav_path:
            cleanup_file(wav_path)


def transcribe_bytes(
    data: bytes,
    extension: str = ".webm",
    language_hint: str | None = None,
    user_name: str | None = None,
    previous_transcript: str | None = None,
) -> dict:
    if len(data) < 3000:
        raise ValueError("Audio too short — speak a full sentence, then pause")

    settings = get_settings()

    if settings.stt_provider == "groq":
        return transcribe_groq(
            data, extension, language_hint, user_name, previous_transcript
        )

    return _local_transcribe(data, extension)
