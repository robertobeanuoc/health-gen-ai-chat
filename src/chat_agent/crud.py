import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Message, Session


async def create_session(db: AsyncSession, title: str | None = None) -> Session:
    session = Session(id=str(uuid.uuid4()), title=title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(db: AsyncSession) -> list[tuple]:
    stmt = (
        select(Session, func.count(Message.id).label("message_count"))
        .outerjoin(Message, Message.session_id == Session.id)
        .group_by(Session.id)
        .order_by(Session.updated_at.desc())
    )
    result = await db.execute(stmt)
    return result.all()


async def get_session(db: AsyncSession, session_id: str) -> Session | None:
    stmt = (
        select(Session)
        .where(Session.id == session_id)
        .options(selectinload(Session.messages))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def delete_session(db: AsyncSession, session_id: str) -> bool:
    session = await db.get(Session, session_id)
    if not session:
        return False
    await db.delete(session)
    await db.commit()
    return True


async def update_session_title(db: AsyncSession, session_id: str, title: str) -> Session | None:
    session = await db.get(Session, session_id)
    if not session:
        return None
    session.title = title
    session.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(session)
    return session


async def add_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    dashboard: dict | None = None,
) -> Message:
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role=role,
        content=content,
        dashboard=dashboard,
    )
    db.add(message)

    session = await db.get(Session, session_id)
    if session:
        session.updated_at = datetime.now(timezone.utc)
        if role == "user" and not session.title:
            session.title = content[:80]

    await db.commit()
    await db.refresh(message)
    return message


async def get_message(db: AsyncSession, message_id: str) -> Message | None:
    return await db.get(Message, message_id)


async def get_session_history(db: AsyncSession, session_id: str) -> list[dict]:
    """Return messages formatted for the Anthropic messages API."""
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
    result = await db.execute(stmt)
    return [{"role": m.role, "content": m.content} for m in result.scalars().all()]
