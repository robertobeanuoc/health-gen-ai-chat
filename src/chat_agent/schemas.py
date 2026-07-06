from datetime import datetime

from pydantic import BaseModel


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    dashboard: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SessionSummary(SessionOut):
    message_count: int


class SessionDetail(SessionOut):
    messages: list[MessageOut]


class CreateSessionRequest(BaseModel):
    title: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str


class ChatRequest(BaseModel):
    session_id: str
    content: str
    timezone: str | None = None


class ChatResponse(BaseModel):
    reply: str
    message_id: str
    dashboard: dict | None = None
