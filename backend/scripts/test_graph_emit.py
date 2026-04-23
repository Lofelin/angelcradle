"""
graph_emit.py 自检脚本——用 assert 验证节点/边 schema / uuid 幂等 / delta 合并幂等。

运行方式:
    python backend/scripts/test_graph_emit.py

[INPUT]: 无
[OUTPUT]: stdout 打印各 case 结果, 全部通过则 exit 0, 任一失败 exit 1
[POS]: backend/scripts/ 的子宫图谱帮手自检, 对应 add-womb-conception-graph 任务 2.6
[PROTOCOL]: 变更时更新此头部, 然后检查 CLAUDE.md
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)  # 让 graph_emit 的 `from common.graph_ids import ...` 可解析
_GE_PATH = os.path.normpath(os.path.join(_HERE, "..", "womb", "graph_emit.py"))
_spec = importlib.util.spec_from_file_location("graph_emit", _GE_PATH)
ge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ge)  # type: ignore


_STD_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")
_EDGE_UUID_RE = _STD_UUID_RE
_NODE_UUID_RE = _STD_UUID_RE
_UUID_RE = _STD_UUID_RE


def _check(cond: bool, msg: str):
    if not cond:
        print(f"  ❌ {msg}")
        raise AssertionError(msg)
    print(f"  ✓ {msg}")


def test_node_constructors():
    print("[1] Node constructors")
    baby = ge.node_baby("baby_sz_001", sex="female")
    _check(_NODE_UUID_RE.match(baby["id"]) is not None, f"baby id 是 node UUID ({baby['id']})")
    _check(baby["metadata"]["raw_id"] == "baby_this", "baby metadata.raw_id 保留可读 raw")
    _check(baby["group"] == "identity", "baby group=identity")
    _check(baby["continuant_id"] == "baby_sz_001", "baby continuant_id 绑定 baby_id")

    h = ge.node_hormone("cortisol", narrative_zh="皮质醇", baseline=1.0)
    _check(_NODE_UUID_RE.match(h["id"]) is not None, f"hormone id 是 node UUID ({h['id']})")
    _check(h["metadata"]["raw_id"] == "hormone_cortisol", "hormone raw_id=hormone_cortisol")
    _check(h["continuant_id"] == "cortisol", "hormone continuant_id")
    _check(h["metadata"]["baseline"] == 1.0, "hormone baseline 进 metadata")

    brain = ge.node_organ("brain", formation_stage=2, maturation_stage=5, neural=True)
    _check(brain["group"] == "neural_behavior", "brain 通过 neural=True 放入 neural_behavior 组")
    _check(brain["metadata"]["formation_stage"] == 2, "organ formation_stage")

    evt = ge.node_event("defect_roll", stage_index=2, result="minor_heart_murmur")
    _check(_NODE_UUID_RE.match(evt["id"]) is not None, f"event id 是 node UUID ({evt['id']})")
    _check(evt["metadata"]["raw_id"] == "event_defect_roll_s2", "event raw_id 带 stage 后缀")
    _check(evt["metadata"]["stage_index"] == 2, "event stage_index 进 metadata")


def test_uuid_format():
    print("[2] UUID format + determinism")
    u1 = ge.make_edge_uuid("hormone_cortisol", "organ_heart", "MODULATES", 2, "皮质醇轻度抑制心肌分化")
    u2 = ge.make_edge_uuid("hormone_cortisol", "organ_heart", "MODULATES", 2, "皮质醇轻度抑制心肌分化")
    _check(_UUID_RE.match(u1) is not None, f"uuid 格式 ^e_[0-9a-f]{{10}}$ ({u1})")
    _check(u1 == u2, "同内容 uuid 可复现（幂等）")

    u3 = ge.make_edge_uuid("hormone_cortisol", "organ_heart", "MODULATES", 4, "持续皮质醇损伤心律调节")
    _check(u1 != u3, "不同 stage_index → 不同 uuid（多重边不碰撞）")

    u4 = ge.make_edge_uuid("species_human", "baby_this", "EXPRESSES_AS")
    _check(_UUID_RE.match(u4) is not None, "结构性边（无 stage_index）uuid 仍合规")


def test_uuid_no_semantic():
    print("[3] UUID 无语义泄漏")
    u = ge.make_edge_uuid("hormone_cortisol", "organ_heart", "MODULATES", 2, "X")
    for forbidden in ("MODULATES", "hormone_cortisol", "organ_heart", "->", ":s2", "s2"):
        _check(forbidden not in u, f"uuid 不包含 '{forbidden}'")


def test_edge_constructor():
    print("[4] Edge constructor")
    e = ge.edge(
        "hormone_cortisol", "organ_heart", "MODULATES",
        stage_index=2, weight=0.4, level_at=1.3, polarity="negative",
        description="皮质醇轻度抑制心肌分化",
    )
    _check(_EDGE_UUID_RE.match(e["uuid"]) is not None, "edge.uuid 合规")
    _check(_NODE_UUID_RE.match(e["source"]) is not None, f"edge.source 是 node UUID ({e['source']})")
    _check(_NODE_UUID_RE.match(e["target"]) is not None, f"edge.target 是 node UUID ({e['target']})")
    # 与 node_hormone('cortisol').id 一致, 确认引用对齐
    cortisol_node = ge.node_hormone("cortisol")
    heart_node = ge.node_organ("heart")
    _check(e["source"] == cortisol_node["id"], "edge.source == node_hormone('cortisol').id (引用对齐)")
    _check(e["target"] == heart_node["id"], "edge.target == node_organ('heart').id (引用对齐)")
    _check(e["stage_index"] == 2, "stage_index 独立字段")
    _check(e["weight"] == 0.4, "weight 独立字段")
    _check(e["level_at"] == 1.3, "业务 extra 字段进边")
    _check(e["polarity"] == "negative", "业务 extra 字段 polarity 进边")

    e2 = ge.edge("species_human", "baby_this", "EXPRESSES_AS", weight=1.0)
    _check("stage_index" not in e2, "无 stage_index 时边不含该字段")


def test_delta_merge():
    print("[5] Delta merge")
    d1 = ge.delta_add(nodes=[ge.node_baby("b1")], edges=[])
    d2 = ge.delta_add(
        nodes=[ge.node_species("human")],
        edges=[ge.edge("species_human", "baby_this", "EXPRESSES_AS", weight=1.0)],
    )
    d3 = ge.delta_update(nodes=[ge.track_append("hormone_cortisol", stage_index=2, level=1.3)])
    d4 = ge.delta_remove(edge_uuids=["e_deadbeef01"])

    merged = ge.merge_deltas(d1, d2, d3, d4, {})  # 空 delta 不影响
    _check(len(merged["add_nodes"]) == 2, "merge 后 add_nodes 聚合")
    _check(len(merged["add_edges"]) == 1, "merge 后 add_edges 聚合")
    _check(len(merged["update_nodes"]) == 1, "merge 后 update_nodes 聚合")
    _check(len(merged["remove_edges"]) == 1, "merge 后 remove_edges 聚合")
    _check("remove_nodes" not in merged, "空列表字段清理")


def test_track_append():
    print("[6] track_append patch 形态")
    p = ge.track_append("hormone_cortisol", stage_index=2, level=1.3, budget_penalty=-8)
    cortisol_node = ge.node_hormone("cortisol")
    _check(p["id"] == cortisol_node["id"], "track_append id 是 UUID 且指向 cortisol 节点")
    _check(_NODE_UUID_RE.match(p["id"]) is not None, "track_append id 格式合规")
    ta = p["metadata"]["track_append"]
    _check(ta["stage_index"] == 2 and ta["level"] == 1.3, "track_append 样本点字段齐全")


def main():
    cases = [
        test_node_constructors,
        test_uuid_format,
        test_uuid_no_semantic,
        test_edge_constructor,
        test_delta_merge,
        test_track_append,
    ]
    for c in cases:
        c()
    print("\nAll graph_emit self-checks passed ✓")


if __name__ == "__main__":
    main()
