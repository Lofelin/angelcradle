"""
cradle/graph_emit.py + ontology.py + graph_story.py 自检脚本。

运行方式:
    python backend/scripts/test_cradle_graph_emit.py

[INPUT]: 无
[OUTPUT]: stdout 逐 case 打印 ✓/❌，全部通过 exit 0，任一失败 AssertionError 抛出
[POS]: backend/scripts/ 的摇篮图谱帮手自检，对应 add-cradle-growth-graph 任务 2.15
[PROTOCOL]: 变更时更新此头部，然后检查 cradle/CLAUDE.md
"""

from __future__ import annotations

import os
import re
import sys

# 确保 backend/ 在 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from cradle import graph_emit as ge  # noqa: E402
from cradle import graph_story as gs  # noqa: E402
from cradle import ontology as onto  # noqa: E402
from womb.graph_emit import make_node_uuid as womb_make_node_uuid  # noqa: E402

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  ❌ {msg}")
        raise AssertionError(msg)
    print(f"  ✓ {msg}")


# ============================================================
# 1. 跨图 UUID 一致性（最重要的守门断言）
# ============================================================

def test_cross_graph_baby_uuid():
    print("== 1. cross-graph baby UUID consistency ==")
    cradle_uuid = ge.id_baby()
    womb_uuid = womb_make_node_uuid("baby_this")
    _check(cradle_uuid == womb_uuid,
           f"baby_this UUID must byte-equal across womb/cradle; "
           f"cradle={cradle_uuid} womb={womb_uuid}")
    _check(_UUID_RE.match(cradle_uuid) is not None, "cradle baby_this UUID is RFC4122 v5")


# ============================================================
# 2. 节点构造器 schema（id / label / group / metadata.raw_id 必备）
# ============================================================

def test_node_constructors_schema():
    print("== 2. node constructors schema ==")
    nodes = [
        ge.node_baby("AC-TEST-001", sex="female", species="human"),
        ge.node_caregiver("M001", "mother"),
        ge.node_progression("neonatal", 0, **gs.hydrate_progression("neonatal")),
        ge.node_dimension("motor", **gs.hydrate_dimension("motor")),
        ge.node_phase_dim("motor", "toddler", **gs.hydrate_phase_dim("motor", "toddler")),
        ge.node_capability("walking", unlocked_at_phase=5, **gs.hydrate_capability("walking")),
        ge.node_milestone("first_steps", "capability_unlock", 5, **gs.hydrate_milestone("first_steps")),
        ge.node_preference("music", category="audio", strength=0.6, acquired_at_phase=2),
        ge.node_fear("stranger", severity=0.7, acquired_at_phase=3),
        ge.node_comfort("blanket", acquired_at_phase=1),
        ge.node_temperament(dimensions={"openness": 0.6}, defined_at_phase=6),
        ge.node_need_type("hunger", **gs.hydrate_need("hunger")),
        ge.node_event("capability_unlock", 5, seq=0, result="walking"),
        ge.node_critical(6, 0, reason="naming", status="pending"),
        ge.node_regression("walking", 4, stress_level_at=0.8),
        ge.node_recovery("walking", 5, strengthened=True, care_from="caregiver_M001"),
        ge.node_conversation("dm:AC-TEST-001", "dm", participants=["AC-TEST-001"]),
        ge.node_narrative(3, summary="S3 summary..."),
    ]
    for n in nodes:
        _check("id" in n and _UUID_RE.match(n["id"]) is not None,
               f"node has valid UUID id: raw={n['metadata']['raw_id']}")
        _check("label" in n and isinstance(n["label"], str), f"node has label: {n['label']}")
        _check(n["group"] in ge.ALL_GROUPS, f"node group valid: {n['group']}")
        _check("raw_id" in n["metadata"], "metadata.raw_id preserved")

    _check(len(nodes) == 18, f"expected 18 node types tested, got {len(nodes)}")


# ============================================================
# 3. 节点构造器 validation（拒绝非法参数）
# ============================================================

def test_node_validation():
    print("== 3. node constructor validation ==")
    try:
        ge.node_caregiver("X", "chef")
        raise AssertionError("bad role should raise")
    except ValueError:
        _check(True, "bad caregiver role raises")
    try:
        ge.node_progression("neonatal", 99)
        raise AssertionError("out-of-range phase_index should raise")
    except ValueError:
        _check(True, "out-of-range progression phase_index raises")
    try:
        ge.node_dimension("superpowers")
        raise AssertionError("unknown dim should raise")
    except ValueError:
        _check(True, "unknown dimension raises")
    try:
        ge.node_phase_dim("motor", "FAKE_STAGE")
        raise AssertionError("unknown phase stage should raise")
    except ValueError:
        _check(True, "unknown phase stage raises")
    try:
        ge.node_need_type("hunger", urgency="cosmic")
        raise AssertionError("bad urgency should raise")
    except ValueError:
        _check(True, "bad need urgency raises")
    try:
        ge.node_critical(0, 0, status="weird")
        raise AssertionError("bad critical status should raise")
    except ValueError:
        _check(True, "bad critical status raises")
    try:
        ge.node_conversation("c1", "chatroom")
        raise AssertionError("bad conv kind should raise")
    except ValueError:
        _check(True, "bad conversation kind raises")


# ============================================================
# 4. edge_occurs_in 内置断言
# ============================================================

def test_edge_occurs_in_assertion():
    print("== 4. edge_occurs_in internal assertion ==")
    # 合法：per-dim phase
    e = ge.edge_occurs_in("capability_walking", "motor", "toddler", phase_index=5)
    _check(e["type"] == "OCCURS_IN", "valid OCCURS_IN edge constructed")

    # 非法：未知 stage（含 progression 伪造的 stage）
    try:
        ge.edge_occurs_in("capability_walking", "motor", "progression:neonatal")
        raise AssertionError("OCCURS_IN to non-phase should raise")
    except ValueError:
        _check(True, "OCCURS_IN to unknown stage raises")

    try:
        ge.edge_occurs_in("capability_walking", "nonexistent_dim", "toddler")
        raise AssertionError("OCCURS_IN to unknown dim should raise")
    except ValueError:
        _check(True, "OCCURS_IN to unknown dim raises")


# ============================================================
# 5. capability 自动路由
# ============================================================

def test_capability_autoroute():
    print("== 5. edge_capability_occurs_in auto-routing ==")
    # walking 在 motor 维度；phase_index=5 月龄 ~15 月，对应 motor:toddler
    e = ge.edge_capability_occurs_in("walking", phase_index=5)
    _check(e["type"] == "OCCURS_IN", "edge type OCCURS_IN")
    expect_target = ge.make_node_uuid("phase:motor:toddler")
    _check(e["target"] == expect_target,
           f"walking routed to phase:motor:toddler (target matches uuid)")

    # object_permanence 在 cognitive；phase_index=3 月龄 7.5 月，对应 cognitive:primary_circular
    e2 = ge.edge_capability_occurs_in("object_permanence", phase_index=3)
    expect2 = ge.make_node_uuid("phase:cognitive:primary_circular")
    _check(e2["target"] == expect2, "object_permanence routed to cognitive:primary_circular")


# ============================================================
# 6. 多重边 uuid 唯一性
# ============================================================

def test_multi_edge_distinct_uuids():
    print("== 6. multi-edge uuids distinct ==")
    e_p2 = ge.edge_cared_by("M001", phase_index=2, quality=0.9)
    e_p4 = ge.edge_cared_by("M001", phase_index=4, quality=0.7)
    e_p6 = ge.edge_cared_by("M001", phase_index=6, quality=0.8)
    uuids = {e_p2["uuid"], e_p4["uuid"], e_p6["uuid"]}
    _check(len(uuids) == 3, f"three distinct uuids, got {len(uuids)}")
    for e in (e_p2, e_p4, e_p6):
        _check(_UUID_RE.match(e["uuid"]) is not None, f"edge uuid is RFC4122 v5")
        _check(e["source"] == e_p2["source"], "same source across multi-edges")
        _check(e["target"] == e_p2["target"], "same target across multi-edges")

    # same (src, tgt, type, phase_index, description) must be idempotent
    e_same_a = ge.edge_cared_by("M001", phase_index=2, quality=0.9)
    e_same_b = ge.edge_cared_by("M001", phase_index=2, quality=0.1)  # quality 不进 uuid
    _check(e_same_a["uuid"] == e_same_b["uuid"],
           "same (src,tgt,type,phase_index,description) yields same uuid (quality not in hash)")


# ============================================================
# 7. edge validation
# ============================================================

def test_edge_validation():
    print("== 7. edge constructor validation ==")
    try:
        ge.edge_attaches_to("M001", 3, state="chaotic")
        raise AssertionError("bad attachment state should raise")
    except ValueError:
        _check(True, "bad attachment state raises")
    try:
        ge.edge_terminated_by("event:x:0:0", 5, cause="random")
        raise AssertionError("bad terminated cause should raise")
    except ValueError:
        _check(True, "bad terminated_by cause raises")


# ============================================================
# 8. bootstrap dimension/phase
# ============================================================

def test_bootstrap_dim_phase():
    print("== 8. bootstrap_dimension_phase_* ==")
    nodes = ge.bootstrap_dimension_phase_nodes()
    edges = ge.bootstrap_dimension_phase_edges()
    _check(len(nodes) == 6 + len(onto.KNOWN_PHASE_STAGES),
           f"bootstrap: 6 dim + {len(onto.KNOWN_PHASE_STAGES)} phase = {6 + len(onto.KNOWN_PHASE_STAGES)} nodes, got {len(nodes)}")
    _check(len(edges) == len(onto.KNOWN_PHASE_STAGES),
           f"bootstrap edges count == phase count {len(onto.KNOWN_PHASE_STAGES)}, got {len(edges)}")
    # 每个 phase 节点 100% 有 BELONGS_TO 出边
    phase_node_ids = {n["id"] for n in nodes if n["group"] == "phase"}
    belongs_srcs = {e["source"] for e in edges if e["type"] == "BELONGS_TO"}
    missing = phase_node_ids - belongs_srcs
    _check(not missing, f"all phase nodes have BELONGS_TO out-edge (missing={len(missing)})")

    # 每条 BELONGS_TO target 都是已知 dimension
    dim_ids = {ge.id_dimension(d) for d in onto.DIMENSIONS}
    for e in edges:
        _check(e["target"] in dim_ids,
               f"BELONGS_TO target is a real dimension (source={e['source'][:12]}...)")
    # Good—只验证第一个就够了，避免刷屏
    print(f"  … {len(edges)} BELONGS_TO edges verified (printed first only)")


# ============================================================
# 9. merge_deltas 幂等性
# ============================================================

def test_merge_deltas_idempotent():
    print("== 9. merge_deltas aggregation ==")
    d1 = ge.delta_add(nodes=[ge.node_baby("AC-T", sex="f")])
    d2 = ge.delta_add(edges=[ge.edge_cared_by("M001", phase_index=0, quality=1.0)])
    d3 = ge.delta_update(nodes=[ge.track_sample("baby_this", phase_index=0, stress=0.2)])
    merged = ge.merge_deltas(d1, d2, d3, {}, None)
    _check(len(merged["add_nodes"]) == 1, "add_nodes merged")
    _check(len(merged["add_edges"]) == 1, "add_edges merged")
    _check(len(merged["update_nodes"]) == 1, "update_nodes merged")
    _check("remove_nodes" not in merged, "empty keys cleaned")

    # merge 多次相同 delta 应该产生多份条目（不去重，这是业务逻辑）
    merged2 = ge.merge_deltas(d1, d1)
    _check(len(merged2["add_nodes"]) == 2,
           "merge_deltas doesn't dedupe; dedup is the reducer's job (apply_delta)")


# ============================================================
# 10. apply_delta reducer 行为
# ============================================================

def test_apply_delta_reducer():
    print("== 10. apply_delta reducer ==")
    state = ge.empty_state()

    # add 幂等
    baby = ge.node_baby("AC-T", sex="f")
    ge.apply_delta(state, ge.delta_add(nodes=[baby, baby]))
    _check(len(state["nodes"]) == 1, "add same node twice stays 1")

    # update_nodes 浅合并 + metadata 深合并
    ge.apply_delta(state, ge.delta_update(nodes=[{
        "id": ge.id_baby(),
        "metadata": {"custom": "X"},
    }]))
    cur_meta = state["nodes"][ge.id_baby()]["metadata"]
    _check(cur_meta.get("custom") == "X", "metadata shallow merge adds new key")
    _check(cur_meta.get("baby_id") == "AC-T", "metadata deep merge preserves pre-existing key")

    # track_append 累积
    for p in range(3):
        ge.apply_delta(state, ge.delta_update(
            nodes=[ge.track_sample("baby_this", phase_index=p, stress=0.1 * p)]))
    track = state["nodes"][ge.id_baby()]["metadata"]["track"]
    _check(len(track) == 3, f"track accumulates 3 samples, got {len(track)}")
    _check(track[-1]["phase_index"] == 2, "last track element is latest")

    # add_edges + remove_nodes 级联
    ge.apply_delta(state, ge.delta_add(
        nodes=[ge.node_caregiver("M001", "mother")],
        edges=[ge.edge_cared_by("M001", phase_index=0, quality=1.0)],
    ))
    mid = ge.id_caregiver("M001")
    _check(mid in state["nodes"], "caregiver added")
    _check(len(state["edges"]) == 1, "CARED_BY edge added")

    ge.apply_delta(state, ge.delta_remove(node_ids=[mid]))
    _check(mid not in state["nodes"], "caregiver removed")
    _check(len(state["edges"]) == 0, "orphan edge cascaded")

    # update_nodes 对不存在节点静默跳过（不创建）
    snap_before = len(state["nodes"])
    ge.apply_delta(state, ge.delta_update(
        nodes=[{"id": ge.make_node_uuid("ghost"), "metadata": {"x": 1}}]))
    _check(len(state["nodes"]) == snap_before, "update on missing node no-op (no creation)")


# ============================================================
# 11. ontology 覆盖与路由健康度
# ============================================================

def test_ontology_coverage():
    print("== 11. ontology coverage ==")
    _check(len(onto.DIMENSIONS) == 6, "6 dimensions")
    _check(24 <= len(onto.KNOWN_PHASE_STAGES) <= 32,
           f"per-dim phase count in [24, 32]: {len(onto.KNOWN_PHASE_STAGES)}")
    # 12 阶段映射无 raise
    for idx in range(12):
        for dim in onto.DIMENSIONS:
            stage = onto.current_phase_for(dim, idx)
            _check((dim, stage) in onto.KNOWN_PHASE_STAGES,
                   f"(p{idx}, {dim}) → known stage {stage}")
    # phases.py 已知 capability 全部在路由表里
    from cradle.phases import PHASES
    missing = []
    for p in PHASES:
        for cap in p.capabilities:
            if cap not in onto.CAPABILITY_DIMENSION_MAP:
                missing.append(cap)
    _check(not missing, f"all phases.PHASES capabilities routed: missing={missing}")


# ============================================================
# 12. state_to_snapshot 序列化
# ============================================================

def test_state_to_snapshot():
    print("== 12. state_to_snapshot ==")
    state = ge.empty_state()
    ge.apply_delta(state, ge.delta_add(
        nodes=ge.bootstrap_dimension_phase_nodes(),
        edges=ge.bootstrap_dimension_phase_edges(),
    ))
    snap = ge.state_to_snapshot(state)
    _check("nodes" in snap and "edges" in snap, "snapshot has nodes + edges")
    _check(isinstance(snap["nodes"], list) and isinstance(snap["edges"], list),
           "snapshot fields are lists")
    _check(len(snap["nodes"]) == 37, f"snapshot has 37 nodes (6 dim + 31 phase), got {len(snap['nodes'])}")
    _check(len(snap["edges"]) == 31, f"snapshot has 31 edges, got {len(snap['edges'])}")


# ============================================================
# main
# ============================================================

TESTS = [
    test_cross_graph_baby_uuid,
    test_node_constructors_schema,
    test_node_validation,
    test_edge_occurs_in_assertion,
    test_capability_autoroute,
    test_multi_edge_distinct_uuids,
    test_edge_validation,
    test_bootstrap_dim_phase,
    test_merge_deltas_idempotent,
    test_apply_delta_reducer,
    test_ontology_coverage,
    test_state_to_snapshot,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"*** FAIL: {fn.__name__}: {e}")
        print()
    total = len(TESTS)
    if failed:
        print(f"=== {failed}/{total} suites FAILED ===")
        return 1
    print(f"=== ALL {total} suites PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
