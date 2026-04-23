"""
子宫实时图谱帮手库——业务函数通过这里构造节点/边/delta，不直接手写 dict。

设计原则（见 openspec/changes/add-womb-conception-graph/design.md §1-§5）：
- 实体稳定：每个 continuant 仅一个节点，不按阶段拆分
- 时间在边上：stage_index 作为边的属性
- 无 Stage 节点：时间不配当节点
- 多重边天然：同一对节点多次关系 emit 产生多条边，uuid 的 content-hash 保证唯一
- uuid 纯技术标识：e_ + md5 前 10 位，不承载任何语义

[INPUT]: 业务数据（激素数值、营养水平、阶段 index、事件类型等）
[OUTPUT]: 导出 node_* / edge / delta_add / delta_update / delta_remove / merge_deltas / make_edge_uuid
[POS]: womb/ 的图谱构造纯函数层，被 hormones/nutrients/teratogen/vitals/fate/stages 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from typing import Any, Iterable

from common.graph_ids import UUID_NAMESPACE_STR, BABY_SELF_RAW_ID

# 固定命名空间 (UUIDv5 需要): 使用 RFC4122 DNS namespace 作为项目稳定 ns
# 值从 common.graph_ids 常量读取, 保证 womb / cradle 两侧字节一致
_UUID_NAMESPACE = _uuid.UUID(UUID_NAMESPACE_STR)

# ============================================================
# 组别枚举（对应 frontend palette）
# ============================================================

GROUP_IDENTITY = "identity"
GROUP_MATERNAL = "maternal_stage"
GROUP_EMBODIMENT = "embodiment"
GROUP_NEURAL = "neural_behavior"
GROUP_FATE = "fate_birth"


# ============================================================
# uuid 构造（content-hash，标准 RFC4122 UUID v5）
# ============================================================

def make_edge_uuid(
    source: str,
    target: str,
    etype: str,
    stage_index: int | None = None,
    description: str = "",
) -> str:
    """确定性边 uuid, 标准 RFC4122 格式 xxxxxxxx-xxxx-5xxx-xxxx-xxxxxxxxxxxx

    标准 RFC4122 UUID 视觉风格。UUIDv5 基于 SHA-1 + 固定 namespace, 幂等确定。
    """
    payload = f"E|{source}|{target}|{etype}|{stage_index if stage_index is not None else ''}|{description}"
    return str(_uuid.uuid5(_UUID_NAMESPACE, payload))


def make_node_uuid(raw_id: str) -> str:
    """确定性节点 uuid, 标准 RFC4122 格式 xxxxxxxx-xxxx-5xxx-xxxx-xxxxxxxxxxxx

    raw_id: 内部可读 id (如 'hormone_cortisol' / 'organ_heart')
    同一 raw_id 始终返回同一 UUID (幂等), id 是纯技术标识不承载语义。
    """
    return str(_uuid.uuid5(_UUID_NAMESPACE, f"N|{raw_id}"))


# ============================================================
# 节点构造器（纯函数，全部返回符合 spec 的 dict）
# ============================================================

def _node(id_: str, label: str, group: str, *,
          continuant_id: str | None = None,
          narrative_zh: str | None = None,
          narrative_en: str | None = None,
          **meta) -> dict:
    """节点构造基座——统一 schema，保证 id/label/group 三必备字段

    id_ 是可读 raw id (如 'hormone_cortisol'), 内部转换为 content-hash UUID 作为对外 id,
    原 raw 保留在 metadata.raw_id 供调试。id 作为纯技术 UUID, 不承载任何语义。
    """
    clean_meta = {k: v for k, v in meta.items() if v is not None}
    clean_meta["raw_id"] = id_  # 保留可读 raw 做调试 + 反查
    node = {
        "id": make_node_uuid(id_),
        "label": label,
        "group": group,
        "metadata": clean_meta,
    }
    if continuant_id:
        node["continuant_id"] = continuant_id
    if narrative_zh or narrative_en:
        primary: dict = {}
        if narrative_zh:
            primary["zh_CN"] = narrative_zh
        if narrative_en:
            primary["en"] = narrative_en
        node["narrative"] = {"primary": primary}
    return node


def node_baby(baby_id: str, sex: str = "unknown", status: str = "alive", **meta) -> dict:
    return _node(
        BABY_SELF_RAW_ID, "This Baby", GROUP_IDENTITY,
        continuant_id=baby_id,
        narrative_zh="本次受孕的新生命锚点，所有事件的发生场",
        kind="baby", sex=sex, status=status, **meta,
    )


def node_species(code: str) -> dict:
    return _node(
        f"species_{code}", code.capitalize(), GROUP_IDENTITY,
        continuant_id=f"species_{code}",
        narrative_zh=f"{code} 物种蓝图",
        kind="species", code=code,
    )


def node_parent(side: str, **meta) -> dict:
    label = "Father Genome" if side == "father" else "Mother Genome"
    return _node(
        f"genome_{side}", label, GROUP_IDENTITY,
        continuant_id=f"genome_{side}",
        kind="parent", side=side, **meta,
    )


def node_methylation(**meta) -> dict:
    return _node(
        "methylation", "Methylation Map", GROUP_IDENTITY,
        continuant_id="methylation",
        narrative_zh="表观遗传甲基化图谱",
        kind="epigenetics", **meta,
    )


def node_birthplace(code: str, name: str | None = None, **meta) -> dict:
    return _node(
        f"birthplace_{code}", name or code, GROUP_MATERNAL,
        continuant_id=f"birthplace_{code}",
        kind="birthplace", name=name or code, **meta,
    )


def node_hormone(name: str, label: str | None = None,
                 narrative_zh: str | None = None, narrative_en: str | None = None, **meta) -> dict:
    return _node(
        f"hormone_{name}", label or name.capitalize(), GROUP_MATERNAL,
        continuant_id=name,
        narrative_zh=narrative_zh, narrative_en=narrative_en,
        kind="hormone", **meta,
    )


def node_nutrient(name: str, label: str | None = None,
                  narrative_zh: str | None = None, narrative_en: str | None = None, **meta) -> dict:
    return _node(
        f"nutrient_{name}", label or name.capitalize(), GROUP_MATERNAL,
        continuant_id=name,
        narrative_zh=narrative_zh, narrative_en=narrative_en,
        kind="nutrient", **meta,
    )


def node_teratogen(name: str, label: str | None = None,
                   narrative_zh: str | None = None, narrative_en: str | None = None, **meta) -> dict:
    return _node(
        f"teratogen_{name}", label or name.capitalize(), GROUP_MATERNAL,
        continuant_id=name,
        narrative_zh=narrative_zh, narrative_en=narrative_en,
        kind="teratogen", **meta,
    )


def node_organ(name: str, formation_stage: int | None = None, maturation_stage: int | None = None,
               label: str | None = None,
               narrative_zh: str | None = None, narrative_en: str | None = None,
               neural: bool = False) -> dict:
    """neural=True 把器官放到 neural_behavior 组（大脑常这样做）"""
    return _node(
        f"organ_{name}", label or name.capitalize(),
        GROUP_NEURAL if neural else GROUP_EMBODIMENT,
        continuant_id=name,
        narrative_zh=narrative_zh, narrative_en=narrative_en,
        kind="organ",
        formation_stage=formation_stage,
        maturation_stage=maturation_stage,
    )


def node_vital(name: str, unit: str, label: str | None = None,
               narrative_zh: str | None = None, narrative_en: str | None = None,
               neural: bool = False) -> dict:
    return _node(
        f"vital_{name}", label or name.replace("_", " ").title(),
        GROUP_NEURAL if neural else GROUP_EMBODIMENT,
        continuant_id=name,
        narrative_zh=narrative_zh, narrative_en=narrative_en,
        kind="vital", unit=unit,
    )


def node_reflex(name: str, emerges_stage: int, label: str | None = None,
                narrative_zh: str | None = None, narrative_en: str | None = None) -> dict:
    return _node(
        f"reflex_{name}", label or f"{name.capitalize()} Reflex", GROUP_NEURAL,
        continuant_id=name,
        narrative_zh=narrative_zh, narrative_en=narrative_en,
        kind="reflex", emerges_stage=emerges_stage,
    )


def node_temperament(dimension: str, score: float, defined_stage: int) -> dict:
    return _node(
        "temperament", "Temperament", GROUP_NEURAL,
        continuant_id="temperament",
        narrative_zh=f"气质：{dimension} 维度 {score:.2f}",
        kind="temperament", dimension=dimension, score=score, defined_stage=defined_stage,
    )


def node_event(event_type: str, stage_index: int, result: Any, narrative_zh: str | None = None, **meta) -> dict:
    """事件节点 id 构造: event_{type}_s{stage} (事件有独立身份，按 stage 区分)"""
    return _node(
        f"event_{event_type}_s{stage_index}",
        f"{event_type.replace('_', ' ').title()}: {result}",
        GROUP_FATE,
        narrative_zh=narrative_zh,
        kind="event", event_type=event_type, stage_index=stage_index, result=result, **meta,
    )


def node_defect(defect_type: str, severity: str, label: str | None = None, narrative_zh: str | None = None) -> dict:
    return _node(
        f"defect_{defect_type}", label or defect_type.replace("_", " ").title(), GROUP_FATE,
        continuant_id=f"defect_{defect_type}",
        narrative_zh=narrative_zh,
        kind="defect", severity=severity,
    )


def node_narrative(stage_index: int, text: str) -> dict:
    return _node(
        f"narr_s{stage_index}", f"S{stage_index} Narrative", GROUP_FATE,
        narrative_zh=text,
        kind="narrative", stage_index=stage_index, length_chars=len(text),
    )


# ============================================================
# 边构造器（通用 edge + 特定语义 helper）
# ============================================================

def edge(source: str, target: str, etype: str, *,
         stage_index: int | None = None,
         weight: float | None = None,
         description: str = "",
         **extra) -> dict:
    """通用边构造：content-hash uuid + 规范字段 + 业务 extra

    source/target 传入可读 raw id (如 'hormone_cortisol'), 内部转换为节点 UUID 作为对外引用。
    edge uuid 的 content-hash 仍基于 raw id 计算（可读性 + 稳定性都保留在 hash payload 里）。
    """
    uuid = make_edge_uuid(source, target, etype, stage_index, description)
    e = {
        "uuid": uuid,
        "source": make_node_uuid(source),
        "target": make_node_uuid(target),
        "type": etype,
    }
    if stage_index is not None:
        e["stage_index"] = stage_index
    if weight is not None:
        e["weight"] = weight
    if description:
        e["description"] = description
    # 其他业务字段（level_at/exposure/polarity/phase/unit/v/status 等）
    for k, v in extra.items():
        if v is not None:
            e[k] = v
    return e


# ============================================================
# Delta 工具（add/update/remove + merge）
# ============================================================

def delta_add(nodes: Iterable[dict] | None = None, edges: Iterable[dict] | None = None) -> dict:
    d = {}
    if nodes:
        d["add_nodes"] = list(nodes)
    if edges:
        d["add_edges"] = list(edges)
    return d


def delta_update(nodes: Iterable[dict] | None = None, edges: Iterable[dict] | None = None) -> dict:
    d = {}
    if nodes:
        d["update_nodes"] = list(nodes)
    if edges:
        d["update_edges"] = list(edges)
    return d


def delta_remove(node_ids: Iterable[str] | None = None, edge_uuids: Iterable[str] | None = None) -> dict:
    d = {}
    if node_ids:
        d["remove_nodes"] = list(node_ids)
    if edge_uuids:
        d["remove_edges"] = list(edge_uuids)
    return d


def merge_deltas(*deltas: dict) -> dict:
    """把多个 delta 合并为一个（业务编排层用）——空列表字段自动清理"""
    out: dict = {}
    keys = (
        "add_nodes", "add_edges",
        "update_nodes", "update_edges",
        "remove_nodes", "remove_edges",
    )
    for k in keys:
        merged = []
        for d in deltas:
            if not d:
                continue
            merged.extend(d.get(k, []))
        if merged:
            out[k] = merged
    return out


def track_append(node_id: str, stage_index: int, **fields) -> dict:
    """生成 update_nodes 项：追加 metadata.track 数组一个样本点

    node_id 传入可读 raw id (如 'hormone_cortisol'), 内部转 UUID 以匹配节点的对外 id。
    前端 mergeGraph 识别 metadata.track_append 做数组追加。
    """
    return {
        "id": make_node_uuid(node_id),
        "metadata": {"track_append": {"stage_index": stage_index, **fields}},
    }
