"""
per-baby 摇篮图谱累积状态 + 落库触发。

[INPUT]: baby_id / graph_delta / 终局原因
[OUTPUT]: get_state / apply / snapshot / snapshot_for_endpoint / reset /
          ensure_bootstrap / dispose
[POS]: cradle/ 的会话级图状态容器，被 scheduler.handlers / cradle.nanny 等
       业务代码在产出 delta 时同步累积，终局事件时触发 api.registry 落库
[PROTOCOL]: 变更时更新此头部，然后检查 cradle/CLAUDE.md

设计原则
========
- 进程内状态：{baby_id: {"nodes": {id: node}, "edges": {uuid: edge}, "bootstrapped": bool}}
- 线程安全：threading.Lock 粒度到 per baby，对齐 state.py 的 per-baby 锁风格
- bootstrap 惰性：第一次 apply 或 ensure_bootstrap 时一次性 emit 6 dim + 31 phase +
  BELONGS_TO；业务代码无需关心
- 落库职责单一：snapshot(baby_id, status) 构造落库 dict 并委托 registry.save_cradle_graph
- 不持久化累积状态本身：重启即重来；真正的"真相源"是 events.jsonl + 终局 cradle_graph.json
"""

from __future__ import annotations

import threading
from typing import Optional

from cradle import graph_emit as ge

# 延迟导入 registry 避免启动期循环
_registry = None


def _get_registry():
    global _registry
    if _registry is None:
        from api import registry  # noqa: WPS433
        _registry = registry
    return _registry


# ============================================================
# 进程内状态 + 锁
# ============================================================

_states: dict[str, dict] = {}
_state_locks: dict[str, threading.Lock] = {}
_table_lock = threading.Lock()  # 保护 _states 字典本身


def _get_lock(baby_id: str) -> threading.Lock:
    with _table_lock:
        lk = _state_locks.get(baby_id)
        if lk is None:
            lk = threading.Lock()
            _state_locks[baby_id] = lk
        return lk


def get_state(baby_id: str) -> dict:
    """取（必要时新建）per-baby 累积状态。"""
    with _table_lock:
        st = _states.get(baby_id)
        if st is None:
            st = ge.empty_state()
            st["bootstrapped"] = False
            _states[baby_id] = st
        return st


def reset(baby_id: str) -> None:
    """清空某个 baby 的累积状态（session 重启时用）。"""
    with _table_lock:
        _states.pop(baby_id, None)
        _state_locks.pop(baby_id, None)


def dispose() -> None:
    """整个模块重置——主要供测试使用。"""
    with _table_lock:
        _states.clear()
        _state_locks.clear()


# ============================================================
# bootstrap：首次应用时 emit 6 dim + 31 phase + BELONGS_TO
# ============================================================

def ensure_bootstrap(baby_id: str, baby_meta: Optional[dict] = None) -> dict:
    """确保 baby 的累积图状态已 bootstrap（6 dim + 31 phase + BELONGS_TO + baby 节点）。

    幂等：多次调用只会 apply 一次 bootstrap。baby_meta 可选含 sex / species 等，
    传入时会在首次 bootstrap 时 emit node_baby；缺失时不创建 baby 节点（留给
    scheduler/handlers 的 phase_start 处理，携带 state 真实数据）。

    返回值：**本次真正 bootstrap 的 delta**（首次调用时含 37+ 节点与 31 边；
    后续幂等调用返回 {}）。调用方（scheduler/handlers）应把返回 delta merge 进
    phase_start 事件的 graph_delta 字段，让前端 lifeline SSE 也能收到 bootstrap
    部分——否则前端只能从 SSE 增量累积，永远不知道 dim / phase / baby 节点存在。
    """
    from cradle import graph_story as gs
    from cradle.ontology import DIMENSIONS

    lk = _get_lock(baby_id)
    with lk:
        state = get_state(baby_id)
        if state.get("bootstrapped"):
            return {}

        dim_meta = {d: gs.hydrate_dimension(d) for d in DIMENSIONS}
        nodes = ge.bootstrap_dimension_phase_nodes(dim_meta=dim_meta)
        edges = ge.bootstrap_dimension_phase_edges()

        if baby_meta is not None:
            nodes = [ge.node_baby(
                baby_meta.get("baby_id", baby_id),
                sex=baby_meta.get("sex", "unknown"),
                species=baby_meta.get("species", "human"),
                status=baby_meta.get("status", "alive"),
            )] + nodes

        delta = ge.delta_add(nodes=nodes, edges=edges)
        ge.apply_delta(state, delta)
        state["bootstrapped"] = True
        return delta


# ============================================================
# apply：给累积状态应用一个 delta
# ============================================================

def apply(baby_id: str, delta: dict | None) -> None:
    """应用 graph_delta 到累积状态。空 / None delta 直接跳过。

    调用前应 ensure_bootstrap。性能：apply_delta 为 O(nodes + edges) 每次。
    """
    if not delta:
        return
    lk = _get_lock(baby_id)
    with lk:
        state = get_state(baby_id)
        ge.apply_delta(state, delta)


# ============================================================
# snapshot：构造落库 / 查询用 dict，可选触发落库
# ============================================================

_ALLOWED_STATUS = {"alive", "world_ready", "deceased", "cradle_incomplete"}


def snapshot_for_endpoint(
    baby_id: str,
    *,
    species: str = "human",
    sex: str = "unknown",
    status: str = "alive",
    phases_completed: int = 0,
    saved_at: str | None = None,
    extra_meta: dict | None = None,
) -> dict:
    """把累积状态序列化为 {nodes, edges, stats, ...} 字典（供 HTTP 端点直接返回）。

    不落库，只构造。
    """
    if status not in _ALLOWED_STATUS:
        raise ValueError(f"status must be one of {_ALLOWED_STATUS}, got {status!r}")

    lk = _get_lock(baby_id)
    with lk:
        state = get_state(baby_id)
        nodes = list(state.get("nodes", {}).values())
        edges = list(state.get("edges", {}).values())

    stats = _compute_stats(nodes, edges)

    doc: dict = {
        "baby_id": baby_id,
        "species": species,
        "sex": sex,
        "schema": "v3-business-as-graph",
        "status": status,
        "phases_completed": phases_completed,
        "center_anchor": "baby_this",
        "role": {"anchor": "baby_this"},
        "nodes": nodes,
        "edges": edges,
        "stats": stats,
    }
    if saved_at:
        doc["saved_at"] = saved_at
    if extra_meta:
        doc.update({k: v for k, v in extra_meta.items()
                    if k not in ("nodes", "edges", "stats")})
    return doc


def snapshot(
    baby_id: str,
    *,
    species: str = "human",
    sex: str = "unknown",
    status: str = "alive",
    phases_completed: int = 0,
    saved_at: str | None = None,
    extra_meta: dict | None = None,
) -> dict:
    """构造快照并落库到 archive/{baby_id}/cradle_graph.json，返回构造的 dict。"""
    doc = snapshot_for_endpoint(
        baby_id,
        species=species, sex=sex, status=status,
        phases_completed=phases_completed,
        saved_at=saved_at, extra_meta=extra_meta,
    )
    _get_registry().save_cradle_graph(baby_id, doc)
    return doc


def _compute_stats(nodes: list[dict], edges: list[dict]) -> dict:
    by_group: dict[str, int] = {}
    for n in nodes:
        by_group[n.get("group", "?")] = by_group.get(n.get("group", "?"), 0) + 1
    in_deg: dict[str, int] = {}
    out_deg: dict[str, int] = {}
    for e in edges:
        out_deg[e["source"]] = out_deg.get(e["source"], 0) + 1
        in_deg[e["target"]] = in_deg.get(e["target"], 0) + 1
    raw_by_id = {n["id"]: n.get("metadata", {}).get("raw_id") for n in nodes}
    degree_top = sorted(
        ((raw_by_id.get(nid, nid[:10]),
          in_deg.get(nid, 0) + out_deg.get(nid, 0),
          in_deg.get(nid, 0), out_deg.get(nid, 0))
         for nid in set(list(in_deg) + list(out_deg))),
        key=lambda x: -x[1],
    )[:5]
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "by_group": by_group,
        "degree_top_5": [
            {"raw_id": r, "total": t, "in": i, "out": o}
            for r, t, i, o in degree_top
        ],
    }
