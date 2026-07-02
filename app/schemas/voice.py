from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class TranscriptOut(BaseModel):
    text: str
    language: Optional[str] = None
    duration: Optional[float] = None


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[ChatMessage] = []
    session_id: Optional[str] = None


class ChatOut(BaseModel):
    reply: str
    model: str
    session_id: Optional[str] = None


class AgentOut(BaseModel):
    transcript: str
    reply: str
    language: Optional[str] = None
    model: str


class VoiceSessionResumeIn(BaseModel):
    """Resume a saved chat session."""
    session_id: str = Field(..., description="Saved session ID from a previous /voice/start")


class VoiceSessionOut(BaseModel):
    session_id: str
    ws_url: str
    join_url: str
    title: str
    resumed: bool = False
    message_count: int = 0


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    language: str
    message_count: int
    preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    join_url: Optional[str] = None


class ChatSessionDetail(BaseModel):
    id: str
    title: str
    language: str
    message_count: int
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessage]


class SpeechOut(BaseModel):
    text: str
    audio_base64: str
    format: str = "mp3"
