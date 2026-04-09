"""
向后兼容层：re-export stages.py 和 llm.py 的公开接口。

原 genetics.py (961行) 已拆分为：
  - womb/prompts.py  — prompt 模板
  - womb/llm.py      — LLM 客户端和 JSON 解析
  - womb/stages.py   — 发育编排逻辑

所有原有 import 路径（from womb.genetics import ...）继续有效。

[INPUT]: 无直接输入
[OUTPUT]: re-export express, express_stream, build_stage_prompts, 常量等
[POS]: womb/ 的向后兼容薄层
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

# 发育引擎
from .stages import (  # noqa: F401
    express,
    express_stream,
    build_stage_prompts,
    STAGE_NAMES,
    STAGE_DURATIONS,
    RESOURCE_BUDGET,
    SPECIES_DIR,
)

# LLM 基础设施
from .llm import (  # noqa: F401
    PROVIDERS,
    _create_client,
    _call_llm,
    _parse_json,
    _get_model,
)
