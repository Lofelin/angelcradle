"""
会话资源 API：1v1（DM）与多宝宝群聊同构资源。

设计要点：
- conv_id 确定性（同组宝宝复用同一会话）
- SSE 仅承载会话事件（与 cradle lifeline 日志通道分离）
- POST messages 触发宝宝回应：群聊首次为破冰，否则 P1 round-robin

[INPUT]: 依赖 cradle.conversation / cradle.conversation_store
[OUTPUT]: FastAPI router，挂载在 /conversations
[POS]: API 层，前端会话窗口通过此模块订阅和发消息
[PROTOCOL]: 变更时更新此头部，然后检查 api/CLAUDE.md 与 cradle/CLAUDE.md
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cradle import (
    make_conv_id, get_or_create_conversation, rename_conversation,
    get_conversation, list_conversations, list_messages,
    post_parent_message,
)
from cradle.conversation_store import get_conv_notify, load_conv_messages_after

router = APIRouter(prefix="/conversations")

# SSE 常量（与 api/cradle.py 对齐）
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
_SSE_IDLE_TICK = 15  # 无消息时多久发送一次 heartbeat 保活


# ============================================================
# 请求模型
# ============================================================

class CreateConversationRequest(BaseModel):
    participants: list[str]
    kind: str                           # "dm" | "group"
    display_name: Optional[str] = None  # group 必填，dm 可省


class RenameConversationRequest(BaseModel):
    display_name: str


class PostMessageRequest(BaseModel):
    content: str
    action_type: str = "message"        # "message" | "touch"
    touch_key: Optional[str] = None


# ============================================================
# CRUD
# ============================================================

@router.post("")
def create_conversation(req: CreateConversationRequest):
    """幂等创建会话：同组宝宝返回同一 conv_id。"""
    if req.kind not in ("dm", "group"):
        raise HTTPException(400, f"Invalid kind: {req.kind}")
    if req.kind == "dm" and len(req.participants) != 1:
        raise HTTPException(400, "DM requires exactly 1 baby participant")
    if req.kind == "group" and len(set(req.participants)) < 2:
        raise HTTPException(400, "Group requires at least 2 distinct baby participants")
    if req.kind == "group" and not (req.display_name and req.display_name.strip()):
        raise HTTPException(400, "Group conversation requires display_name")
    try:
        return get_or_create_conversation(req.participants, req.kind, req.display_name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("")
def list_convs(baby_id: Optional[str] = None):
    """列出所有会话。可按 baby_id 过滤。"""
    try:
        return {"conversations": list_conversations(baby_id)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{conv_id}")
def get_conv(conv_id: str):
    try:
        meta = get_conversation(conv_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if meta is None:
        raise HTTPException(404, f"Conversation '{conv_id}' not found")
    return meta


@router.patch("/{conv_id}")
def rename_conv(conv_id: str, req: RenameConversationRequest):
    try:
        return rename_conversation(conv_id, req.display_name)
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg else 400
        raise HTTPException(status, msg)


# ============================================================
# 消息
# ============================================================

@router.get("/{conv_id}/messages")
def get_messages(conv_id: str, after_seq: int = 0):
    """拉取历史消息。"""
    try:
        if get_conversation(conv_id) is None:
            raise HTTPException(404, f"Conversation '{conv_id}' not found")
        return {"messages": list_messages(conv_id, after_seq)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{conv_id}/messages")
async def post_message(conv_id: str, req: PostMessageRequest):
    """
    家长发一条消息。返回 {"seq", "triggered_babies"}。

    同步完成所有宝宝回应（串行 LLM）后才返回。
    前端可同时订阅 /stream 接收每条消息的 SSE 推送。
    """
    if get_conversation(conv_id) is None:
        raise HTTPException(404, f"Conversation '{conv_id}' not found")
    try:
        return await post_parent_message(
            conv_id=conv_id,
            content=req.content,
            action_type=req.action_type,
            touch_key=req.touch_key,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ============================================================
# SSE
# ============================================================

@router.get("/{conv_id}/stream")
async def stream_conversation(conv_id: str, after_seq: int = 0):
    """
    会话 SSE：回放历史 + 实时追踪。

    Phase 1: 读 messages.jsonl 中 seq > after_seq
    Phase 2: await notify → 读增量 → 推送
    每 _SSE_IDLE_TICK 秒无消息 → SSE 注释保活
    """
    if get_conversation(conv_id) is None:
        raise HTTPException(404, f"Conversation '{conv_id}' not found")

    async def event_generator():
        last_seq = after_seq
        notify = get_conv_notify(conv_id)

        # Phase 1: 回放
        msgs = load_conv_messages_after(conv_id, last_seq)
        for m in msgs:
            yield _sse(m)
            last_seq = m.get("seq", last_seq)
            await asyncio.sleep(0.1)

        # Phase 2: 实时
        while True:
            new_msgs = load_conv_messages_after(conv_id, last_seq)
            if new_msgs:
                for m in new_msgs:
                    yield _sse(m)
                    last_seq = m.get("seq", last_seq)
                    await asyncio.sleep(0.1)
                continue

            notify.clear()
            new_msgs = load_conv_messages_after(conv_id, last_seq)
            if new_msgs:
                for m in new_msgs:
                    yield _sse(m)
                    last_seq = m.get("seq", last_seq)
                    await asyncio.sleep(0.1)
                continue

            try:
                await asyncio.wait_for(notify.wait(), timeout=_SSE_IDLE_TICK)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
