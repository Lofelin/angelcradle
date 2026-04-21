"""
LLM 调用持��化日志。

每次 LLM 请求的完整 prompt 和 response 以 JSONL 格式追加写入
archive/{baby_id}/llm_calls.jsonl，供调试和回溯。

[INPUT]: 由 llm/__init__.py 的 call_llm / call_llm_chat 在调用末尾触发
[OUTPUT]: persist_llm_call()
[POS]: llm/ 包的日志子模块
[PROTOCOL]: 变更时更新此头部，然后检查 llm/__init__.py
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_ARCHIVE_DIR = Path(os.environ.get("ARCHIVE_DIR", "archive"))
_write_lock = threading.Lock()


def persist_llm_call(
    metadata: dict,
    prompt_data: str | dict,
    response: str,
    provider: str,
    model: str,
    elapsed_sec: float,
    usage: str,
) -> None:
    """
    将一次 LLM 调用的 req/resp 追加写入 baby 的日���文件。

    metadata 必须包含 baby_id，可选 callsite / phase / extra。
    无 baby_id 时静默跳过（womb 阶段等场景）。
    """
    baby_id = metadata.get("baby_id")
    if not baby_id:
        return

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "callsite": metadata.get("callsite", "unknown"),
        "phase": metadata.get("phase"),
        "provider": provider,
        "model": model,
        "elapsed_s": round(elapsed_sec, 2),
        "usage": usage,
        "prompt": prompt_data,
        "response": response,
    }

    log_path = _ARCHIVE_DIR / baby_id / "llm_calls.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with _write_lock:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        logger.debug("LLM 日志写入失败: %s", log_path, exc_info=True)
