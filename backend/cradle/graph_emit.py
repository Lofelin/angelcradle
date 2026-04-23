"""
摇篮实时图谱帮手库——业务函数通过这里构造节点/边/delta，不直接手写 dict。

[INPUT]: 业务数据（phase_index、cap_key、caregiver 信息、critical 事件等）
[OUTPUT]: 节点构造器 node_* / 边构造器 edge_* / delta_* / merge_deltas /
          apply_delta / track_sample / CradleGroup 枚举
[POS]: cradle/ 的图谱构造纯函数层，被 scheduler.handlers / cradle.nanny /
       cradle.initiative_needs / cradle.conversation / cradle.mind 消费
[PROTOCOL]: 变更时更新此头部，然后检查 cradle/CLAUDE.md

设计原则（详见 openspec/changes/add-cradle-growth-graph/design.md §1-§5）
========
- 全盘沿用 womb/graph_emit.py 的 UUID 规则（UUIDv5 + RFC4122 DNS namespace）
- baby_this raw_id 引用 common.graph_ids.BABY_SELF_RAW_ID 常量（跨图一致性守门）
- 两类发育阶段节点严格区分（v3 铁律）：
    progression:{name}  引擎调度游标
    phase:{dim}:{stage} per-dim 发育期（必须 BELONGS_TO → dimension）
- capability/milestone 的 OCCURS_IN 目标由 edge_occurs_in 内置断言保证为 per-dim phase
- Delta 工具（delta_add / delta_update / delta_remove / merge_deltas / track_append）
  直接复用 womb.graph_emit 的实现——行为一致、代码不重复
"""

from __future__ import annotations

from typing import Iterable

# ============================================================
# 从 womb 复用 UUID + Delta 工具（唯一依赖 womb 的地方）
# ============================================================
#
# 跨图 continuant 延续（baby_this 字节一致）的技术前提：同一 UUID namespace +
# 同一 raw_id 拼写。直接复用 womb.graph_emit.make_node_uuid / make_edge_uuid
# 比"另立 ns + 期望相等"安全得多。
from womb.graph_emit import (  # noqa: E402  (cross-module reuse by design)
    make_edge_uuid,
    make_node_uuid,
    delta_add,
    delta_update,
    delta_remove,
    merge_deltas,
)
from common.graph_ids import BABY_SELF_RAW_ID, baby_raw_id  # noqa: E402
from cradle.ontology import (  # noqa: E402
    DIMENSIONS,
    DIMENSION_PHASES,
    KNOWN_PHASE_STAGES,
    capability_dimension,
    current_phase_for,
    iter_dimension_phases,
)


# ============================================================
# 10 类 group 枚举（对应前端配色表）
# ============================================================

GROUP_IDENTITY = "identity"
GROUP_PROGRESSION = "progression"
GROUP_DIMENSION = "dimension"
GROUP_PHASE = "phase"
GROUP_CAPABILITY_MILESTONE = "capability_milestone"
GROUP_TRAIT = "trait"
GROUP_NEED = "need"
GROUP_EVENT = "event"
GROUP_NARRATIVE = "narrative"
GROUP_CAREGIVER = "caregiver"

ALL_GROUPS: tuple[str, ...] = (
    GROUP_IDENTITY,
    GROUP_PROGRESSION,
    GROUP_DIMENSION,
    GROUP_PHASE,
    GROUP_CAPABILITY_MILESTONE,
    GROUP_TRAIT,
    GROUP_NEED,
    GROUP_EVENT,
    GROUP_NARRATIVE,
    GROUP_CAREGIVER,
)


# ============================================================
# raw id 工具
# ============================================================

def id_baby(fetus_index: int | None = None) -> str:
    """Baby 节点的对外 UUID（跨图一致）。"""
    return make_node_uuid(baby_raw_id(fetus_index))


def id_caregiver(caregiver_id: str) -> str:
    return make_node_uuid(f"caregiver_{caregiver_id}")


def id_progression(phase_name: str) -> str:
    return make_node_uuid(f"progression:{phase_name}")


def id_dimension(dim: str) -> str:
    return make_node_uuid(f"dimension:{dim}")


def id_phase(dim: str, stage: str) -> str:
    return make_node_uuid(f"phase:{dim}:{stage}")


def id_capability(cap_key: str) -> str:
    return make_node_uuid(f"capability_{cap_key}")


def id_milestone(slug: str) -> str:
    return make_node_uuid(f"milestone_{slug}")


def id_need(trigger: str) -> str:
    return make_node_uuid(f"need:{trigger}")


def id_event(event_type: str, phase_index: int, seq: int | str = 0) -> str:
    return make_node_uuid(f"event:{event_type}:{phase_index}:{seq}")


def id_critical(phase_index: int, seq: int | str) -> str:
    return make_node_uuid(f"critical:{phase_index}:{seq}")


def id_regression(cap_key: str, phase_index: int) -> str:
    return make_node_uuid(f"event_regression:{cap_key}:{phase_index}")


def id_recovery(cap_key: str, phase_index: int) -> str:
    return make_node_uuid(f"event_recovery:{cap_key}:{phase_index}")


def id_narrative(phase_index: int) -> str:
    return make_node_uuid(f"narrative:phase_{phase_index}")


def id_conversation(conv_id: str) -> str:
    return make_node_uuid(f"conv:{conv_id}")


def id_trait(kind: str, tag: str) -> str:
    """kind ∈ {preference, fear, comfort}"""
    return make_node_uuid(f"{kind}_{tag}")


def id_temperament() -> str:
    return make_node_uuid("temperament")


# ============================================================
# 节点构造基座
# ============================================================

def _node(
    raw_id: str,
    label: str,
    group: str,
    *,
    continuant_id: str | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    scientific_zh: str | None = None,
    scientific_en: str | None = None,
    **meta,
) -> dict:
    """统一 schema 的节点构造。id/label/group 必备，raw_id 进 metadata 可调试。"""
    if group not in ALL_GROUPS:
        raise ValueError(f"Unknown group '{group}', must be one of {ALL_GROUPS}")
    clean_meta = {k: v for k, v in meta.items() if v is not None}
    clean_meta["raw_id"] = raw_id
    node: dict = {
        "id": make_node_uuid(raw_id),
        "label": label,
        "group": group,
        "metadata": clean_meta,
    }
    if continuant_id:
        node["continuant_id"] = continuant_id
    narrative: dict = {}
    if narrative_zh or narrative_en:
        primary: dict = {}
        if narrative_zh:
            primary["zh_CN"] = narrative_zh
        if narrative_en:
            primary["en"] = narrative_en
        narrative["primary"] = primary
    if scientific_zh or scientific_en:
        sci: dict = {}
        if scientific_zh:
            sci["zh_CN"] = scientific_zh
        if scientific_en:
            sci["en"] = scientific_en
        narrative["scientific"] = sci
    if narrative:
        node["narrative"] = narrative
    return node


# ============================================================
# 节点构造器：身份层
# ============================================================

def node_baby(
    baby_id: str,
    sex: str = "unknown",
    species: str = "human",
    status: str = "alive",
    fetus_index: int | None = None,
    **meta,
) -> dict:
    raw = baby_raw_id(fetus_index)
    return _node(
        raw, "This Baby", GROUP_IDENTITY,
        continuant_id=baby_id,
        narrative_zh="摇篮期新生命锚点——所有照护、能力、事件、依附发生的主体。",
        narrative_en="Cradle-phase self anchor: the subject of all care, capability, event and attachment.",
        kind="baby", baby_id=baby_id, sex=sex, species=species, status=status,
        **meta,
    )


def node_caregiver(
    caregiver_id: str,
    role: str,
    *,
    display_name: str | None = None,
    status: str = "active",
    identity_traits: list | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    **meta,
) -> dict:
    if role not in {"mother", "father", "grandparent", "nanny"}:
        raise ValueError(f"caregiver role must be one of mother/father/grandparent/nanny, got {role!r}")
    label = display_name or {"mother": "Mother", "father": "Father",
                             "grandparent": "Grandparent", "nanny": "Nanny"}[role]
    return _node(
        f"caregiver_{caregiver_id}", label, GROUP_CAREGIVER,
        continuant_id=f"caregiver:{caregiver_id}",
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="caregiver", caregiver_id=caregiver_id, role=role, status=status,
        identity_traits=list(identity_traits) if identity_traits else None,
        **meta,
    )


# ============================================================
# 节点构造器：调度时间线（progression）
# ============================================================

def node_progression(
    phase_name: str,
    phase_index: int,
    *,
    display_name: str | None = None,
    expression_mode: str | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    **meta,
) -> dict:
    if not 0 <= phase_index < 12:
        raise ValueError(f"phase_index must be in [0, 11], got {phase_index}")
    return _node(
        f"progression:{phase_name}",
        display_name or phase_name.replace("_", " ").title(),
        GROUP_PROGRESSION,
        continuant_id=f"progression:{phase_name}",
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="progression", phase_name=phase_name, phase_index=phase_index,
        expression_mode=expression_mode,
        **meta,
    )


# ============================================================
# 节点构造器：发育维度与发育期
# ============================================================

def node_dimension(
    dim: str,
    *,
    display_zh: str | None = None,
    display_en: str | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
) -> dict:
    if dim not in DIMENSIONS:
        raise ValueError(f"dim must be one of {DIMENSIONS}, got {dim!r}")
    return _node(
        f"dimension:{dim}",
        display_en or dim.capitalize(),
        GROUP_DIMENSION,
        continuant_id=f"dimension:{dim}",
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="dimension", dim=dim,
        display_zh=display_zh,
    )


def node_phase_dim(
    dim: str,
    stage: str,
    *,
    age_range_zh: str | None = None,
    age_range_en: str | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    **meta,
) -> dict:
    if (dim, stage) not in KNOWN_PHASE_STAGES:
        raise ValueError(
            f"Unknown phase stage ({dim}, {stage}); "
            f"扩展 cradle/ontology.py DIMENSION_PHASES 后再使用"
        )
    return _node(
        f"phase:{dim}:{stage}",
        f"{dim.capitalize()} · {stage.replace('_', ' ')}",
        GROUP_PHASE,
        continuant_id=f"phase:{dim}:{stage}",
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="phase_dim", dim=dim, stage=stage,
        age_range_zh=age_range_zh, age_range_en=age_range_en,
        **meta,
    )


# ============================================================
# 节点构造器：能力与里程碑
# ============================================================

def node_capability(
    cap_key: str,
    *,
    unlocked_at_phase: int,
    dim: str | None = None,
    strength: float = 1.0,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    **meta,
) -> dict:
    """能力节点。dim 省略时按 CAPABILITY_DIMENSION_MAP 自动路由。"""
    resolved_dim = dim or capability_dimension(cap_key)
    return _node(
        f"capability_{cap_key}",
        cap_key.replace("_", " ").title(),
        GROUP_CAPABILITY_MILESTONE,
        continuant_id=f"capability:{cap_key}",
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="capability", cap_key=cap_key, dim=resolved_dim,
        unlocked_at_phase=unlocked_at_phase, strength=strength,
        regression_history=[],
        **meta,
    )


def node_milestone(
    slug: str,
    kind: str,
    achieved_at_phase: int,
    *,
    label: str | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    tags: list | None = None,
    **meta,
) -> dict:
    return _node(
        f"milestone_{slug}",
        label or slug.replace("_", " ").title(),
        GROUP_CAPABILITY_MILESTONE,
        continuant_id=f"milestone:{slug}",
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="milestone", milestone_kind=kind, slug=slug,
        achieved_at_phase=achieved_at_phase,
        tags=list(tags) if tags else None,
        **meta,
    )


# ============================================================
# 节点构造器：心理与偏好
# ============================================================

def _node_trait(kind: str, tag: str, *, label: str | None = None, **meta) -> dict:
    if kind not in {"preference", "fear", "comfort"}:
        raise ValueError(f"trait kind must be preference/fear/comfort, got {kind!r}")
    return _node(
        f"{kind}_{tag}",
        label or f"{kind.title()}: {tag.replace('_', ' ')}",
        GROUP_TRAIT,
        continuant_id=f"{kind}:{tag}",
        kind=kind, tag=tag,
        **meta,
    )


def node_preference(tag: str, *, category: str | None = None, strength: float = 0.5,
                    acquired_at_phase: int, **meta) -> dict:
    return _node_trait(
        "preference", tag,
        category=category, strength=strength, acquired_at_phase=acquired_at_phase, **meta,
    )


def node_fear(tag: str, *, severity: float = 0.5, acquired_at_phase: int, **meta) -> dict:
    return _node_trait(
        "fear", tag,
        severity=severity, acquired_at_phase=acquired_at_phase, **meta,
    )


def node_comfort(tag: str, *, comfort_kind: str = "object",
                 acquired_at_phase: int, **meta) -> dict:
    return _node_trait(
        "comfort", tag,
        comfort_kind=comfort_kind, acquired_at_phase=acquired_at_phase, **meta,
    )


def node_temperament(
    *,
    dimensions: dict | None = None,
    defined_at_phase: int | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
) -> dict:
    return _node(
        "temperament", "Temperament", GROUP_TRAIT,
        continuant_id="temperament",
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="temperament",
        dimensions=dimensions,
        defined_at_phase=defined_at_phase,
    )


# ============================================================
# 节点构造器：需求与场景
# ============================================================

def node_need_type(
    trigger: str,
    *,
    urgency: str,
    timeout_min: float | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
) -> dict:
    if urgency not in {"physiological", "emotional", "social"}:
        raise ValueError(f"urgency must be physiological/emotional/social, got {urgency!r}")
    return _node(
        f"need:{trigger}",
        trigger.replace("_", " ").title(),
        GROUP_NEED,
        continuant_id=f"need:{trigger}",
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="need_type", trigger=trigger, urgency=urgency,
        timeout_min=timeout_min,
    )


# ============================================================
# 节点构造器：事件层
# ============================================================

def node_event(
    event_type: str,
    phase_index: int,
    *,
    seq: int | str = 0,
    result: str | None = None,
    day_index: int | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    **meta,
) -> dict:
    return _node(
        f"event:{event_type}:{phase_index}:{seq}",
        f"{event_type} @ P{phase_index}",
        GROUP_EVENT,
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="event", event_type=event_type, phase_index=phase_index,
        seq=seq, day_index=day_index, result=result,
        **meta,
    )


def node_critical(
    phase_index: int,
    seq: int | str,
    *,
    reason: str | None = None,
    status: str = "pending",
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    **meta,
) -> dict:
    if status not in {"pending", "resolved", "expired"}:
        raise ValueError(f"critical status must be pending/resolved/expired, got {status!r}")
    return _node(
        f"critical:{phase_index}:{seq}",
        f"Critical @ P{phase_index}",
        GROUP_EVENT,
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="critical_event", phase_index=phase_index, seq=seq,
        reason=reason, status=status,
        **meta,
    )


def node_regression(
    cap_key: str,
    phase_index: int,
    *,
    stress_level_at: float | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    **meta,
) -> dict:
    return _node(
        f"event_regression:{cap_key}:{phase_index}",
        f"Regression · {cap_key}",
        GROUP_EVENT,
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="regression", cap_key=cap_key, phase_index=phase_index,
        stress_level_at=stress_level_at, **meta,
    )


def node_recovery(
    cap_key: str,
    phase_index: int,
    *,
    strengthened: bool = False,
    care_from: str | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
    **meta,
) -> dict:
    return _node(
        f"event_recovery:{cap_key}:{phase_index}",
        f"Recovery · {cap_key}",
        GROUP_EVENT,
        narrative_zh=narrative_zh,
        narrative_en=narrative_en,
        kind="recovery", cap_key=cap_key, phase_index=phase_index,
        strengthened=strengthened, care_from=care_from, **meta,
    )


def node_conversation(
    conv_id: str,
    kind: str,
    *,
    participants: list | None = None,
    display_name: str | None = None,
    message_count: int = 0,
) -> dict:
    if kind not in {"dm", "group"}:
        raise ValueError(f"conversation kind must be dm/group, got {kind!r}")
    return _node(
        f"conv:{conv_id}",
        display_name or f"Conv · {conv_id}",
        GROUP_EVENT,
        continuant_id=f"conv:{conv_id}",
        kind="conversation", conv_id=conv_id, conv_kind=kind,
        participants=list(participants) if participants else None,
        message_count=message_count,
    )


def node_narrative(
    phase_index: int,
    *,
    summary: str | None = None,
    length_chars: int | None = None,
    narrative_zh: str | None = None,
    narrative_en: str | None = None,
) -> dict:
    return _node(
        f"narrative:phase_{phase_index}",
        f"Narrative · P{phase_index}",
        GROUP_NARRATIVE,
        narrative_zh=narrative_zh or summary,
        narrative_en=narrative_en,
        kind="narrative", phase_index=phase_index,
        length_chars=length_chars,
    )


# ============================================================
# 批量：dimension + phase 初始化（会话启动时调一次）
# ============================================================

def bootstrap_dimension_phase_nodes(dim_meta: dict | None = None) -> list[dict]:
    """一次性 emit 全部 6 个 dimension 节点 + 31 个 per-dim phase 节点。

    通常在摇篮 session 启动时调用一次，后续通过 edge_phase_belongs_to 把 phase
    挂到 dimension 下。dim_meta 用于注入 display_zh / narrative_zh 等文本（可选）。
    """
    dim_meta = dim_meta or {}
    nodes: list[dict] = []
    for dim in DIMENSIONS:
        dm = dim_meta.get(dim, {})
        nodes.append(node_dimension(dim, **dm))
    for dim, stage, _months, age_zh, age_en in iter_dimension_phases():
        nodes.append(node_phase_dim(dim, stage, age_range_zh=age_zh, age_range_en=age_en))
    return nodes


def bootstrap_dimension_phase_edges() -> list[dict]:
    """dimension → phase 的 BELONGS_TO 出边（phase 指向 dimension，reversed direction）。"""
    edges: list[dict] = []
    for dim, stage, *_ in iter_dimension_phases():
        edges.append(edge_phase_belongs_to(dim, stage))
    return edges


# ============================================================
# 边构造基座
# ============================================================

def _edge(
    source_raw: str,
    target_raw: str,
    etype: str,
    *,
    phase_index: int | None = None,
    day_index: int | None = None,
    weight: float | None = None,
    description: str = "",
    **extra,
) -> dict:
    """统一的边构造：content-hash uuid + source/target 转 UUID + 业务 extra。

    uuid 纳入 phase_index + description 以支持多重边不碰撞（与 womb 一致）。
    """
    uuid = make_edge_uuid(source_raw, target_raw, etype, phase_index, description)
    e: dict = {
        "uuid": uuid,
        "source": make_node_uuid(source_raw),
        "target": make_node_uuid(target_raw),
        "type": etype,
    }
    if phase_index is not None:
        e["phase_index"] = phase_index
    if day_index is not None:
        e["day_index"] = day_index
    if weight is not None:
        e["weight"] = weight
    if description:
        e["description"] = description
    for k, v in extra.items():
        if v is not None:
            e[k] = v
    return e


# ============================================================
# 边构造器：结构性
# ============================================================

def edge_phase_belongs_to(dim: str, stage: str) -> dict:
    """phase:{dim}:{stage} → dimension:{dim} BELONGS_TO"""
    if (dim, stage) not in KNOWN_PHASE_STAGES:
        raise ValueError(f"Unknown phase stage ({dim}, {stage})")
    return _edge(
        f"phase:{dim}:{stage}", f"dimension:{dim}", "BELONGS_TO",
    )


def edge_next(prev_phase_name: str, next_phase_name: str) -> dict:
    """progression 之间的时间线串联。"""
    return _edge(
        f"progression:{prev_phase_name}", f"progression:{next_phase_name}", "NEXT",
    )


# ============================================================
# 边构造器：发育承担层
# ============================================================

def edge_occurs_in(
    cap_or_milestone_raw: str,
    dim: str,
    stage: str,
    *,
    phase_index: int | None = None,
) -> dict:
    """capability / milestone → per-dim phase 的 OCCURS_IN 归属。

    内置断言：target 必须是 per-dim phase（category=phase），绝不指向 progression。
    """
    if (dim, stage) not in KNOWN_PHASE_STAGES:
        raise ValueError(
            f"OCCURS_IN target must be a known per-dim phase, got ({dim}, {stage}). "
            f"该目标必须是 per-dim phase，不得指向 progression。"
        )
    return _edge(
        cap_or_milestone_raw, f"phase:{dim}:{stage}", "OCCURS_IN",
        phase_index=phase_index,
    )


def edge_capability_occurs_in(cap_key: str, phase_index: int) -> dict:
    """便捷 API：由 cap_key + phase_index 自动路由 per-dim stage。"""
    dim = capability_dimension(cap_key)
    stage = current_phase_for(dim, phase_index)
    return edge_occurs_in(f"capability_{cap_key}", dim, stage, phase_index=phase_index)


def edge_milestone_occurs_in(milestone_slug: str, dim: str, phase_index: int) -> dict:
    """milestone 的 dim 无法从 slug 推断，由调用方显式传入。"""
    stage = current_phase_for(dim, phase_index)
    return edge_occurs_in(f"milestone_{milestone_slug}", dim, stage, phase_index=phase_index)


def edge_unlocks(
    event_raw: str,
    cap_key: str,
    phase_index: int,
    *,
    description: str = "",
    **extra,
) -> dict:
    return _edge(
        event_raw, f"capability_{cap_key}", "UNLOCKS",
        phase_index=phase_index, description=description, **extra,
    )


def edge_achieves(
    baby_raw: str,
    milestone_slug: str,
    phase_index: int,
    *,
    day_index: int | None = None,
    description: str = "",
) -> dict:
    return _edge(
        baby_raw, f"milestone_{milestone_slug}", "ACHIEVES",
        phase_index=phase_index, day_index=day_index, description=description,
    )


def edge_regresses(
    event_raw: str,
    cap_key: str,
    phase_index: int,
    *,
    stress_level_at: float | None = None,
    description: str = "",
) -> dict:
    return _edge(
        event_raw, f"capability_{cap_key}", "REGRESSES",
        phase_index=phase_index, description=description,
        stress_level_at=stress_level_at,
    )


def edge_recovers(
    event_raw: str,
    cap_key: str,
    phase_index: int,
    *,
    strengthened: bool = False,
    care_from: str | None = None,
    description: str = "",
) -> dict:
    return _edge(
        event_raw, f"capability_{cap_key}", "RECOVERS",
        phase_index=phase_index, description=description,
        strengthened=strengthened, care_from=care_from,
    )


def edge_driven_by(new_cap: str, prereq_cap: str, *, weight: float = 1.0) -> dict:
    """capability → capability 的预置依赖关系。"""
    return _edge(
        f"capability_{new_cap}", f"capability_{prereq_cap}", "DRIVEN_BY",
        weight=weight,
    )


# ============================================================
# 边构造器：照护关系
# ============================================================

def edge_cared_by(
    caregiver_id: str,
    phase_index: int,
    *,
    day_index: int | None = None,
    quality: float | None = None,
    description: str = "",
    event_ref: str | None = None,
    fetus_index: int | None = None,
) -> dict:
    return _edge(
        f"caregiver_{caregiver_id}", baby_raw_id(fetus_index), "CARED_BY",
        phase_index=phase_index, day_index=day_index,
        weight=quality, description=description, event_ref=event_ref,
    )


def edge_attaches_to(
    caregiver_id: str,
    phase_index: int,
    state: str,
    *,
    since_day: int | None = None,
    description: str = "",
    fetus_index: int | None = None,
) -> dict:
    if state not in {"secure", "anxious", "avoidant"}:
        raise ValueError(f"attachment state must be secure/anxious/avoidant, got {state!r}")
    return _edge(
        baby_raw_id(fetus_index), f"caregiver_{caregiver_id}", "ATTACHES_TO",
        phase_index=phase_index,
        description=description or f"state={state}",
        state=state, since_day=since_day,
    )


def edge_named_by(
    caregiver_id: str,
    name_given: str,
    *,
    day_index: int | None = None,
    fetus_index: int | None = None,
) -> dict:
    return _edge(
        f"caregiver_{caregiver_id}", baby_raw_id(fetus_index), "NAMED_BY",
        day_index=day_index, name_given=name_given,
    )


def edge_soothes(
    source_raw: str,
    phase_index: int,
    *,
    stress_delta: float,
    description: str = "",
    fetus_index: int | None = None,
) -> dict:
    return _edge(
        source_raw, baby_raw_id(fetus_index), "SOOTHES",
        phase_index=phase_index, description=description,
        weight=abs(stress_delta), stress_delta=stress_delta,
    )


def edge_stresses(
    source_raw: str,
    phase_index: int,
    *,
    stress_delta: float,
    reason: str = "",
    description: str = "",
    fetus_index: int | None = None,
) -> dict:
    return _edge(
        source_raw, baby_raw_id(fetus_index), "STRESSES",
        phase_index=phase_index, description=description or reason,
        weight=abs(stress_delta), stress_delta=stress_delta, reason=reason,
    )


# ============================================================
# 边构造器：经验与塑形
# ============================================================

def edge_triggered_by(
    event_raw: str,
    trigger: str,
    phase_index: int,
    *,
    day_index: int | None = None,
    resolution: str | None = None,
    description: str = "",
) -> dict:
    return _edge(
        event_raw, f"need:{trigger}", "TRIGGERED_BY",
        phase_index=phase_index, day_index=day_index,
        description=description, resolution=resolution,
    )


def edge_experiences(
    event_raw: str,
    phase_index: int,
    *,
    day_index: int | None = None,
    description: str = "",
    fetus_index: int | None = None,
) -> dict:
    return _edge(
        baby_raw_id(fetus_index), event_raw, "EXPERIENCES",
        phase_index=phase_index, day_index=day_index, description=description,
    )


def edge_exposed_to(
    event_raw: str,
    phase_index: int,
    *,
    day_index: int | None = None,
    tag: str | None = None,
    description: str = "",
    fetus_index: int | None = None,
) -> dict:
    return _edge(
        baby_raw_id(fetus_index), event_raw, "EXPOSED_TO",
        phase_index=phase_index, day_index=day_index,
        description=description, tag=tag,
    )


def edge_acquires(
    trait_kind: str,
    tag: str,
    phase_index: int,
    *,
    day_index: int | None = None,
    source_event_ref: str | None = None,
    description: str = "",
    fetus_index: int | None = None,
) -> dict:
    return _edge(
        baby_raw_id(fetus_index), f"{trait_kind}_{tag}", "ACQUIRES",
        phase_index=phase_index, day_index=day_index,
        description=description, source_event_ref=source_event_ref,
    )


def edge_speaks_to(
    conv_id: str,
    phase_index: int,
    *,
    msg_seq: int,
    description: str = "",
    fetus_index: int | None = None,
) -> dict:
    return _edge(
        baby_raw_id(fetus_index), f"conv:{conv_id}", "SPEAKS_TO",
        phase_index=phase_index, description=description,
        msg_seq=msg_seq,
    )


def edge_caused_by(
    event_raw: str,
    cause_raw: str,
    *,
    phase_index: int,
    weight: float | None = None,
    description: str = "",
) -> dict:
    return _edge(
        event_raw, cause_raw, "CAUSED_BY",
        phase_index=phase_index, weight=weight, description=description,
    )


# ============================================================
# 边构造器：归因叙事
# ============================================================

def edge_resolves(
    caregiver_id: str,
    critical_raw: str,
    phase_index: int,
    *,
    action: str | None = None,
    day_index: int | None = None,
    tag_effects: list | None = None,
    description: str = "",
) -> dict:
    return _edge(
        f"caregiver_{caregiver_id}", critical_raw, "RESOLVES",
        phase_index=phase_index, day_index=day_index, description=description,
        action=action, tag_effects=list(tag_effects) if tag_effects else None,
    )


def edge_describes(
    narrative_raw: str,
    phase_index: int,
    *,
    fetus_index: int | None = None,
) -> dict:
    return _edge(
        narrative_raw, baby_raw_id(fetus_index), "DESCRIBES",
        phase_index=phase_index,
    )


def edge_terminated_by(
    event_raw: str,
    phase_index: int,
    cause: str,
    *,
    fetus_index: int | None = None,
) -> dict:
    if cause not in {"deceased", "world_ready", "cradle_incomplete"}:
        raise ValueError(
            f"terminated_by cause must be deceased/world_ready/cradle_incomplete, got {cause!r}"
        )
    return _edge(
        event_raw, baby_raw_id(fetus_index), "TerminatedBy",
        phase_index=phase_index, cause=cause,
    )


# ============================================================
# track_append 便捷 API
# ============================================================

def track_sample(
    node_raw_id: str,
    *,
    phase_index: int,
    day_index: int | None = None,
    **fields,
) -> dict:
    """生成 update_nodes 项：追加一个日常采样到 metadata.track 数组。

    引导业务代码走"日常采样走 update、首次出现走 add"的正确路径。
    """
    sample = {"phase_index": phase_index, **fields}
    if day_index is not None:
        sample["day_index"] = day_index
    return {
        "id": make_node_uuid(node_raw_id),
        "metadata": {"track_append": sample},
    }


# ============================================================
# 后端累积状态 reducer（与前端 mergeGraph 行为一致）
# ============================================================

def apply_delta(state: dict, delta: dict) -> dict:
    """原地更新累积图状态。state 结构：{"nodes": {id: node}, "edges": {uuid: edge}}。

    返回的是传入 state 的同一对象（in-place），便于循环调用。
    """
    if not isinstance(state, dict) or "nodes" not in state or "edges" not in state:
        raise ValueError("state must be {'nodes': dict, 'edges': dict}")
    if not delta:
        return state

    nodes: dict = state["nodes"]
    edges: dict = state["edges"]

    # add_nodes / add_edges：后 add 覆盖先 add（幂等）
    for n in delta.get("add_nodes") or []:
        if n and n.get("id"):
            nodes[n["id"]] = n
    for e in delta.get("add_edges") or []:
        if e and e.get("uuid"):
            edges[e["uuid"]] = e

    # update_nodes：浅合并 + metadata 深合并 + track_append 特殊语义
    for patch in delta.get("update_nodes") or []:
        if not patch or not patch.get("id"):
            continue
        cur = nodes.get(patch["id"])
        if not cur:
            continue
        next_meta = dict(cur.get("metadata") or {})
        for k, v in (patch.get("metadata") or {}).items():
            if k == "track_append" and isinstance(v, dict):
                track = list(next_meta.get("track") or [])
                track.append(v)
                next_meta["track"] = track
            else:
                next_meta[k] = v
        merged = {**cur, **patch, "metadata": next_meta}
        nodes[patch["id"]] = merged

    # update_edges：浅合并
    for patch in delta.get("update_edges") or []:
        if not patch or not patch.get("uuid"):
            continue
        cur = edges.get(patch["uuid"])
        if not cur:
            continue
        edges[patch["uuid"]] = {**cur, **patch}

    # remove_nodes：级联删边
    for nid in delta.get("remove_nodes") or []:
        nodes.pop(nid, None)
        for u in list(edges.keys()):
            ev = edges[u]
            if ev.get("source") == nid or ev.get("target") == nid:
                edges.pop(u, None)
    for u in delta.get("remove_edges") or []:
        edges.pop(u, None)

    return state


def empty_state() -> dict:
    return {"nodes": {}, "edges": {}}


def state_to_snapshot(state: dict) -> dict:
    """reducer 内部 dict 形态 → 落库 JSON 的 {nodes: [...], edges: [...]}。"""
    return {
        "nodes": list(state.get("nodes", {}).values()),
        "edges": list(state.get("edges", {}).values()),
    }


# ============================================================
# 导出清单（便于 from cradle.graph_emit import *）
# ============================================================

__all__ = [
    # UUID / delta 工具（re-export from womb）
    "make_edge_uuid", "make_node_uuid",
    "delta_add", "delta_update", "delta_remove", "merge_deltas",
    # groups
    "ALL_GROUPS",
    "GROUP_IDENTITY", "GROUP_PROGRESSION", "GROUP_DIMENSION", "GROUP_PHASE",
    "GROUP_CAPABILITY_MILESTONE", "GROUP_TRAIT", "GROUP_NEED", "GROUP_EVENT",
    "GROUP_NARRATIVE", "GROUP_CAREGIVER",
    # id helpers
    "id_baby", "id_caregiver", "id_progression", "id_dimension", "id_phase",
    "id_capability", "id_milestone", "id_need", "id_event", "id_critical",
    "id_regression", "id_recovery", "id_narrative", "id_conversation",
    "id_trait", "id_temperament",
    # node constructors
    "node_baby", "node_caregiver", "node_progression", "node_dimension",
    "node_phase_dim", "node_capability", "node_milestone",
    "node_preference", "node_fear", "node_comfort", "node_temperament",
    "node_need_type", "node_event", "node_critical",
    "node_regression", "node_recovery", "node_conversation", "node_narrative",
    # bootstrap helpers
    "bootstrap_dimension_phase_nodes", "bootstrap_dimension_phase_edges",
    # edge constructors
    "edge_phase_belongs_to", "edge_next",
    "edge_occurs_in", "edge_capability_occurs_in", "edge_milestone_occurs_in",
    "edge_unlocks", "edge_achieves", "edge_regresses", "edge_recovers",
    "edge_driven_by",
    "edge_cared_by", "edge_attaches_to", "edge_named_by",
    "edge_soothes", "edge_stresses",
    "edge_triggered_by", "edge_experiences", "edge_exposed_to", "edge_acquires",
    "edge_speaks_to", "edge_caused_by",
    "edge_resolves", "edge_describes", "edge_terminated_by",
    # track & apply
    "track_sample",
    "apply_delta", "empty_state", "state_to_snapshot",
]
