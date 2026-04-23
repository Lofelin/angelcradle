"""
scheduler 层给关键事件产出 graph_delta 的辅助函数集合。

[INPUT]: BabyState / phase_idx / capability / milestone 等业务数据
[OUTPUT]: emit_phase_start / emit_capabilities_unlocked / emit_milestones /
          emit_regression / emit_recovery / emit_phase_completed /
          emit_cradle_complete / emit_caregivers_from_state /
          snapshot_and_save / snapshot_and_reset
[POS]: scheduler/ 层的纯函数工厂，被 scheduler.handlers 在 append_event 前
       调用产出 delta；delta 同时塞进 event payload（lifeline SSE 透传）+
       累积到 graph_session（供 /baby/{id}/cradle-graph 查询）
[PROTOCOL]: 变更时更新此头部，然后检查 scheduler/CLAUDE.md

设计原则
========
- 每个 emit_* 返回一个 graph_delta dict（空 delta 返回 {}）
- 业务字段缺失 / 路由失败静默降级：log.warning 但不抛，避免图谱 bug 阻断 DES 主循环
- 时间坐标严格放边/metadata，不创建 stage_/day_/phase_x_day_ 节点
- caregiver 路由：CaregiverProfile.role 的 "parent" / "teacher" 非法，做映射
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def _state_sex(state) -> str:
    """BabyState 没有顶级 sex 字段，真正的值落在 phenotype["sex"]（见 cradle/__init__.py:139）。
    历史上这里写成 getattr(state, "sex", "unknown") 永远取不到，baby 节点全部写成 unknown。"""
    if state is None:
        return "unknown"
    phenotype = getattr(state, "phenotype", None)
    if isinstance(phenotype, dict):
        sex = phenotype.get("sex")
        if sex:
            return sex
    return "unknown"


# ============================================================
# CaregiverProfile.role → graph_emit 合法 role 的映射
# ============================================================

def _map_caregiver_role(role: str) -> str:
    """CaregiverProfile.role（parent/grandparent/nanny/teacher）→
    graph_emit node_caregiver 合法 role（mother/father/grandparent/nanny）。

    role "parent" 歧义最大，按约定降级为 mother（主照护者习惯标签）。
    "teacher" 映射为 nanny（非照护者但提供育儿介入）。
    """
    mapping = {
        "mother": "mother",
        "father": "father",
        "grandparent": "grandparent",
        "grandmother": "grandparent",
        "grandfather": "grandparent",
        "nanny": "nanny",
        "teacher": "nanny",
        "parent": "mother",  # 默认
    }
    return mapping.get((role or "").lower(), "nanny")


# ============================================================
# phase_start: progression + NEXT + baby track
# ============================================================

def emit_phase_start(state, phase_idx: int) -> dict:
    """生成 phase_start 对应的 graph_delta。

    第一次进入（phase_idx=0）或恢复性 phase_start 都可以调用——progression
    节点按 raw_id 幂等 add；NEXT 边 uuid 按 content-hash 幂等。
    """
    try:
        from cradle import graph_emit as ge
        from cradle import graph_story as gs
        from cradle.phases import PHASES

        phase = PHASES[phase_idx]
        nodes = [ge.node_progression(
            phase.name, phase_idx,
            expression_mode=phase.expression_mode,
            **gs.hydrate_progression(phase.name),
        )]
        edges = []
        if phase_idx > 0:
            prev_name = PHASES[phase_idx - 1].name
            edges.append(ge.edge_next(prev_name, phase.name))

        upd_nodes = [ge.track_sample(
            "baby_this",
            phase_index=phase_idx,
            kind="phase_start",
            phase_name=phase.name,
            sim_time=getattr(state, "sim_time", None) if state else None,
        )]

        return ge.merge_deltas(
            ge.delta_add(nodes=nodes, edges=edges),
            ge.delta_update(nodes=upd_nodes),
        )
    except Exception:
        logger.exception("emit_phase_start failed for phase=%s", phase_idx)
        return {}


# ============================================================
# capabilities_unlocked: capability + OCCURS_IN + UNLOCKS + EXPERIENCES
# ============================================================

def emit_capabilities_unlocked(state, phase_idx: int,
                               capabilities: Iterable[str]) -> dict:
    try:
        from cradle import graph_emit as ge
        from cradle import graph_story as gs
        from cradle.ontology import capability_dimension

        nodes = []
        edges = []
        for cap in capabilities or []:
            cap_key = cap if isinstance(cap, str) else str(cap)
            try:
                capability_dimension(cap_key)  # 路由校验（未知 key raise）
            except KeyError:
                logger.warning("skip unknown capability in graph_emit: %s", cap_key)
                continue

            event_raw = f"event:capability_unlock:{phase_idx}:{cap_key}"
            nodes.append(ge.node_capability(
                cap_key, unlocked_at_phase=phase_idx,
                **gs.hydrate_capability(cap_key),
            ))
            nodes.append(ge.node_event(
                "capability_unlock", phase_idx, seq=cap_key, result=cap_key,
            ))
            edges.append(ge.edge_capability_occurs_in(cap_key, phase_index=phase_idx))
            edges.append(ge.edge_unlocks(
                event_raw, cap_key, phase_index=phase_idx,
                description=f"{cap_key} unlocked",
            ))
            edges.append(ge.edge_experiences(
                event_raw, phase_idx,
                description=f"experienced {cap_key} unlock",
            ))
        return ge.delta_add(nodes=nodes, edges=edges)
    except Exception:
        logger.exception("emit_capabilities_unlocked failed")
        return {}


# ============================================================
# milestones: milestone + ACHIEVES + OCCURS_IN
# ============================================================

_MILESTONE_DEFAULT_DIM = "cognitive"


def emit_milestones(state, phase_idx: int, milestones: Iterable) -> dict:
    try:
        from cradle import graph_emit as ge
        from cradle import graph_story as gs

        nodes = []
        edges = []
        for m in milestones or []:
            if isinstance(m, dict):
                slug = m.get("name") or m.get("id") or ""
                kind = m.get("kind") or "milestone"
                dim_hint = m.get("dimension") or _MILESTONE_DEFAULT_DIM
            else:
                slug = getattr(m, "name", "") or ""
                kind = "milestone"
                dim_hint = _MILESTONE_DEFAULT_DIM
            slug = slug.strip()
            if not slug:
                continue
            nodes.append(ge.node_milestone(
                slug, kind, phase_idx, **gs.hydrate_milestone(slug),
            ))
            edges.append(ge.edge_achieves("baby_this", slug, phase_idx))
            try:
                edges.append(ge.edge_milestone_occurs_in(slug, dim_hint, phase_idx))
            except Exception:
                logger.warning("milestone OCCURS_IN routing failed: slug=%s dim=%s",
                               slug, dim_hint)
        return ge.delta_add(nodes=nodes, edges=edges)
    except Exception:
        logger.exception("emit_milestones failed")
        return {}


# ============================================================
# stress_regression / regression_recovery
# ============================================================

def emit_regression(state, phase_idx: int, regressed: Iterable) -> dict:
    try:
        from cradle import graph_emit as ge
        from cradle.ontology import capability_dimension

        nodes = []
        edges = []
        stress_level = None
        try:
            stress_level = round(getattr(state.stress, "stress_level", 0.0), 3)
        except Exception:
            pass
        for r in regressed or []:
            cap = r if isinstance(r, str) else r.get("capability", "")
            cap = (cap or "").strip()
            if not cap:
                continue
            try:
                capability_dimension(cap)
            except KeyError:
                logger.warning("skip unknown regression capability: %s", cap)
                continue
            nodes.append(ge.node_regression(cap, phase_idx, stress_level_at=stress_level))
            edges.append(ge.edge_regresses(
                f"event_regression:{cap}:{phase_idx}", cap, phase_idx,
                stress_level_at=stress_level,
                description=f"{cap} regressed under stress",
            ))
        return ge.delta_add(nodes=nodes, edges=edges)
    except Exception:
        logger.exception("emit_regression failed")
        return {}


def emit_recovery(state, phase_idx: int, recovered: Iterable) -> dict:
    try:
        from cradle import graph_emit as ge
        from cradle.ontology import capability_dimension

        nodes = []
        edges = []
        for r in recovered or []:
            if isinstance(r, dict):
                cap = (r.get("capability") or "").strip()
                strengthened = bool(r.get("strengthened"))
                care_from = r.get("care_from")
            else:
                cap = str(r).strip()
                strengthened = False
                care_from = None
            if not cap:
                continue
            try:
                capability_dimension(cap)
            except KeyError:
                logger.warning("skip unknown recovery capability: %s", cap)
                continue
            nodes.append(ge.node_recovery(
                cap, phase_idx, strengthened=strengthened, care_from=care_from,
            ))
            edges.append(ge.edge_recovers(
                f"event_recovery:{cap}:{phase_idx}", cap, phase_idx,
                strengthened=strengthened, care_from=care_from,
                description=f"{cap} recovered",
            ))
        return ge.delta_add(nodes=nodes, edges=edges)
    except Exception:
        logger.exception("emit_recovery failed")
        return {}


# ============================================================
# phase_completed: narrative (若 summary 非空)
# ============================================================

def emit_phase_completed(state, phase_idx: int, summary) -> dict:
    try:
        from cradle import graph_emit as ge

        text = ""
        if isinstance(summary, dict):
            text = (summary.get("summary") or "").strip()
        elif isinstance(summary, str):
            text = summary.strip()
        if not text:
            return {}
        return ge.delta_add(
            nodes=[ge.node_narrative(
                phase_idx,
                summary=text[:400],
                length_chars=len(text),
                narrative_zh=text[:400],
            )],
            edges=[ge.edge_describes(f"narrative:phase_{phase_idx}", phase_idx)],
        )
    except Exception:
        logger.exception("emit_phase_completed failed")
        return {}


# ============================================================
# physical_changes: height/weight/teeth → milestone + OCCURS_IN → phase:physical
# ============================================================

def emit_physical_changes(state, phase_idx: int,
                          changes: Iterable[dict]) -> dict:
    """把 _update_phase_state 的 physical_growth / new_teeth 变化转换为
    milestone 节点 + OCCURS_IN → phase:physical:* 边。

    不这样做的话 phase:physical:* 节点永远 OCCURS_IN 入度为 0，physical
    维度链只靠 4 条 BELONGS_TO 骨架与主图相连，被力导向甩成孤岛（2026-04-23
    观察）。本函数给每个 physical 变化 emit 1 个 milestone，让 physical
    维度获得真实入度融入主星系。

    changes 条目白名单：
      - {"type": "physical_growth", "height_cm", "weight_kg", "phase"}
      - {"type": "new_teeth", "count", "total"}
    其他类型忽略（避免爆量）。
    """
    try:
        from cradle import graph_emit as ge

        nodes = []
        edges = []
        for ch in changes or []:
            t = ch.get("type")
            if t == "physical_growth":
                slug = f"physical_growth:{phase_idx}"
                h = ch.get("height_cm")
                w = ch.get("weight_kg")
                desc = f"height={h}cm weight={w}kg" if h and w else "physical growth"
                nodes.append(ge.node_milestone(
                    slug, kind="physical_growth",
                    achieved_at_phase=phase_idx,
                    label=f"Growth P{phase_idx}",
                    tags=["physical", "growth"],
                    height_cm=h, weight_kg=w,
                ))
                edges.append(ge.edge_achieves(
                    "baby_this", slug, phase_idx,
                    description=desc,
                ))
                edges.append(ge.edge_occurs_in(
                    slug, "physical",
                    stage=_current_physical_stage(phase_idx),
                    phase_index=phase_idx,
                ))
            elif t == "new_teeth":
                slug = f"new_teeth:{phase_idx}"
                cnt = ch.get("count", 0)
                total = ch.get("total", 0)
                nodes.append(ge.node_milestone(
                    slug, kind="teeth",
                    achieved_at_phase=phase_idx,
                    label=f"Teeth +{cnt} (total {total})",
                    tags=["physical", "teeth"],
                    teeth_added=cnt, teeth_total=total,
                ))
                edges.append(ge.edge_achieves(
                    "baby_this", slug, phase_idx,
                    description=f"{cnt} new teeth, {total} total",
                ))
                edges.append(ge.edge_occurs_in(
                    slug, "physical",
                    stage=_current_physical_stage(phase_idx),
                    phase_index=phase_idx,
                ))
        return ge.delta_add(nodes=nodes, edges=edges) if (nodes or edges) else {}
    except Exception:
        logger.exception("emit_physical_changes failed")
        return {}


def _current_physical_stage(phase_idx: int) -> str:
    try:
        from cradle.ontology import current_phase_for
        return current_phase_for("physical", phase_idx)
    except Exception:
        return "neonate"


# ============================================================
# cradle_complete / world_ready 终局
# ============================================================

def emit_cradle_complete(state, phase_idx: int, *, cause: str = "world_ready") -> dict:
    try:
        from cradle import graph_emit as ge

        event_raw = f"event:{cause}:{phase_idx}:0"
        return ge.merge_deltas(
            ge.delta_add(
                nodes=[ge.node_event(cause, phase_idx, seq=0, result=cause)],
                edges=[
                    ge.edge_experiences(event_raw, phase_idx,
                                        description=f"reached {cause}"),
                    ge.edge_terminated_by(event_raw, phase_idx, cause=cause),
                ],
            ),
            ge.delta_update(nodes=[{
                "id": ge.id_baby(),
                "metadata": {
                    "status": cause,
                    "terminated_at_phase": phase_idx,
                },
            }]),
        )
    except Exception:
        logger.exception("emit_cradle_complete failed")
        return {}


# ============================================================
# caregivers bootstrap（首次 phase_start 时从 state 提取）
# ============================================================

def emit_caregivers_from_state(state, phase_idx: int,
                               moment: str = "phase_start") -> dict:
    """从 state.caregivers 为每个照护者 emit 节点 + CARED_BY 边。

    幂等：caregiver raw_id = f"caregiver_{id}"，多次调用覆盖；
    CARED_BY 边按 (source, target, type, phase_index, day_index, description)
    content-hash，所以不同 moment（phase_start/phase_complete）产出不同 UUID。

    moment：
    - "phase_start"：阶段起点 baseline CARED_BY（description="caregiver {role} present"）
    - "phase_complete"：阶段终点 summary CARED_BY，带 day_index + stress_avg，反映
      本阶段整体照护强度，避免仅靠 1 条/阶段导致 baby_this 入度塌陷。
    """
    try:
        from cradle import graph_emit as ge
        caregivers = getattr(state, "caregivers", None) or {}
        attach_map = getattr(state, "attachment_per_caregiver", None) or {}
        nodes = []
        edges = []
        # 阶段终点：取出本阶段结束时的 day_index 与 stress 快照，保证 UUID 与起点不同
        phase_end_day: int | None = None
        stress_snapshot: float | None = None
        if moment == "phase_complete":
            try:
                from cradle.phases import PHASES
                phase_end_day = PHASES[phase_idx].age_days[1]
            except Exception:
                phase_end_day = None
            try:
                stress_snapshot = float(getattr(getattr(state, "stress", None),
                                                "stress_level", 0.0) or 0.0)
            except Exception:
                stress_snapshot = None

        for cid, cg in caregivers.items():
            role = _map_caregiver_role(getattr(cg, "role", ""))
            display = getattr(cg, "display_name", None)
            nodes.append(ge.node_caregiver(
                cid, role, display_name=display,
            ))
            if moment == "phase_complete":
                desc = f"caregiver {role} summary stress={stress_snapshot:.2f}" \
                    if stress_snapshot is not None \
                    else f"caregiver {role} summary"
                edges.append(ge.edge_cared_by(
                    cid, phase_index=phase_idx,
                    day_index=phase_end_day,
                    quality=getattr(cg, "responsiveness", None),
                    description=desc,
                ))
            else:
                edges.append(ge.edge_cared_by(
                    cid, phase_index=phase_idx,
                    quality=getattr(cg, "responsiveness", None),
                    description=f"caregiver {role} present",
                ))
            state_word = attach_map.get(cid)
            if state_word in {"secure", "anxious", "avoidant"}:
                edges.append(ge.edge_attaches_to(
                    cid, phase_idx, state_word,
                    description=f"attachment={state_word}",
                ))
        return ge.delta_add(nodes=nodes, edges=edges)
    except Exception:
        logger.exception("emit_caregivers_from_state failed")
        return {}


# ============================================================
# traits 差分 emit：自驱动路径新增 fear/preference/comfort
# ============================================================

def emit_trait_diff(
    state,
    phase_idx: int,
    *,
    seen_fears: set[str] | None = None,
    seen_preferences: set[str] | None = None,
    seen_comforts: set[str] | None = None,
) -> tuple[dict, set[str], set[str], set[str]]:
    """diff state.fears / state.preferences / state.comfort_sources 相对于
    seen_* 集合，为新增项 emit trait 节点 + ACQUIRES 边。

    返回 (delta, new_seen_fears, new_seen_preferences, new_seen_comforts)。
    调用方（scheduler/handlers.on_phase_complete）应持久化 seen_* 到 per-baby
    跟踪表，避免跨阶段重复 emit。

    这是对 /intervene 端点 emit 的补充——后者只覆盖父母决议路径，自驱动路径
    （fate_weaving / scene 触发等）也会往 state.fears 等追加，没有它这些
    trait 节点会孤悬或完全缺失。
    """
    try:
        from cradle import graph_emit as ge
    except Exception:
        logger.exception("emit_trait_diff import failed")
        return {}, set(), set(), set()

    def _as_strs(items) -> list[str]:
        if not items:
            return []
        out = []
        for v in items:
            if isinstance(v, str):
                v = v.strip()
                if v:
                    out.append(v)
            elif isinstance(v, dict):
                # 某些模块会用 {"tag": "..."} 形式；尝试兜底
                t = (v.get("tag") or v.get("name") or "").strip()
                if t:
                    out.append(t)
        return out

    cur_fears = set(_as_strs(getattr(state, "fears", None)))
    cur_prefs = set(_as_strs(getattr(state, "preferences", None)))
    cur_comforts = set(_as_strs(getattr(state, "comfort_sources", None)))

    new_fears = cur_fears - (seen_fears or set())
    new_prefs = cur_prefs - (seen_preferences or set())
    new_comforts = cur_comforts - (seen_comforts or set())

    nodes = []
    edges = []
    for tag in new_fears:
        nodes.append(ge.node_fear(tag, acquired_at_phase=phase_idx))
        edges.append(ge.edge_acquires("fear", tag, phase_idx,
                                      description="gained via emergent event"))
    for tag in new_prefs:
        nodes.append(ge.node_preference(tag, acquired_at_phase=phase_idx))
        edges.append(ge.edge_acquires("preference", tag, phase_idx,
                                      description="gained via emergent event"))
    for tag in new_comforts:
        nodes.append(ge.node_comfort(tag, acquired_at_phase=phase_idx))
        edges.append(ge.edge_acquires("comfort", tag, phase_idx,
                                      description="gained via emergent event"))

    delta = ge.delta_add(nodes=nodes, edges=edges) if (nodes or edges) else {}
    return delta, cur_fears, cur_prefs, cur_comforts


# ============================================================
# session 生命周期：apply + snapshot + save
# ============================================================

def apply_and_attach(baby_id: str, delta: Optional[dict],
                     event_dict: Optional[dict] = None) -> Optional[dict]:
    """把 delta 应用到累积状态，并可选地塞进 event_dict['graph_delta']。

    返回同一 event_dict（便于链式调用）。delta 为空/None 时是 no-op。
    """
    if not delta:
        return event_dict
    from cradle import graph_session
    graph_session.apply(baby_id, delta)
    if event_dict is not None:
        event_dict["graph_delta"] = delta
    return event_dict


def ensure_bootstrap(baby_id: str, state) -> dict:
    """确保该 baby 的累积状态已 bootstrap。

    返回首次 bootstrap 的 delta（含 ~38 节点 + 31 BELONGS_TO 边）；重复调用
    返回 {}。调用方必须把返回值 merge 进 phase_start 事件的 graph_delta，
    否则前端 lifeline SSE 永远收不到 dim / phase / baby 节点，图会长成
    "散点+arc" 的残缺形态。
    """
    from cradle import graph_session
    baby_meta = None
    if state is not None:
        baby_meta = {
            "baby_id": baby_id,
            "sex": _state_sex(state),
            "species": getattr(getattr(state, "identity", None), "species", "human")
                       if getattr(state, "identity", None) else "human",
            "status": "alive",
        }
    return graph_session.ensure_bootstrap(baby_id, baby_meta=baby_meta)


def snapshot_and_save(baby_id: str, state, *, status: str,
                      phases_completed: Optional[int] = None) -> dict:
    """把当前累积状态落库到 archive/{baby_id}/cradle_graph.json。"""
    from cradle import graph_session
    import datetime as _dt
    return graph_session.snapshot(
        baby_id,
        species=getattr(getattr(state, "identity", None), "species", "human")
                if getattr(state, "identity", None) else "human",
        sex=_state_sex(state),
        status=status,
        phases_completed=(phases_completed
                          if phases_completed is not None
                          else getattr(state, "current_phase", 0)),
        saved_at=_dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )
