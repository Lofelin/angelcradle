"""
生成 frontend/src/data/cradle-growth-sample.json v1。

设计参考实现（design-as-code）：一个完整 human 摇篮期的图谱最终态。
主角 AC-20260421-36472 (female)，12 阶段完整走完并进入世界。

剧本要点:
  - 3 照护者: mother (全程) / father (间歇) / grandmother (3mo 起)
  - 1 次依附漂移: mother secure → anxious (P3) → secure (P4)
  - 1 次压力回退 + 恢复: walking 在 P7 regress、P8 recover (strengthened)
  - 1 次 critical_event: naming ceremony @ P6, resolved by father
  - 3 preference + 2 fear + 2 comfort + 1 temperament
  - 12 progression + 6 dimension + 31 per-dim phase + ~15 capability + ~6 milestone
  - narrative @ P0/P3/P6/P9/P11

运行:
    python backend/scripts/build_cradle_sample.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from cradle import graph_emit as ge  # noqa: E402
from cradle import graph_story as gs  # noqa: E402
from cradle.ontology import DIMENSIONS, capability_dimension, current_phase_for  # noqa: E402

BABY_ID = "AC-20260421-36472"


def build_state() -> dict:
    st = ge.empty_state()
    add = lambda nodes=None, edges=None: ge.apply_delta(st, ge.delta_add(nodes=nodes, edges=edges))
    upd = lambda nodes=None: ge.apply_delta(st, ge.delta_update(nodes=nodes))

    # ------------------------------------------------------------
    # 1. Bootstrap: 6 dimension + 31 per-dim phase + BELONGS_TO
    # ------------------------------------------------------------
    dim_meta_hydrated = {d: gs.hydrate_dimension(d) for d in DIMENSIONS}
    add(nodes=ge.bootstrap_dimension_phase_nodes(dim_meta=dim_meta_hydrated),
        edges=ge.bootstrap_dimension_phase_edges())

    # Phase nodes already created. Re-hydrate narratives:
    for dim, phases in [(d, [(s,) for s, *_ in []] ) for d in []]:  # placeholder
        pass

    # ------------------------------------------------------------
    # 2. Identity: baby + 3 caregivers
    # ------------------------------------------------------------
    add(nodes=[
        ge.node_baby(BABY_ID, sex="female", species="human", status="world_ready"),
        ge.node_caregiver("mother", "mother", display_name="Mother",
                          identity_traits=["patient", "attentive"],
                          narrative_zh="主照护者，全程陪伴，依附核心。",
                          narrative_en="Primary caregiver, full-time companion, attachment core."),
        ge.node_caregiver("father", "father", display_name="Father",
                          identity_traits=["playful", "protective"],
                          narrative_zh="间歇陪伴的父亲，命名仪式主导者。",
                          narrative_en="Intermittent father; leads naming ceremony."),
        ge.node_caregiver("grandmother", "grandparent", display_name="Grandmother",
                          identity_traits=["warm"],
                          narrative_zh="外婆，从 3 个月起间歇照护。",
                          narrative_en="Grandmother, intermittent from 3mo."),
    ])

    # ------------------------------------------------------------
    # 3. 12 Progressions + NEXT 串联
    # ------------------------------------------------------------
    progression_names = [
        "neonatal", "sensory_awakening", "body_discovery", "object_permanence",
        "locomotion", "first_word", "language_explosion", "why_phase",
        "social_budding", "rule_understanding", "abstract_beginning", "independence",
    ]
    prog_nodes = [
        ge.node_progression(name, idx, **gs.hydrate_progression(name))
        for idx, name in enumerate(progression_names)
    ]
    prog_edges = [
        ge.edge_next(progression_names[i], progression_names[i + 1])
        for i in range(11)
    ]
    add(nodes=prog_nodes, edges=prog_edges)

    # ------------------------------------------------------------
    # 4. 每阶段主要能力 + OCCURS_IN + UNLOCKS
    #    挑选每阶段 1-3 个关键 capability，不是全铺
    # ------------------------------------------------------------
    capability_schedule: list[tuple[int, list[str]]] = [
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
    for phase_idx, caps in capability_schedule:
        for cap_key in caps:
            cap_node = ge.node_capability(
                cap_key, unlocked_at_phase=phase_idx,
                **gs.hydrate_capability(cap_key),
            )
            event_raw = f"event:capability_unlock:{phase_idx}:{cap_key}"
            event_node = ge.node_event(
                "capability_unlock", phase_idx, seq=cap_key, result=cap_key,
            )
            add(nodes=[cap_node, event_node])
            add(edges=[
                ge.edge_capability_occurs_in(cap_key, phase_index=phase_idx),
                ge.edge_unlocks(
                    event_raw, cap_key, phase_index=phase_idx,
                    description=f"{cap_key} unlocked in phase {phase_idx}",
                ),
                # baby 经历每一次能力解锁——巩固 baby 作为拓扑中心
                ge.edge_experiences(event_raw, phase_idx,
                                    description=f"experienced {cap_key} unlock"),
            ])

    # ------------------------------------------------------------
    # 5. Milestones + ACHIEVES + OCCURS_IN
    # ------------------------------------------------------------
    milestones = [
        ("first_social_smile", "capability_unlock", 1, "social"),
        ("first_word", "capability_unlock", 4, "language"),
        ("first_steps", "capability_unlock", 5, "motor"),
        ("naming", "naming", 6, "social"),
        ("separation_success", "milestone", 8, "social"),
        ("toilet_trained", "milestone", 9, "physical"),
        ("capability_recovered", "capability_recovered", 8, "motor"),
        ("world_ready", "terminus", 11, "cognitive"),
    ]
    for slug, kind, phase_idx, dim in milestones:
        add(nodes=[
            ge.node_milestone(slug, kind, phase_idx, **gs.hydrate_milestone(slug)),
        ])
        add(edges=[
            ge.edge_achieves("baby_this", slug, phase_idx),
            ge.edge_milestone_occurs_in(slug, dim, phase_idx),
        ])

    # ------------------------------------------------------------
    # 6. Caregiver CARED_BY multi-edges (多重边核心 demo)
    # ------------------------------------------------------------
    care_schedule = [
        ("mother", 0, 0.95, "breastfeeding & swaddling"),
        ("mother", 1, 0.90, "gaze play & cooing response"),
        ("mother", 2, 0.88, "tummy time & hand play"),
        ("mother", 3, 0.92, "separation games & peekaboo"),
        ("mother", 4, 0.90, "walking practice"),
        ("mother", 5, 0.85, "word coaching"),
        ("mother", 7, 0.80, "tantrum containment"),
        ("mother", 9, 0.90, "rule co-creation"),
        ("mother", 11, 0.95, "pre-world emotional prep"),

        ("father", 1, 0.70, "evening bathing"),
        ("father", 4, 0.75, "rough play"),
        ("father", 6, 0.88, "naming ceremony"),
        ("father", 8, 0.80, "peer setup"),
        ("father", 11, 0.82, "debate coaching"),

        ("grandmother", 3, 0.65, "first visit after 3mo"),
        ("grandmother", 6, 0.72, "holiday stay"),
        ("grandmother", 9, 0.70, "weekend visits"),
    ]
    for cg_id, phase_idx, quality, desc in care_schedule:
        add(edges=[ge.edge_cared_by(cg_id, phase_index=phase_idx, quality=quality, description=desc)])

    # ------------------------------------------------------------
    # 7. ATTACHES_TO 多重边：依附漂移 secure → anxious → secure
    # ------------------------------------------------------------
    attachment_history = [
        ("mother", 1, "secure", 30, "初次依附形成"),
        ("mother", 3, "anxious", 200, "陌生人焦虑副作用波及主依附"),
        ("mother", 4, "secure", 290, "通过躲猫猫重建安全感"),
        ("mother", 9, "secure", 1500, "规则共建巩固依附"),
        ("father", 6, "secure", 600, "命名仪式建立父女依附"),
        ("grandmother", 3, "anxious", 250, "新面孔警戒"),
        ("grandmother", 9, "secure", 1550, "累积信任"),
    ]
    for cg_id, phase_idx, state, since_day, desc in attachment_history:
        add(edges=[ge.edge_attaches_to(cg_id, phase_idx, state, since_day=since_day, description=desc)])

    # ------------------------------------------------------------
    # 8. Traits: preferences / fears / comforts / temperament
    # ------------------------------------------------------------
    add(nodes=[
        ge.node_preference("music", category="audio", strength=0.7, acquired_at_phase=4),
        ge.node_preference("red", category="visual", strength=0.5, acquired_at_phase=5),
        ge.node_preference("doll", category="object", strength=0.8, acquired_at_phase=6),
        ge.node_fear("stranger", severity=0.7, acquired_at_phase=3),
        ge.node_fear("loud_noise", severity=0.6, acquired_at_phase=8),
        ge.node_comfort("blanket", comfort_kind="object", acquired_at_phase=1),
        ge.node_comfort("mother_voice", comfort_kind="routine", acquired_at_phase=10),
        ge.node_temperament(
            dimensions={"openness": 0.65, "neuroticism": 0.40,
                        "extraversion": 0.55, "agreeableness": 0.70,
                        "conscientiousness": 0.50},
            defined_at_phase=6,
            narrative_zh="温和偏外向，好奇心适中。",
            narrative_en="Mild and slightly extraverted, moderate curiosity.",
        ),
    ])
    add(edges=[
        ge.edge_acquires("preference", "music", 4),
        ge.edge_acquires("preference", "red", 5),
        ge.edge_acquires("preference", "doll", 6),
        ge.edge_acquires("fear", "stranger", 3),
        ge.edge_acquires("fear", "loud_noise", 8),
        ge.edge_acquires("comfort", "blanket", 1),
        ge.edge_acquires("comfort", "mother_voice", 10),
        ge.edge_soothes("comfort_blanket", 3, stress_delta=-0.3, description="夜醒安抚"),
        ge.edge_soothes("comfort_mother_voice", 10, stress_delta=-0.4, description="分离时听录音"),
    ])

    # ------------------------------------------------------------
    # 9. Needs + Trigger events
    # ------------------------------------------------------------
    for trigger in ["hunger", "sleepy", "comfort", "curious", "fear"]:
        add(nodes=[ge.node_need_type(trigger, **gs.hydrate_need(trigger))])

    # 一组 need 触发事件（scene 实例）
    need_events = [
        ("hunger",  0, 5,  "middle-of-night feed"),
        ("sleepy",  1, 20, "overstimulated after visitor"),
        ("fear",    3, 10, "stranger at the door"),
        ("curious", 5, 15, "new toy exploration"),
        ("comfort", 7, 12, "post-tantrum need comfort"),
    ]
    for trigger, phase_idx, day_idx, ctx in need_events:
        event_raw = f"event:need:{phase_idx}:{trigger}"
        add(nodes=[ge.node_event("need", phase_idx, seq=trigger, result="resolved",
                                 day_index=day_idx, context=ctx)])
        add(edges=[
            ge.edge_triggered_by(event_raw, trigger, phase_idx,
                                 day_index=day_idx, resolution="caregiver_response"),
            ge.edge_experiences(event_raw, phase_idx, day_index=day_idx),
        ])

    # ------------------------------------------------------------
    # 10. 压力回退 + 恢复: walking @ P7 regress → P8 recover
    # ------------------------------------------------------------
    add(nodes=[
        ge.node_regression("walking", 7, stress_level_at=0.78,
                           narrative_zh="why_phase 情绪风暴期暂失行走能力。",
                           narrative_en="Walking regressed during why_phase emotional storms."),
        ge.node_recovery("walking", 8, strengthened=True, care_from="caregiver_mother",
                         narrative_zh="母亲陪伴 + social_budding 同伴示范下恢复，更强韧。",
                         narrative_en="Recovered with mother's companionship in social_budding; stronger."),
    ])
    add(edges=[
        ge.edge_regresses(f"event_regression:walking:7", "walking", 7,
                          stress_level_at=0.78, description="2 days of refusing to walk"),
        ge.edge_recovers(f"event_recovery:walking:8", "walking", 8,
                         strengthened=True, care_from="caregiver_mother",
                         description="regained with stronger resilience"),
    ])

    # ------------------------------------------------------------
    # 11. Critical event: naming ceremony @ P6
    # ------------------------------------------------------------
    add(nodes=[
        ge.node_critical(6, 0, reason="naming_ceremony", status="resolved",
                         narrative_zh="命名仪式——身份锚点建立。",
                         narrative_en="Naming ceremony — establishing identity anchor."),
    ])
    add(edges=[
        ge.edge_experiences("critical:6:0", 6, description="naming event happens"),
        ge.edge_resolves("father", "critical:6:0", 6,
                         action="bestowed_name", day_index=600,
                         tag_effects=["named", "identity_stable"],
                         description="父亲赐名"),
        ge.edge_named_by("father", "Lily", day_index=600),
    ])

    # ------------------------------------------------------------
    # 12. DRIVEN_BY: capability prerequisite
    # ------------------------------------------------------------
    add(edges=[
        ge.edge_driven_by("first_words", "babbling_syllables", weight=0.8),  # babbling -> first_words
        ge.edge_driven_by("walking", "crawling", weight=0.9),
        ge.edge_driven_by("pretend_play", "object_permanence", weight=0.7),
        ge.edge_driven_by("why_questions", "first_words", weight=0.6),
    ])
    # Ensure prerequisite nodes exist (created lazily as empty capability)
    # babbling_syllables and crawling already unlocked at P4; object_permanence at P3; first_words at P4.
    # All prerequisites are in capability_schedule above? Let's double-check:
    # - babbling_syllables: NOT in schedule → need to add minimal node
    # - crawling: in schedule (P4)
    # - object_permanence: in schedule (P3)
    # - first_words: in schedule (P4)
    # Add missing babbling_syllables as a capability unlocked at P3 (not in schedule).
    add(nodes=[
        ge.node_capability("babbling_syllables", unlocked_at_phase=3,
                           **gs.hydrate_capability("babbling_syllables")),
    ])
    add(edges=[ge.edge_capability_occurs_in("babbling_syllables", phase_index=3)])

    # ------------------------------------------------------------
    # 13. Narrative nodes @ selected phases
    # ------------------------------------------------------------
    narratives = [
        (0, "新生儿期：纯反射、睡眠占主导、母亲哺乳建立最初联结。",
            "Neonatal: pure reflexes, sleep-dominant; mother builds first bond via feeding."),
        (3, "陌生人焦虑峰值，外婆首次到访引起警戒；依附系统出现波动。",
            "Stranger anxiety peaks; grandmother's first visit triggers wariness; attachment wobbles."),
        (6, "命名仪式：父亲赐名 Lily，自我意识通过镜面测试。",
            "Naming ceremony: father bestows 'Lily'; self-awareness via mirror test."),
        (8, "压力回退后的恢复期，同伴游戏让走路重新稳固，更强韧。",
            "Post-regression recovery; peer play restores walking, stronger this time."),
        (11, "独立期：有观点能辩论，可以进入世界。",
            "Independence: opinions and debate, ready for the world."),
    ]
    for phase_idx, zh, en in narratives:
        add(nodes=[ge.node_narrative(phase_idx, summary=zh,
                                     length_chars=len(zh),
                                     narrative_zh=zh, narrative_en=en)])
        add(edges=[ge.edge_describes(f"narrative:phase_{phase_idx}", phase_idx)])

    # ------------------------------------------------------------
    # 14. STRESSES edge: 回退事件压力归因
    # ------------------------------------------------------------
    add(edges=[
        ge.edge_stresses("event_regression:walking:7", 7, stress_delta=0.3,
                         reason="regression_impact", description="能力失灵加剧焦虑"),
        ge.edge_caused_by("event_regression:walking:7", "fear_loud_noise",
                          phase_index=7, weight=0.5,
                          description="噪声恐惧放大情绪风暴"),
    ])

    # ------------------------------------------------------------
    # 15. Conversations + SPEAKS_TO (P10 起)
    # ------------------------------------------------------------
    add(nodes=[
        ge.node_conversation(f"dm:{BABY_ID}", "dm",
                             participants=[BABY_ID],
                             display_name=f"Mother × Lily · DM",
                             message_count=2),
    ])
    add(edges=[
        ge.edge_speaks_to(f"dm:{BABY_ID}", 10, msg_seq=1,
                          description="首次 DM 对话：谈论天气"),
        ge.edge_speaks_to(f"dm:{BABY_ID}", 11, msg_seq=2,
                          description="对话中表达自己的意见"),
    ])

    # ------------------------------------------------------------
    # 16. World ready terminus
    # ------------------------------------------------------------
    add(nodes=[ge.node_event("world_ready", 11, seq=0, result="graduated")])
    add(edges=[
        ge.edge_experiences("event:world_ready:11:0", 11, description="进入世界"),
        ge.edge_terminated_by("event:world_ready:11:0", 11, cause="world_ready"),
    ])

    return st


def compute_stats(snapshot: dict) -> dict:
    nodes = snapshot["nodes"]
    edges = snapshot["edges"]
    by_group: dict[str, int] = {}
    for n in nodes:
        by_group[n["group"]] = by_group.get(n["group"], 0) + 1

    # degree
    in_deg: dict[str, int] = {}
    out_deg: dict[str, int] = {}
    for e in edges:
        out_deg[e["source"]] = out_deg.get(e["source"], 0) + 1
        in_deg[e["target"]] = in_deg.get(e["target"], 0) + 1
    raw_by_id = {n["id"]: n["metadata"].get("raw_id") for n in nodes}
    degree_top = sorted(
        ((raw_by_id.get(nid, nid[:10]), in_deg.get(nid, 0) + out_deg.get(nid, 0),
          in_deg.get(nid, 0), out_deg.get(nid, 0))
         for nid in set(list(in_deg) + list(out_deg))),
        key=lambda x: -x[1],
    )[:8]

    # 多重边分布
    pair_type_counts: dict[str, int] = {}
    for e in edges:
        key = f"{e['source'][:8]}->{e['target'][:8]}:{e['type']}"
        pair_type_counts[key] = pair_type_counts.get(key, 0) + 1
    multi_edges = {k: v for k, v in pair_type_counts.items() if v >= 2}

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "by_group": by_group,
        "degree_top_8": [
            {"raw_id": r, "total": t, "in": i, "out": o}
            for r, t, i, o in degree_top
        ],
        "multi_edges_count": len(multi_edges),
        "multi_edges_max": max(pair_type_counts.values()) if pair_type_counts else 0,
    }


def main() -> int:
    state = build_state()
    snap = ge.state_to_snapshot(state)
    stats = compute_stats(snap)

    doc = {
        "baby_id": BABY_ID,
        "species": "human",
        "sex": "female",
        "schema": "v3-business-as-graph",
        "status": "world_ready",
        "saved_at": "2026-04-22T12:00:00Z",
        "phases_completed": 12,
        "center_anchor": "baby_this",
        "role": {"anchor": "baby_this"},
        "nodes": snap["nodes"],
        "edges": snap["edges"],
        "stats": stats,
    }

    out_path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "cradle-growth-sample.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {out_path}")
    print(f"  node_count  : {stats['node_count']}")
    print(f"  edge_count  : {stats['edge_count']}")
    print(f"  by_group    : {stats['by_group']}")
    print(f"  multi_edges : {stats['multi_edges_count']} pairs with ≥2 edges (max={stats['multi_edges_max']})")
    print(f"  degree top-5 (raw_id, total, in, out):")
    for row in stats["degree_top_8"][:5]:
        print(f"    {row}")

    # 硬性 spec 校验
    assert stats["node_count"] >= 80, f"spec: nodes ≥ 80 (got {stats['node_count']})"
    assert stats["edge_count"] >= 180, f"spec: edges ≥ 180 (got {stats['edge_count']})"
    assert stats["by_group"].get("progression") == 12, "12 progression"
    assert stats["by_group"].get("dimension") == 6, "6 dimension"
    assert 24 <= stats["by_group"].get("phase", 0) <= 32, "phase in [24,32]"
    # 最高度数必须是 baby_this
    top = stats["degree_top_8"][0]
    assert top["raw_id"] == "baby_this", f"center anchor must be baby_this, got {top['raw_id']}"
    assert top["total"] >= 30, f"baby_this degree ≥ 30 (got {top['total']})"
    print()
    print("=== Sample JSON all spec checks PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
