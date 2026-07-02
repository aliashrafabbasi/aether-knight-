import io
import logging
import uuid
import wave
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def ensure_temp_dir() -> Path:
    settings = get_settings()
    path = Path(settings.temp_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_audio_bytes(data: bytes, extension: str = ".webm") -> str:
    settings = get_settings()
    max_bytes = settings.max_audio_size_mb * 1024 * 1024

    if not data:
        raise ValueError("No audio received")
    if len(data) > max_bytes:
        raise ValueError(f"Audio too large (max {settings.max_audio_size_mb}MB)")

    ext = extension if extension.startswith(".") else f".{extension}"
    file_path = ensure_temp_dir() / f"{uuid.uuid4()}{ext}"

    with open(file_path, "wb") as f:
        f.write(data)

    return str(file_path)


def _pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return out.getvalue()


def _decode_with_av(source, sample_rate: int = 16000) -> bytes:
    import av

    resampler = av.audio.resampler.AudioResampler(
        format="s16",
        layout="mono",
        rate=sample_rate,
    )

    pcm = bytearray()
    container = av.open(source, mode="r")

    if not container.streams.audio:
        raise ValueError("No audio stream in file")

    for frame in container.decode(audio=0):
        for resampled in resampler.resample(frame):
            pcm.extend(bytes(resampled.planes[0]))

    for resampled in resampler.resample(None):
        pcm.extend(bytes(resampled.planes[0]))

    if len(pcm) < 1600:
        raise ValueError("Decoded audio too short")

    return bytes(pcm)


def prepare_stt_audio(data: bytes, extension: str = ".webm") -> tuple[bytes, str]:
    """Convert browser audio to 16 kHz mono WAV using PyAV (no ffmpeg required)."""
    ext = extension.lstrip(".") or "webm"
    errors: list[str] = []

    # Try in-memory decode (auto-detect format)
    try:
        pcm = _decode_with_av(io.BytesIO(data))
        return _pcm_to_wav(pcm), ".wav"
    except Exception as e:
        errors.append(f"memory: {e}")

    # Try via temp file (some WebM containers need seek)
    file_path = save_audio_bytes(data, f".{ext}")
    try:
        pcm = _decode_with_av(file_path)
        return _pcm_to_wav(pcm), ".wav"
    except Exception as e:
        errors.append(f"file: {e}")
        logger.error("Audio decode failed: %s", "; ".join(errors))
        raise ValueError(
            "Could not decode microphone audio. "
            "Refresh the page and speak a full sentence."
        ) from e
    finally:
        cleanup_file(file_path)


def convert_to_wav(file_path: str) -> str:
    pcm = _decode_with_av(file_path)
    wav_path = str(Path(file_path).with_suffix(".wav"))
    with open(wav_path, "wb") as f:
        f.write(_pcm_to_wav(pcm))
    return wav_path


def cleanup_file(file_path: str) -> None:
    try:
        Path(file_path).unlink(missing_ok=True)
    except OSError:
        pass
