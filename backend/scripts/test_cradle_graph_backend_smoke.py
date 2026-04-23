"""
摇篮图谱 Phase D 后端端到端 smoke 测试。

直接调 scheduler/graph_hooks 的各 emit_* 函数，模拟一次完整摇篮期
（12 阶段 + 能力解锁 + 里程碑 + 压力回退/恢复 + 命名 critical + 终局）产出的
累积图谱，断言满足 spec 成功标准。

不跑真正 DES 主循环 / LLM 调用——那是 Gate 3 的浏览器端到端验证的范围。本
脚本只保证："hook 函数组合正确、图最终形态符合 spec、反向测试（时间节点/
OCCURS_IN 越界/UUID 冲突）全部过关"。

运行: python backend/scripts/test_cradle_graph_backend_smoke.py
"""

from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")


class _MockStress:
    stress_level = 0.4


class _MockIdentity:
    species = "human"


class _MockCaregiverProfile:
    def __init__(self, cid, role, display, resp):
        self.caregiver_id = cid
        self.role = role
        self.display_name = display
        self.responsiveness = resp


class _MockState:
    """尽量贴合 BabyState 的最小子集——只覆盖 graph_hooks 所需字段。"""

    def __init__(self, baby_id="AC-SMOKE-TEST"):
        self.baby_id = baby_id
        self.sex = "female"
        self.sim_time = 0.0
        self.current_phase = 0
        self.age_days = 0
        self.identity = _MockIdentity()
        self.stress = _MockStress()
        self.caregivers = {
            "mother":  _MockCaregiverProfile("mother", "mother", "Mother", 0.9),
            "father":  _MockCaregiverProfile("father", "father", "Father", 0.7),
            "granny":  _MockCaregiverProfile("granny", "grandparent", "Granny", 0.6),
        }
        self.attachment_per_caregiver = {
            "mother": "secure", "father": "secure", "granny": "anxious",
        }


def main() -> int:
    from cradle import graph_session
    from scheduler import graph_hooks
    from cradle import graph_emit as ge

    baby_id = "AC-SMOKE-TEST"
    graph_session.dispose()

    state = _MockState(baby_id)

    # ==== 模拟一次完整摇篮期 ====

    # phase_start phase=0 (首次: bootstrap + caregivers + progression)
    graph_hooks.ensure_bootstrap(baby_id, state)
    d0 = ge.merge_deltas(
        graph_hooks.emit_caregivers_from_state(state, 0),
        graph_hooks.emit_phase_start(state, 0),
    )
    graph_hooks.apply_and_attach(baby_id, d0)

    # phase 1-11 的 progression
    for p in range(1, 12):
        state.current_phase = p
        graph_hooks.apply_and_attach(baby_id, graph_hooks.emit_phase_start(state, p))

    # 每阶段解锁 2 个 capability
    capability_schedule = [
        (0, ["sucking_reflex", "crying"]),
        (1, ["social_smile", "visual_tracking"]),
        (2, ["grasping", "rolling"]),
        (3, ["object_permanence", "stranger_anxiety"]),
        (4, ["crawling", "first_words"]),
        (5, ["walking", "tool_use"]),
        (6, ["pretend_play", "self_recognition"]),
        (7, ["why_questions", "emotional_storms"]),
        (8, ["moral_sense", "peer_awareness"]),
        (9, ["rule_following", "basic_empathy"]),
        (10, ["time_concept", "analogy"]),
        (11, ["self_advocacy", "complex_emotion"]),
    ]
    for p, caps in capability_schedule:
        graph_hooks.apply_and_attach(
            baby_id, graph_hooks.emit_capabilities_unlocked(state, p, caps),
        )

    # 里程碑（模拟 _check_milestones 输出: 带 name 字段的对象）
    class _M:
        def __init__(self, name): self.name = name
        def to_dict(self): return {"name": self.name}

    graph_hooks.apply_and_attach(baby_id, graph_hooks.emit_milestones(state, 4, [_M("first_word")]))
    graph_hooks.apply_and_attach(baby_id, graph_hooks.emit_milestones(state, 5, [_M("first_steps")]))
    graph_hooks.apply_and_attach(baby_id, graph_hooks.emit_milestones(state, 6, [_M("naming")]))

    # 压力回退 + 恢复
    graph_hooks.apply_and_attach(baby_id, graph_hooks.emit_regression(state, 7, ["walking"]))
    graph_hooks.apply_and_attach(baby_id, graph_hooks.emit_recovery(state, 8,
        [{"capability": "walking", "strengthened": True, "care_from": "caregiver_mother"}]))

    # 每阶段 narrative
    for p in range(12):
        graph_hooks.apply_and_attach(
            baby_id, graph_hooks.emit_phase_completed(state, p, f"Phase {p} summary text."),
        )

    # 模拟多阶段的 caregiver 介入（真实 DES 会通过 intervene 端点累积多条 CARED_BY）
    for p in [2, 4, 6, 8, 10]:
        graph_hooks.apply_and_attach(baby_id, ge.delta_add(edges=[
            ge.edge_cared_by("mother", phase_index=p, quality=0.85,
                             description=f"mother care @ phase {p}"),
        ]))
    # 父亲在语言期前后介入
    for p in [5, 7, 11]:
        graph_hooks.apply_and_attach(baby_id, ge.delta_add(edges=[
            ge.edge_cared_by("father", phase_index=p, quality=0.75,
                             description=f"father care @ phase {p}"),
        ]))

    # cradle_complete
    graph_hooks.apply_and_attach(baby_id, graph_hooks.emit_cradle_complete(state, 11, cause="world_ready"))

    # ==== 拉快照做 Gate 断言 ====
    snap = graph_session.snapshot_for_endpoint(
        baby_id, species="human", sex="female",
        status="world_ready", phases_completed=12,
    )
    nodes = snap["nodes"]
    edges = snap["edges"]
    raw_of = {n["id"]: n["metadata"].get("raw_id") for n in nodes}
    stats = snap["stats"]

    def _ok(cond, msg):
        if not cond:
            print(f"  ❌ {msg}")
            raise AssertionError(msg)
        print(f"  ✓ {msg}")

    print(f"node_count={stats['node_count']}  edge_count={stats['edge_count']}")
    print(f"by_group={stats['by_group']}")
    print(f"degree_top_5={stats['degree_top_5']}")
    print()

    # Gate A: 规模
    print("== Gate A: 图规模 ==")
    _ok(80 <= stats["node_count"] <= 200, f"nodes ∈ [80,200]: {stats['node_count']}")
    _ok(stats["edge_count"] >= 120, f"edges ≥ 120: {stats['edge_count']}")

    # Gate B: progression/dimension/phase 结构
    print("== Gate B: 结构 ==")
    _ok(stats["by_group"].get("progression") == 12, "12 progression")
    _ok(stats["by_group"].get("dimension") == 6, "6 dimension")
    _ok(stats["by_group"].get("phase") == 31, "31 phase (per-dim)")
    _ok(stats["by_group"].get("caregiver") == 3, f"3 caregiver: {stats['by_group'].get('caregiver')}")

    # Gate C: 所有 phase 节点 BELONGS_TO dim
    phase_ids = {n["id"] for n in nodes if n["group"] == "phase"}
    belongs_srcs = {e["source"] for e in edges if e["type"] == "BELONGS_TO"}
    missing = phase_ids - belongs_srcs
    _ok(not missing, f"all phase nodes BELONGS_TO dim (missing={len(missing)})")

    # Gate D: OCCURS_IN 100% 指向 phase（不指向 progression）
    occurs_bad = []
    for e in edges:
        if e["type"] != "OCCURS_IN":
            continue
        tgt_raw = raw_of.get(e["target"], "")
        if not tgt_raw.startswith("phase:"):
            occurs_bad.append(tgt_raw)
    _ok(not occurs_bad, f"all OCCURS_IN → phase (violators={occurs_bad})")

    # Gate E: baby_this top-1 degree ≥ 30
    top = stats["degree_top_5"][0]
    _ok(top["raw_id"] == "baby_this", f"top-1 is baby_this, got {top['raw_id']}")
    _ok(top["total"] >= 30, f"baby_this degree ≥ 30: {top['total']}")

    # Gate F: 无时间节点
    bad_time = [r for r in raw_of.values() if r and re.match(r"^(stage_|day_|phase_x_day_)", r)]
    _ok(not bad_time, f"no time-entity nodes (violators={bad_time})")

    # Gate G: 所有 UUID 合法 RFC4122 v5 格式
    invalid_ids = [nid for nid in raw_of if not _UUID_RE.match(nid)]
    _ok(not invalid_ids, f"all node ids are UUIDv5 ({len(invalid_ids)} invalid)")
    invalid_edge_uuids = [e["uuid"] for e in edges if not _UUID_RE.match(e["uuid"])]
    _ok(not invalid_edge_uuids, f"all edge uuids are UUIDv5")

    # Gate H: 能力回退 + 恢复双向
    reg_edges = [e for e in edges if e["type"] == "REGRESSES"]
    rec_edges = [e for e in edges if e["type"] == "RECOVERS"]
    _ok(len(reg_edges) >= 1 and len(rec_edges) >= 1,
        f"regress+recover both present: REGRESSES={len(reg_edges)}, RECOVERS={len(rec_edges)}")

    # Gate I: NEXT 链接 11 个相邻 progression
    next_edges = [e for e in edges if e["type"] == "NEXT"]
    _ok(len(next_edges) == 11, f"11 NEXT edges (got {len(next_edges)})")

    # Gate J: 终局 TerminatedBy
    term = [e for e in edges if e["type"] == "TerminatedBy"]
    _ok(len(term) >= 1, f"TerminatedBy present (cause=world_ready): {len(term)}")

    # Gate K: 跨图 UUID 一致
    from womb.graph_emit import make_node_uuid as womb_uuid
    baby_uuid = [n["id"] for n in nodes if n["metadata"].get("raw_id") == "baby_this"][0]
    _ok(baby_uuid == womb_uuid("baby_this"),
        f"baby_this UUID byte-equal across womb/cradle")

    # Gate L: mother 节点 degree 是全图 top 之一
    mother_row = next((row for row in stats["degree_top_5"]
                       if row["raw_id"] == "caregiver_mother"), None)
    _ok(mother_row is not None,
        f"caregiver_mother in top-5 degree")

    print()
    print(f"=== Phase D backend smoke: ALL {12} Gates PASSED ===")
    print()
    print("Reminder: Gate 3 (browser visual validation) remains for USER to complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
