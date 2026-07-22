import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.routes.auth import get_current_user
from app.services.chat_service import ChatService

router = APIRouter(prefix="/assistant", tags=["assistant"])


def get_chat_service() -> ChatService:
    return ChatService()


# ---------- schemas ----------

class ChatTitleUpdate(BaseModel):
    title: str


class MessageRequest(BaseModel):
    message: str
    stream: bool = False


class NewChatResponse(BaseModel):
    chat: dict
    user_message: dict
    assistant_message: dict


class MessageResponse(BaseModel):
    user_message: dict
    assistant_message: dict


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
    """
    from app.services.assistant_service import chat as assistant_chat, generate_title, stream_chat

    title, response = await asyncio.gather(
        generate_title(body.message),
        assistant_chat(body.message, history=None),
    )

    chat_session = await svc.create_chat(user_id=current_user["id"], title=title)
    chat_id = chat_session["id"]

    user_msg, assistant_msg = await asyncio.gather(
        svc.add_message(chat_id=chat_id, role="user", content=body.message),
        svc.add_message(chat_id=chat_id, role="assistant", content=response),
    )

    if body.stream:
        async def emit():
            for char in response:
                yield char

        return StreamingResponse(emit(), media_type="text/plain", headers={
            "X-Chat-Id": chat_id,
            "X-Chat-Title": title,
        })

    return NewChatResponse(chat=chat_session, user_message=user_msg, assistant_message=assistant_msg)


@router.post("/chats/{chat_id}/messages")
async def send_message(
    chat_id: str,
    body: MessageRequest,
    current_user: dict = Depends(get_current_user),
    svc: ChatService = Depends(get_chat_service),
):
    """Send a message in an existing chat session and get an assistant response."""
    from app.services.assistant_service import chat as assistant_chat, stream_chat

    chat_session = await svc.get_chat(chat_id=chat_id, user_id=current_user["id"])
    if not chat_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found.")

    history_rows = await svc.get_messages(chat_id=chat_id)
    history = [{"role": m["role"], "content": m["content"]} for m in history_rows]

    user_msg = await svc.add_message(chat_id=chat_id, role="user", content=body.message)

    if body.stream:
        async def token_stream():
            collected = []
            async for token in stream_chat(body.message, history):
                collected.append(token)
                yield token
            await svc.add_message(chat_id=chat_id, role="assistant", content="".join(collected))

        return StreamingResponse(token_stream(), media_type="text/plain")

    try:
        response = await assistant_chat(body.message, history)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    assistant_msg = await svc.add_message(chat_id=chat_id, role="assistant", content=response)

    return MessageResponse(user_message=user_msg, assistant_message=assistant_msg)
