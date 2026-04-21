"""
孕育会话存储：让 /conceive/stream 从"请求生命周期"解耦到"后台任务 + 可订阅缓冲"。

[INPUT]: asyncio, 由 conceive.py 填充事件
[OUTPUT]: ConceptionSession, create(), get(); 支持断线重连与事件回放
[POS]: api/ 层的内存会话管理器，被 conceive.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

import asyncio
import time
import uuid
from typing import Any, AsyncIterator, Optional

# 完成/失败的会话在内存里保留多久（秒），过期后由下一次 create() 顺手清理
SESSION_TTL = 600


class ConceptionSession:
    """一次孕育的生命周期：后台线程追加事件，异步订阅者回放并尾随。"""

    def __init__(self, params: dict):
        self.id: str = uuid.uuid4().hex[:12]
        self.params: dict = params
        self.events: list[dict] = []
        self.status: str = "running"  # running | complete | error
        self.error: Optional[str] = None
        self.started_at: float = time.time()
        self.finished_at: Optional[float] = None
        self.loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._waiters: set[asyncio.Event] = set()
        self.task: Optional[asyncio.Task] = None

    # ── 线程侧入口：由 asyncio.to_thread 内部调用 ──
    def append_from_thread(self, ev: dict) -> None:
        self.loop.call_soon_threadsafe(self._append_on_loop, ev)

    def finalize_from_thread(self, status: str, error: Optional[str] = None) -> None:
        self.loop.call_soon_threadsafe(self._finalize_on_loop, status, error)

    # ── 事件循环侧：状态变更与唤醒 ──
    def _append_on_loop(self, ev: dict) -> None:
        self.events.append(ev)
        self._wake_waiters()

    def _finalize_on_loop(self, status: str, error: Optional[str]) -> None:
        if self.status == "running":
            self.status = status
            self.error = error
            self.finished_at = time.time()
        self._wake_waiters()

    def _wake_waiters(self) -> None:
        for w in self._waiters:
            w.set()

    async def subscribe(self) -> AsyncIterator[dict]:
        """从头回放所有缓冲事件，然后尾随新事件直到会话结束。"""
        idx = 0
        waiter = asyncio.Event()
        self._waiters.add(waiter)
        try:
            while True:
                while idx < len(self.events):
                    yield self.events[idx]
                    idx += 1
                if self.status != "running":
                    return
                waiter.clear()
                await waiter.wait()
        finally:
            self._waiters.discard(waiter)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "error": self.error,
            "event_count": len(self.events),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_sessions: dict[str, ConceptionSession] = {}


def create(params: dict) -> ConceptionSession:
    _sweep()
    session = ConceptionSession(params)
    _sessions[session.id] = session
    return session


def get(session_id: str) -> Optional[ConceptionSession]:
    return _sessions.get(session_id)


def _sweep() -> None:
    """清理过期的已完成会话，避免内存无限增长。"""
    now = time.time()
    stale = [
        sid for sid, s in _sessions.items()
        if s.status != "running" and s.finished_at and (now - s.finished_at) > SESSION_TTL
    ]
    for sid in stale:
        _sessions.pop(sid, None)
