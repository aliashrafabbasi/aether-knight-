import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from app.schemas.voice import ChatMessage
from app.services import llm, stt
from app.services.conversation_intents import farewell_message, is_end_conversation
from app.services.language import DEFAULT_LANGUAGE, resolve_language
from app.services.tts import text_to_speech_base64

logger = logging.getLogger(__name__)

PROCESS_TIMEOUT = 45


async def process_voice(
    audio: bytes,
    extension: str = ".webm",
    history: list[ChatMessage] | None = None,
    session_lang: str | None = None,
    user_name: str | None = None,
    user_email: str | None = None,
    on_status=None,
    on_reply=None,
) -> dict:
    async def _run():
        if on_status:
            await on_status("Listening…")

        previous = None
        if history:
            for msg in reversed(history):
                if msg.role == "user":
                    previous = msg.content
                    break

        transcript = await run_in_threadpool(
            stt.transcribe_bytes,
            audio,
            extension,
            session_lang,
            user_name,
            previous,
        )

        if not transcript["text"]:
            raise ValueError("No speech detected — speak clearly, then pause")

        language = resolve_language(transcript.get("language"), session_lang)

        if is_end_conversation(transcript["text"]):
            reply_text = farewell_message(user_name, language)
            partial = {
                "transcript": transcript["text"],
                "language": language,
                "reply": reply_text,
                "model": "end-conversation",
                "end_session": True,
            }
            if on_reply:
                await on_reply(partial)
            if on_status:
                await on_status("Closing conversation…")
            speech_b64 = await text_to_speech_base64(reply_text, language)
            return {**partial, "audio_base64": speech_b64}

        if on_status:
            await on_status("Thinking…")

        reply = await run_in_threadpool(
            llm.chat,
            transcript["text"],
            history,
            language,
            user_name,
            user_email,
        )

        partial = {
            "transcript": transcript["text"],
            "language": language,
            "reply": reply["reply"],
            "model": reply["model"],
        }

        if on_reply:
            await on_reply(partial)

        if on_status:
            await on_status("Speaking…")

        speech_b64 = await text_to_speech_base64(reply["reply"], language)

        return {**partial, "audio_base64": speech_b64, "end_session": False}

    try:
        return await asyncio.wait_for(_run(), timeout=PROCESS_TIMEOUT)
    except asyncio.TimeoutError:
        raise ValueError("Too slow — try a shorter question")


async def speak(text: str, language: str = DEFAULT_LANGUAGE) -> dict:
    audio_b64 = await text_to_speech_base64(text, language)
    return {
        "text": text,
        "audio_base64": audio_b64,
        "format": "mp3",
        "language": language,
    }
