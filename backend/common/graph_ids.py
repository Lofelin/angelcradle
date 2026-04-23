"""
跨图共享的图节点 raw_id 常量。

[INPUT]: 无（纯常量定义）
[OUTPUT]: BABY_SELF_RAW_ID / BABY_RAW_ID(idx) / UUID_NAMESPACE_STR
[POS]: backend/common/ 的低层约定，被 womb/graph_emit.py 与 cradle/graph_emit.py 共同引用
[PROTOCOL]: 变更时更新此头部，然后检查 backend/CLAUDE.md（若存在）与相关 L2

设计目的
========
womb 图与 cradle 图共享同一个 baby_this 节点（UUIDv5 字节相同），两张图可在前端天然
按 id 合并。其技术前提是：**两侧使用完全相同的 raw_id 拼写 + 完全相同的 UUID namespace**。

任何一侧把 "baby_this" 拼成 "self_baby" 或换 namespace，跨图一致性立刻崩塌，
而且不会在运行时报错（只会默默渲染成两个孤立节点）。所以把拼写冻结为常量是
唯一能被 import / grep / 单测强制的防线。

本期 womb 端仍在 backend/womb/graph_emit.py:101 硬编码 "baby_this"。为避免扩大
当前变更范围（add-cradle-growth-graph 批次 1 只做契约层），**cradle 端以本文件
为权威**，womb 端视为"历史同值"，由 tests/test_cradle_graph_emit.py::
test_baby_id_cross_graph_consistency 守门两侧字节一致。下次变更 womb 图时顺手把
硬编码替换为 from common.graph_ids import BABY_SELF_RAW_ID。
"""

from __future__ import annotations

# ============================================================
# UUIDv5 固定 namespace —— womb 与 cradle 必须使用同一值
# ============================================================
# 使用 RFC4122 DNS namespace 作为项目稳定 ns，与 womb/graph_emit.py 保持字节一致。
# 不要在任何其他地方重新定义此值；需要时 import 此常量。
UUID_NAMESPACE_STR: str = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


# ============================================================
# Baby 节点 raw_id（跨图 continuant 延续的关键）
# ============================================================

# 单胎场景的 self 节点 raw_id。womb/graph_emit.py node_baby 当前硬编码同值。
BABY_SELF_RAW_ID: str = "baby_this"


def baby_raw_id(fetus_index: int | None = None) -> str:
    """返回 baby 节点的 raw_id。

    - fetus_index is None 或 0：返回 BABY_SELF_RAW_ID（单胎场景）
    - fetus_index >= 1：返回 f"baby_f{fetus_index}"（多胎场景，对齐 womb design §8.1）

    多胎在本批次（add-cradle-growth-graph 批次 1）不做深度支持，但保留 API
    以免未来新增时重新定义常量导致 UUID 漂移。
    """
    if fetus_index is None or fetus_index == 0:
        return BABY_SELF_RAW_ID
    if fetus_index < 0:
        raise ValueError(f"fetus_index must be >= 0, got {fetus_index}")
    return f"baby_f{fetus_index}"
