"""
向后兼容层：re-export 根级 llm.py 的接口。

实际实现在 backend/llm.py（全局共享）。
此文件保留下划线命名以兼容 womb 内部的现有 import。

[INPUT]: 无
[OUTPUT]: re-export _create_client, _call_llm, _parse_json, _get_model, PROVIDERS
[POS]: womb/ 的 LLM 兼容层
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from llm import (  # noqa: F401
    PROVIDERS,
    create_client as _create_client,
    call_llm as _call_llm,
    parse_json as _parse_json,
    get_model as _get_model,
)
