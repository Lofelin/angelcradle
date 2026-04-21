"""
会话资源持久化层：meta.json + messages.jsonl + SSE 基础设施。

与 cradle/state.py 的 baby 级 events.jsonl 基础设施同构，但独立命名空间：
- 存储路径：archive/conversations/{conv_id}/
- seq 游标：per-conv 单调递增
- notify/lock：per-conv asyncio.Event / asyncio.Lock

[INPUT]: 依赖 cradle/state.py 的 ARCHIVE_DIR / _validate_baby_id / _count_lines
[OUTPUT]: conv_id 校验、meta 读写、messages 追加/读取、notify/lock 管理
[POS]: cradle/ 会话持久化层，被 cradle/conversation.py 与 api/conversations.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import threading
import time as _time
from pathlib import Path
from typing import Optional

from .state import ARCHIVE_DIR, _validate_baby_id, _count_lines

# 会话根目录
_CONV_ROOT = ARCHIVE_DIR / "conversations"

# conv_id 规则：dm:{baby_id} 或 gp:{sorted_baby_ids_joined_with_underscore}
_SAFE_CONV_ID_RE = re.compile(r'^(dm|gp):[a-zA-Z0-9_-]+$')

# 基础设施（与 cradle/state.py 同构）
_conv_seq_counters: dict[str, int] = {}
_conv_seq_locks: dict[str, threading.Lock] = {}
_conv_notify: dict[str, asyncio.Event] = {}
_conv_locks: dict[str, asyncio.Lock] = {}
_infra_lock = threading.Lock()


# ============================================================
# conv_id 校验 / 路径
# ============================================================

def validate_conv_id(conv_id: str) -> str:
    """校验 conv_id，阻止路径遍历。"""
    if not conv_id or not _SAFE_CONV_ID_RE.match(conv_id):
        raise ValueError(f"Invalid conv_id: {conv_id!r}")
    return conv_id


def conversation_dir(conv_id: str) -> Path:
    validate_conv_id(conv_id)
    return _CONV_ROOT / conv_id


# ============================================================
# 原子写 JSON
# ============================================================

def _atomic_write_json(path: Path, data: dict) -> None:
    """tempfile + os.replace 原子写入。"""
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ============================================================
# Meta（会话元信息）读写
# ============================================================

def ensure_conversation(
    conv_id: str,
    participants: list[str],
    kind: str,
    display_name: str,
) -> dict:
    """幂等创建会话：存在则读回，不存在则写入初始 meta。"""
    validate_conv_id(conv_id)
    if kind not in ("dm", "group"):
        raise ValueError(f"Invalid kind: {kind!r}")
    for bid in participants:
        _validate_baby_id(bid)

    d = conversation_dir(conv_id)
    d.mkdir(parents=True, exist_ok=True)
    meta_path = d / "meta.json"

    if meta_path.is_file():
        return json.loads(meta_path.read_text(encoding="utf-8"))

    now = _time.time()
    meta = {
        "conv_id": conv_id,
        "kind": kind,
        "participants": list(participants),
        "display_name": display_name,
        "created_at": now,
        "last_active_ts": now,
        "icebreaker_done": False,
        "message_count": 0,
    }
    _atomic_write_json(meta_path, meta)
    return meta


def load_conversation_meta(conv_id: str) -> Optional[dict]:
    path = conversation_dir(conv_id) / "meta.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_conversation_meta(conv_id: str, meta: dict) -> None:
    _atomic_write_json(conversation_dir(conv_id) / "meta.json", meta)


# ============================================================
# Messages 追加 / 读取
# ============================================================

def _get_conv_seq_lock(conv_id: str) -> threading.Lock:
    with _infra_lock:
        if conv_id not in _conv_seq_locks:
            _conv_seq_locks[conv_id] = threading.Lock()
        return _conv_seq_locks[conv_id]


def _next_conv_seq(conv_id: str) -> int:
    """必须在 _get_conv_seq_lock 内调用。"""
    if conv_id not in _conv_seq_counters:
        path = conversation_dir(conv_id) / "messages.jsonl"
        _conv_seq_counters[conv_id] = _count_lines(path)
    _conv_seq_counters[conv_id] += 1
    return _conv_seq_counters[conv_id]


def append_conv_message(conv_id: str, record: dict) -> int:
    """
    追加一条消息到 messages.jsonl，分配单调递增 seq，触发 SSE 通知。

    同步更新 meta 的 last_active_ts 与 message_count（best-effort）。
    返回分配的 seq 号。
    """
    d = conversation_dir(conv_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "messages.jsonl"
    lock = _get_conv_seq_lock(conv_id)
    with lock:
        seq = _next_conv_seq(conv_id)
        line = json.dumps({"seq": seq, "ts": _time.time(), **record}, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # 更新 meta（best-effort，失败不影响消息写入）
    try:
        meta = load_conversation_meta(conv_id)
        if meta is not None:
            meta["last_active_ts"] = _time.time()
            meta["message_count"] = seq
            save_conversation_meta(conv_id, meta)
    except Exception:
        pass

    # 通知 SSE 订阅者（非阻塞）
    try:
        get_conv_notify(conv_id).set()
    except Exception:
        pass

    return seq


def load_conv_messages(conv_id: str) -> list[dict]:
    """加载全部消息（含 seq 字段）。"""
    path = conversation_dir(conv_id) / "messages.jsonl"
    if not path.is_file():
        return []
    msgs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msgs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return msgs


def load_conv_messages_after(conv_id: str, after_seq: int) -> list[dict]:
    """加载 seq > after_seq 的消息。用于 SSE 增量。"""
    return [m for m in load_conv_messages(conv_id) if m.get("seq", 0) > after_seq]


# ============================================================
# 列表
# ============================================================

def list_conversations(baby_id: Optional[str] = None) -> list[dict]:
    """
    列出所有会话 meta。可按 baby_id 过滤（仅返回该 baby 参与的）。
    按 last_active_ts 倒序排列。
    """
    if baby_id is not None:
        _validate_baby_id(baby_id)
    if not _CONV_ROOT.is_dir():
        return []
    out = []
    for d in sorted(_CONV_ROOT.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if baby_id is not None and baby_id not in meta.get("participants", []):
            continue
        out.append(meta)
    out.sort(key=lambda m: m.get("last_active_ts", 0), reverse=True)
    return out


# ============================================================
# SSE notify / 会话锁
# ============================================================

def get_conv_notify(conv_id: str) -> asyncio.Event:
    """获取会话的 SSE 通知信号（惰性创建）。"""
    validate_conv_id(conv_id)
    with _infra_lock:
        if conv_id not in _conv_notify:
            _conv_notify[conv_id] = asyncio.Event()
        return _conv_notify[conv_id]


def get_conv_lock(conv_id: str) -> asyncio.Lock:
    """获取会话的异步锁（防 round-robin 并发撞车）。"""
    validate_conv_id(conv_id)
    with _infra_lock:
        if conv_id not in _conv_locks:
            _conv_locks[conv_id] = asyncio.Lock()
        return _conv_locks[conv_id]
