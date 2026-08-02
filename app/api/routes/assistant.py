import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.routes.auth import get_current_user
from app.services.chat_service import ChatService

router = APIRouter(prefix="/assistant", tags=["assistant"])


def get_chat_service() -> ChatService:
    return ChatService()


def _sse_event(payload: dict) -> str:
    """Serialize a payload as a single NDJSON line for streaming responses."""
    return json.dumps(payload, default=str) + "\n"


# ---------- schemas ----------

class ChatTitleUpdate(BaseModel):
    title: str


class MessageRequest(BaseModel):
    message: str
    stream: bool = False
    symbol: Optional[str] = None  # only used when starting a new chat -> scopes it to a stock


class UIAction(BaseModel):
    type: str
    tab: str


class NewChatResponse(BaseModel):
    chat: dict
    user_message: dict
    assistant_message: dict
    action: Optional[UIAction] = None


class MessageResponse(BaseModel):
    user_message: dict
    assistant_message: dict
    action: Optional[UIAction] = None


# ---------- chat session endpoints ----------

@router.get("/chats")
async def list_chats(
    current_user: dict = Depends(get_current_user),
    svc: ChatService = Depends(get_chat_service),
):
    """List all chat sessions for the current user, newest first."""
    return await svc.list_chats(user_id=current_user["id"])


@router.get("/chats/{chat_id}")
async def get_chat(
    chat_id: str,
    current_user: dict = Depends(get_current_user),
    svc: ChatService = Depends(get_chat_service),
):
    """Get a chat session with its full message history."""
    chat = await svc.get_chat(chat_id=chat_id, user_id=current_user["id"])
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found.")
    messages = await svc.get_messages(chat_id=chat_id)
    return {**chat, "messages": messages}


@router.patch("/chats/{chat_id}")
async def rename_chat(
    chat_id: str,
    body: ChatTitleUpdate,
    current_user: dict = Depends(get_current_user),
    svc: ChatService = Depends(get_chat_service),
):
    """Rename a chat session."""
    chat = await svc.update_title(chat_id=chat_id, user_id=current_user["id"], title=body.title)
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found.")
    return chat


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: str,
    current_user: dict = Depends(get_current_user),
    svc: ChatService = Depends(get_chat_service),
):
    """Delete a chat session and all its messages."""
    deleted = await svc.delete_chat(chat_id=chat_id, user_id=current_user["id"])
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found.")


# ---------- messaging endpoints ----------

@router.post("/chats/messages", status_code=status.HTTP_201_CREATED)
async def start_chat(
    body: MessageRequest,
    current_user: dict = Depends(get_current_user),
    svc: ChatService = Depends(get_chat_service),
):
    """
    Start a new chat with the first message.

    Creates the session, auto-generates a title, and returns the assistant response.
    Pass `symbol` to scope the chat to a specific stock's detail page — answers are then
    grounded only in data already cached in the database for that symbol, and the assistant
    may return an `action` telling the frontend to navigate to a specific tab.
    """
    from app.services.assistant_service import chat as assistant_chat, generate_title, stream_chat

    chat_type = "stock" if body.symbol else "general"

    if body.stream:
        title, chat_session = await _create_chat_with_title(
            body.message, current_user["id"], svc, chat_type, body.symbol
        )
        chat_id = chat_session["id"]
        user_msg = await svc.add_message(chat_id=chat_id, role="user", content=body.message)

        async def token_stream():
            yield _sse_event({
                "type": "start",
                "chat": chat_session,
                "user_message": user_msg,
            })

            collected = []
            action_box: dict = {}
            try:
                async for token in stream_chat(body.message, history=None, symbol=body.symbol, action_box=action_box):
                    collected.append(token)
                    yield _sse_event({"type": "token", "content": token})
            except Exception as e:
                yield _sse_event({"type": "error", "detail": str(e)})
                return

            assistant_msg = await svc.add_message(
                chat_id=chat_id, role="assistant", content="".join(collected)
            )
            yield _sse_event({
                "type": "done",
                "assistant_message": assistant_msg,
                "action": action_box or None,
            })

        return StreamingResponse(
            token_stream(),
            media_type="application/x-ndjson",
            headers={"X-Chat-Id": chat_id, "X-Chat-Title": title},
        )

    title, result = await asyncio.gather(
        generate_title(body.message),
        assistant_chat(body.message, history=None, symbol=body.symbol),
    )

    chat_session = await svc.create_chat(
        user_id=current_user["id"], title=title, type=chat_type, symbol=body.symbol
    )
    chat_id = chat_session["id"]

    user_msg, assistant_msg = await asyncio.gather(
        svc.add_message(chat_id=chat_id, role="user", content=body.message),
        svc.add_message(chat_id=chat_id, role="assistant", content=result["reply"]),
    )

    return NewChatResponse(
        chat=chat_session, user_message=user_msg, assistant_message=assistant_msg, action=result["action"]
    )


async def _create_chat_with_title(
    message: str, user_id: str, svc: ChatService, chat_type: str, symbol: Optional[str]
) -> tuple[str, dict]:
    from app.services.assistant_service import generate_title

    title = await generate_title(message)
    chat_session = await svc.create_chat(user_id=user_id, title=title, type=chat_type, symbol=symbol)
    return title, chat_session


@router.post("/chats/{chat_id}/messages")
async def send_message(
    chat_id: str,
    body: MessageRequest,
    current_user: dict = Depends(get_current_user),
    svc: ChatService = Depends(get_chat_service),
):
    """Send a message in an existing chat session and get an assistant response.

    The chat's own `type`/`symbol` (set when it was created) determines whether this
    is a general assistant conversation or a stock-scoped one — not the request body.
    """
    from app.services.assistant_service import chat as assistant_chat, stream_chat

    chat_session = await svc.get_chat(chat_id=chat_id, user_id=current_user["id"])
    if not chat_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found.")

    symbol = chat_session.get("symbol")

    history_rows = await svc.get_messages(chat_id=chat_id)
    history = [{"role": m["role"], "content": m["content"]} for m in history_rows]

    user_msg = await svc.add_message(chat_id=chat_id, role="user", content=body.message)

    if body.stream:
        async def token_stream():
            yield _sse_event({"type": "start", "user_message": user_msg})

            collected = []
            action_box: dict = {}
            try:
                async for token in stream_chat(body.message, history, symbol=symbol, action_box=action_box):
                    collected.append(token)
                    yield _sse_event({"type": "token", "content": token})
            except Exception as e:
                yield _sse_event({"type": "error", "detail": str(e)})
                return

            assistant_msg = await svc.add_message(
                chat_id=chat_id, role="assistant", content="".join(collected)
            )
            yield _sse_event({
                "type": "done",
                "assistant_message": assistant_msg,
                "action": action_box or None,
            })

        return StreamingResponse(token_stream(), media_type="application/x-ndjson")

    try:
        result = await assistant_chat(body.message, history, symbol=symbol)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    assistant_msg = await svc.add_message(chat_id=chat_id, role="assistant", content=result["reply"])

    return MessageResponse(user_message=user_msg, assistant_message=assistant_msg, action=result["action"])
