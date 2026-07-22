import uuid
from datetime import datetime

from sqlalchemy import delete, select

from app.core.orm import get_session
from app.models.chat import Chat, ChatMessage


class ChatService:
    async def create_chat(self, user_id: str, title: str | None = None) -> dict:
        chat = Chat(id=str(uuid.uuid4()), user_id=user_id, title=title)
        async with get_session() as session:
            session.add(chat)
            await session.commit()
            await session.refresh(chat)
        return self._chat_to_dict(chat)

    async def list_chats(self, user_id: str) -> list[dict]:
        async with get_session() as session:
            rows = await session.execute(
                select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc())
            )
            return [self._chat_to_dict(c) for c in rows.scalars()]

    async def get_chat(self, chat_id: str, user_id: str) -> dict | None:
        async with get_session() as session:
            row = await session.get(Chat, chat_id)
            if row is None or row.user_id != user_id:
                return None
            return self._chat_to_dict(row)

    async def delete_chat(self, chat_id: str, user_id: str) -> bool:
        async with get_session() as session:
            row = await session.get(Chat, chat_id)
            if row is None or row.user_id != user_id:
                return False
            await session.delete(row)
            await session.commit()
        return True

    async def update_title(self, chat_id: str, user_id: str, title: str) -> dict | None:
        async with get_session() as session:
            row = await session.get(Chat, chat_id)
            if row is None or row.user_id != user_id:
                return None
            row.title = title
            await session.commit()
            await session.refresh(row)
        return self._chat_to_dict(row)

    async def add_message(self, chat_id: str, role: str, content: str) -> dict:
        msg = ChatMessage(id=str(uuid.uuid4()), chat_id=chat_id, role=role, content=content)
        async with get_session() as session:
            session.add(msg)
            # bump chat.updated_at so list_chats stays sorted correctly
            chat = await session.get(Chat, chat_id)
            if chat:
                chat.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(msg)
        return self._msg_to_dict(msg)

    async def get_messages(self, chat_id: str) -> list[dict]:
        async with get_session() as session:
            rows = await session.execute(
                select(ChatMessage)
                .where(ChatMessage.chat_id == chat_id)
                .order_by(ChatMessage.created_at.asc())
            )
            return [self._msg_to_dict(m) for m in rows.scalars()]

    def _chat_to_dict(self, c: Chat) -> dict:
        return {
            "id": c.id,
            "user_id": c.user_id,
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }

    def _msg_to_dict(self, m: ChatMessage) -> dict:
        return {
            "id": m.id,
            "chat_id": m.chat_id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
