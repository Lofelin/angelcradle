"""摇篮图 caregiver 自举回归测试 (2026-04-23 修复)。

AC-20260422-44207 归档 state.json 里 caregivers={} 空字典，导致
emit_caregivers_from_state 迭代空字典 → 0 个 caregiver 节点 / 0 条
CARED_BY/ATTACHES_TO 边 → baby_this 入度只有 10（样本 27）。

根因：cradle.__init__.admit_stream 构造 BabyState 时未塞 caregivers，且
state.from_dict 仅在老 archive 含 parent_profile 时兜底。

修复：
1. admit_stream 构造时显式塞 primary_parent CaregiverProfile
2. from_dict 在 caregivers 空 + 无 parent_profile 时也兜底补 primary_parent

本测试守护两条回归路径，以及下游 emit_caregivers_from_state 的产出契约。

[INPUT]: cradle.state / scheduler.graph_hooks
[OUTPUT]: pytest 3 cases
[POS]: backend/scripts/
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许以 backend 根目录作为 python path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cradle.state import BabyState, CaregiverProfile


def test_babystate_from_dict_bootstraps_primary_parent_when_empty() -> None:
    """老 archive (AC-20260422-44207) caregivers={} 无 parent_profile → 兜底 primary_parent."""
    d = {
        "baby_id": "TEST-old-archive",
        "species": "human",
        "caregivers": {},  # 空字典模拟故障归档
        "attachment_per_caregiver": {},
    }
    state = BabyState.from_dict(d)
    assert "primary_parent" in state.caregivers, "from_dict 应兜底补 primary_parent"
    assert state.caregivers["primary_parent"].caregiver_id == "primary_parent"
    assert state.attachment_per_caregiver.get("primary_parent") == "forming", (
        "attachment_per_caregiver 应同步补 forming 初始值"
    )


def test_babystate_from_dict_respects_existing_caregivers() -> None:
    """已有 caregivers 时不覆盖；仅补齐缺失的 attachment 初始值。"""
    d = {
        "baby_id": "TEST-with-cg",
        "species": "human",
        "caregivers": {
            "mother": CaregiverProfile(
                caregiver_id="mother", role="mother", display_name="Mom",
            ).to_dict(),
        },
        "attachment_per_caregiver": {"mother": "secure"},
    }
    state = BabyState.from_dict(d)
    assert set(state.caregivers.keys()) == {"mother"}
    assert state.attachment_per_caregiver == {"mother": "secure"}


def test_emit_caregivers_produces_node_and_edges() -> None:
    """修复后 emit_caregivers_from_state 产出 1 个节点 + CARED_BY。

    attachment state ∈ {secure, anxious, avoidant} 时额外产出 ATTACHES_TO。
    """
    from scheduler.graph_hooks import emit_caregivers_from_state

    state = BabyState(
        baby_id="TEST-emit",
        species="human",
        caregivers={"primary_parent": CaregiverProfile()},
        attachment_per_caregiver={"primary_parent": "forming"},
    )
    delta = emit_caregivers_from_state(state, 0)
    nodes = delta.get("add_nodes", [])
    edges = delta.get("add_edges", [])
    assert len(nodes) == 1, "默认一个 caregiver → 1 个节点"
    assert nodes[0].get("group") == "caregiver"
    edge_types = [e.get("type") for e in edges]
    assert "CARED_BY" in edge_types
    # forming 状态不该 emit ATTACHES_TO
    assert "ATTACHES_TO" not in edge_types

    # 切换到 secure 后应该 emit ATTACHES_TO
    state.attachment_per_caregiver["primary_parent"] = "secure"
    delta2 = emit_caregivers_from_state(state, 2)
    edge_types2 = [e.get("type") for e in delta2.get("add_edges", [])]
    assert "CARED_BY" in edge_types2
    assert "ATTACHES_TO" in edge_types2
