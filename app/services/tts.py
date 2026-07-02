import base64
import logging

logger = logging.getLogger(__name__)

# Natural neural voices per language (Edge TTS)
VOICE_MAP = {
    "en": "en-US-JennyNeural",
    "ur": "ur-PK-UzmaNeural",
    "hi": "hi-IN-SwaraNeural",
    "ar": "ar-SA-ZariyahNeural",
    "pa": "pa-IN-GulNeural",
    "bn": "bn-IN-TanishaaNeural",
    "ta": "ta-IN-PallaviNeural",
    "te": "te-IN-ShrutiNeural",
    "mr": "mr-IN-AarohiNeural",
    "gu": "gu-IN-DhwaniNeural",
    "fr": "fr-FR-DeniseNeural",
    "es": "es-ES-ElviraNeural",
    "de": "de-DE-KatjaNeural",
    "tr": "tr-TR-EmelNeural",
    "fa": "fa-IR-DilaraNeural",
}

DEFAULT_VOICE = "en-US-JennyNeural"
SPEECH_RATE = "+8%"


def voice_for_language(language: str | None) -> str:
    if not language:
        return DEFAULT_VOICE
    code = language.lower().split("-")[0]
    return VOICE_MAP.get(code, DEFAULT_VOICE)


async def text_to_speech(text: str, language: str | None = None) -> bytes:
    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts not installed — speech disabled")
        return b""

    voice = voice_for_language(language)
    communicate = edge_tts.Communicate(text, voice, rate=SPEECH_RATE)
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


async def text_to_speech_base64(text: str, language: str | None = None) -> str:
    audio = await text_to_speech(text, language)
    if not audio:
        return ""
    return base64.b64encode(audio).decode()
