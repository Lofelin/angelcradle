"""
摇篮 API 端点。

[INPUT]: 依赖 cradle/ 模块、scheduler.py（调度器单例）
[OUTPUT]: FastAPI 路由（含 touch-actions、lifeline SSE 日志读取器（含 graph_delta 透传）、interact 代理、heartbeat/stream 重定向、cradle-graph 发育图谱快照端点、portrait 肖像同步生成）；GET /cradle/babies 支持 page/page_size 分页（默认 100/页，page_size 上限 100），返回 babies + page/page_size/total/total_pages/has_more
[POS]: API 层，暴露摇篮功能给前端；lifeline 从 events.jsonl 读取事件流（会话/互动/主动需求事件已迁至 /conversations）；cradle-graph 新端点 GET /baby/{id}/cradle-graph 由 baby_router 暴露；portrait 端点支持未入摇篮宝宝（从 birth.json 同步生成）
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from typing import Optional

# SSE heartbeat 间隔（秒）
SSE_HEARTBEAT_INTERVAL = 15
SIM_TICK_INTERVAL = 2           # 模拟时钟 tick 频率（秒）

# SSE 响应头：禁止所有层面的缓冲
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

# 快速事件之间的微延迟（秒）
_PACE_DELAY = 0.05

from cradle import (
    admit, admit_stream, load_state, list_cradle_babies, list_cradle_babies_page,
    CRADLE_BABIES_PAGE_SIZE_MAX,
    check_world_readiness, simulate_phase, simulate_phase_stream,
    resolve_critical_event, complete_phase, grow_stream, PHASES,
    append_event, load_events,
    save_state,
    make_conv_id, get_or_create_conversation, post_parent_message,
    list_messages,
)

# lifeline 不再推送的事件类型（迁至 /conversations 通道或为内部心跳）
_LIFELINE_BLOCKLIST = {
    "interaction",            # 旧亲子互动事件（历史数据兼容，新路径不再写）
    "baby_need",              # 迁入 DM 会话，作为 baby 消息 subtype="need"
    "need_responded",         # 迁入 DM 会话
    # conversation_message: 放行到 lifeline（控制台简要展示互动摘要）
    # heartbeat_initiative/ignored: 保留在 lifeline（Round 2 D.4 约定）
}

router = APIRouter(prefix="/cradle")

# /baby/{baby_id}/* 规范命名空间的路由（与 /cradle 同层挂载）。
# 目前只有 cradle-graph 新端点挂在这里；未来 baby 生命周期其他规范化端点
# （如 /baby/{id}/womb-graph，已由 api/conceive.py 自行挂 /baby 前缀）可一并归位。
baby_router = APIRouter()


# ============================================================
# 肖像
# ============================================================

_portrait_generating: set[str] = set()  # 正在生成头像的 baby_id 集合


@router.get("/baby/{baby_id}/portrait")
async def get_portrait(baby_id: str, age: Optional[int] = None):
    """获取宝宝肖像。

    未入摇篮时从 birth.json 读取 birthplace 同步生成（首次访问即分配头像）。
    已入摇篮时从 state 读取（含更完整的 birthplace 数据）。
    """
    from portrait import get_portrait_path, get_latest_portrait, generate_portrait
    from fastapi.responses import FileResponse

    if age is not None:
        path = get_portrait_path(baby_id, age)
    else:
        path = get_latest_portrait(baby_id)

    if path is not None:
        return FileResponse(path, media_type="image/png")

    # 无肖像：同步生成（从 state 或 birth registry 获取 birthplace）
    if baby_id not in _portrait_generating:
        _portrait_generating.add(baby_id)
        try:
            state = load_state(baby_id)
            if state is not None:
                generate_portrait(state, age_years=age or 0)
            else:
                # 未入摇篮：从出生注册表构造轻量对象
                from api import registry
                baby_data = registry.load(baby_id)
                if baby_data is not None:
                    class _BirthProxy:
                        pass
                    proxy = _BirthProxy()
                    proxy.baby_id = baby_id
                    proxy.birthplace = baby_data.get("birthplace", {})
                    generate_portrait(proxy, age_years=age or 0)
        finally:
            _portrait_generating.discard(baby_id)

    # 重新检查是否已生成
    path = get_latest_portrait(baby_id)
    if path is not None:
        return FileResponse(path, media_type="image/png")

    raise HTTPException(status_code=404, detail="Portrait not available")


# ============================================================
# 请求模型
# ============================================================

class AdmitRequest(BaseModel):
    baby_id: str


class InterveneRequest(BaseModel):
    event_name: str
    parent_action: str
    parent_input: str = ""  # 自由输入（如名字）
    caregiver_id: str = "primary_parent"  # 介入的照护者


class TimeScaleRequest(BaseModel):
    time_scale: str   # "slow" | "normal" | "fast" | "turbo"


# 并发锁：baby_id -> True 表示 grow_stream 正在运行
_grow_locks: dict[str, bool] = {}


# ============================================================
# 端点
# ============================================================

@router.post("/admit")
async def admit_baby(req: AdmitRequest):
    """将婴儿放入摇篮（同步 admit + 注册调度器）。"""
    try:
        state = admit(req.baby_id)
        # 注册到调度器，启动自主生命
        from scheduler import scheduler
        await scheduler.register(req.baby_id)
        return {
            "status": "admitted",
            "baby_id": state.baby_id,
            "species": state.species,
            "identity": state.identity.to_dict(),
            "phase": PHASES[0].display_name,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Admission failed: {e}")


@router.get("/admit/stream")
async def admit_baby_stream(baby_id: str):
    """
    将婴儿放入摇篮（SSE 流式）。

    事件流：
    - {"event": "loading", ...}
    - {"event": "extracting", ...}     — 规则提取完成
    - {"event": "compiling", ...}      — LLM 编译开始
    - {"event": "constraints_ready"}   — 约束编译完成
    - {"event": "admitted", ...}       — 入摇篮完成
    """
    # 在 async 上下文中捕获事件循环引用，供同步生成器线程使用
    _loop = asyncio.get_running_loop()

    def event_generator():
        admitted = False
        try:
            for step in admit_stream(baby_id):
                data = {k: v for k, v in step.items() if not k.startswith("_")}
                # 将分配的 seq 回填到 data，前端据此推进 lastSeq，
                # 避免 lifeline 以 after_seq=0 连接时重放这些事件造成重复。
                data["seq"] = append_event(baby_id, data)
                yield _sse(data)
                if step.get("event") == "admitted":
                    admitted = True
        except ValueError as e:
            err = {"event": "error", "message": str(e)}
            err["seq"] = append_event(baby_id, err)
            yield _sse(err)
        except Exception as e:
            err = {"event": "error", "message": f"Admission failed: {e}"}
            err["seq"] = append_event(baby_id, err)
            yield _sse(err)
        finally:
            # 入摇篮成功后注册到调度器
            # 同步生成器在 StreamingResponse 线程中运行，
            # 用 call_soon_threadsafe 将协程提交到主事件循环
            if admitted:
                from scheduler import scheduler
                _loop.call_soon_threadsafe(
                    lambda: _loop.create_task(scheduler.register(baby_id))
                )

    return StreamingResponse(
        _paced(_with_heartbeat(event_generator())),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/babies")
def list_babies(page: int = 1, page_size: int = 100):
    """列出摇篮中婴儿（分页，默认每页 100）。

    参数：
    - page: 页码，从 1 开始（<1 夹紧到 1）
    - page_size: 每页条数，上限 CRADLE_BABIES_PAGE_SIZE_MAX=100

    响应：
    {
      "babies": [...],
      "page": int, "page_size": int,
      "total": int, "total_pages": int,
      "has_more": bool
    }
    """
    babies, total = list_cradle_babies_page(page=page, page_size=page_size)
    eff_page_size = max(1, min(CRADLE_BABIES_PAGE_SIZE_MAX, int(page_size)))
    eff_page = max(1, int(page))
    total_pages = (total + eff_page_size - 1) // eff_page_size if total > 0 else 0
    return {
        "babies": babies,
        "page": eff_page,
        "page_size": eff_page_size,
        "total": total,
        "total_pages": total_pages,
        "has_more": eff_page < total_pages,
    }


@router.get("/{baby_id}/status")
def get_status(baby_id: str):
    """获取婴儿当前状态。"""
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    phase = PHASES[state.current_phase]

    # 恢复 pending need：从 events.jsonl 查找对应的 baby_need 事件
    pending_need = None
    ini = state.initiative
    if ini.pending_initiative_id:
        events = load_events(baby_id)
        for evt in reversed(events):
            if evt.get("event") == "baby_need" and evt.get("need_id") == ini.pending_initiative_id:
                pending_need = {
                    "need_id": evt["need_id"],
                    "trigger": evt.get("trigger", ""),
                    "urgency": evt.get("urgency", "social"),
                    "timeout_sec": evt.get("timeout_sec", 15),
                    "expression": evt.get("expression", ""),
                    "behavior_type": evt.get("behavior_type", "verbal"),
                    "parent_hint": evt.get("parent_hint", ""),
                }
                break

    return {
        "baby_id": state.baby_id,
        "name": state.name,
        "species": state.species,
        "current_phase": {
            "index": phase.index,
            "name": phase.name,
            "display_name": phase.display_name,
            "age_range": phase.age_range(state.lang),
            "age_range_zh": phase.age_range_zh,
            "age_range_en": phase.age_range_en,
            "description": phase.description,
        },
        "lang": state.lang,
        "age_days": state.age_days,
        "expression_mode": state.expression_mode,
        "capabilities": state.capabilities,
        "attachment_style": state.attachment_style,
        "fears": state.fears,
        "preferences": state.preferences,
        "comfort_sources": state.comfort_sources,
        "milestones": [m.to_dict() for m in state.milestones],
        "memories_count": len(state.memories),
        "caregivers": {cid: c.to_dict() for cid, c in state.caregivers.items()},
        "attachment_per_caregiver": state.attachment_per_caregiver,
        "stress": state.stress.to_dict(),
        "nutrition_sleep": state.nutrition_sleep.to_dict(),
        "emotional": state.emotional.to_dict(),
        "physical": state.physical.to_dict(),
        "pending_criticals": state.pending_criticals,
        "pending_need": pending_need,
        "phase_advancing": state.phase_advancing,
        "time_scale": __import__("config").get_time_scale(),
        "last_active_ts": state.last_active_ts,
        "sim_time": state.sim_time,
        "life_tags": sorted(state.life_tags),
    }


@router.patch("/{baby_id}/time-scale")
async def set_time_scale_legacy(baby_id: str, req: TimeScaleRequest):
    """[代理] 旧端点向后兼容——实际设置全局速率。"""
    from config import set_time_scale as _set_global, get_time_scale
    from scheduler import TIME_SCALES
    if req.time_scale not in TIME_SCALES:
        raise HTTPException(400, f"Invalid time_scale: {req.time_scale}")
    _set_global(req.time_scale)
    return {"time_scale": get_time_scale()}


@router.post("/{baby_id}/advance")
def advance_phase(baby_id: str):
    """
    推进到下一阶段。保姆运行模拟。

    返回阶段结果，包含可能需要父母介入的关键事件。
    如有关键事件，调用 /intervene 处理后再调用 /complete 完成阶段。
    """
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    if state.current_phase >= len(PHASES):
        raise HTTPException(400, "Already completed all phases")

    try:
        result = simulate_phase(state)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(500, f"Phase simulation failed: {e}")


@router.get("/{baby_id}/advance/stream")
def advance_phase_stream(baby_id: str):
    """
    推进到下一阶段（SSE 流式）。

    事件流：
    - {"event": "phase_start", ...}            — 阶段开始
    - {"event": "rolling_events", ...}         — 掷骰结果
    - {"event": "daily_events", ...}           — 日常事件（即时）
    - {"event": "environment_processing", ...} — LLM 处理开始
    - {"event": "environment_reaction", ...}   — 逐个环境反应
    - {"event": "critical_event", ...}         — 需要父母介入
    - {"event": "capabilities_unlocked", ...}
    - {"event": "milestones", ...}
    - {"event": "phase_simulated", ...}        — 完成
    """
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    if state.current_phase >= len(PHASES):
        raise HTTPException(400, "Already completed all phases")

    # 不持久化到 events.jsonl 的进度事件（仅用于 SSE 保活）
    _EPHEMERAL_EVENTS = {"narrating"}

    def event_generator():
        try:
            for step in simulate_phase_stream(state):
                data = {k: v for k, v in step.items() if not k.startswith("_")}
                if data.get("event") not in _EPHEMERAL_EVENTS:
                    append_event(baby_id, data)
                yield _sse(data)
        except Exception as e:
            err = {"event": "error", "message": str(e)}
            append_event(baby_id, err)
            yield _sse(err)

    return StreamingResponse(
        _paced(_with_heartbeat(event_generator())),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/{baby_id}/intervene")
async def intervene(baby_id: str, req: InterveneRequest):
    """父母介入处理关键事件。处理完后自动触发阶段继续。"""
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    try:
        # 更新活跃时间戳（父母介入 = 活跃）
        import time as _time
        state.last_active_ts = _time.time()

        result = resolve_critical_event(
            state,
            event_name=req.event_name,
            parent_action=req.parent_action,
            parent_input=req.parent_input,
            caregiver_id=req.caregiver_id,
        )

        # 将已处理的关键事件标记为不再等待父母
        for c in state.pending_criticals:
            if c.get("event_name") == req.event_name:
                c["awaiting_parent"] = False
        save_state(state)

        # 持久化介入事件到日志（与 critical_event 配对）
        _evt = {
            "event": "intervention",
            "event_name": req.event_name,
            "parent_action": req.parent_action,
            "caregiver_id": req.caregiver_id,
            "reaction": result.get("reaction", ""),
            "emotional_valence": result.get("emotional_valence", ""),
            "phase": state.current_phase,
            "age_days": state.age_days,
        }

        # 摇篮图谱：critical 决议 → critical 节点 + RESOLVES + 新 trait（若 reaction 产出）
        try:
            from scheduler import graph_hooks
            from cradle import graph_emit as ge
            phase_idx = state.current_phase
            # 用 event_name + phase_idx 作为 critical 节点 seq（幂等）
            critical_raw = f"critical:{phase_idx}:{req.event_name}"
            nodes = [ge.node_critical(
                phase_idx, req.event_name,
                reason=req.event_name, status="resolved",
            )]
            edges = [
                ge.edge_experiences(critical_raw, phase_idx,
                                    description=f"{req.event_name} critical"),
                ge.edge_resolves(
                    req.caregiver_id, critical_raw, phase_idx,
                    action=req.parent_action,
                    description=result.get("reaction", "")[:120],
                ),
            ]
            # 首次 caregiver（若 state.caregivers 有此 id 但之前未 emit）——
            # node_caregiver 幂等，重复 add 即覆盖
            cg = (state.caregivers or {}).get(req.caregiver_id)
            if cg is not None:
                role = graph_hooks._map_caregiver_role(getattr(cg, "role", ""))
                nodes.append(ge.node_caregiver(
                    req.caregiver_id, role,
                    display_name=getattr(cg, "display_name", None),
                ))
            # 命名仪式：edge_named_by
            if req.event_name == "naming_ceremony" and req.parent_input:
                edges.append(ge.edge_named_by(
                    req.caregiver_id, req.parent_input,
                ))
            # 新 preference / fear / comfort（节点 + ACQUIRES）
            for kind, key in (("preference", "new_preference"),
                              ("fear", "new_fear"),
                              ("comfort", "new_comfort")):
                tag = result.get(key)
                if not tag:
                    continue
                if kind == "preference":
                    nodes.append(ge.node_preference(tag, acquired_at_phase=phase_idx))
                elif kind == "fear":
                    nodes.append(ge.node_fear(tag, acquired_at_phase=phase_idx))
                else:
                    nodes.append(ge.node_comfort(tag, acquired_at_phase=phase_idx))
                edges.append(ge.edge_acquires(kind, tag, phase_idx,
                                              source_event_ref=critical_raw))
            delta = ge.delta_add(nodes=nodes, edges=edges)
            graph_hooks.apply_and_attach(baby_id, delta, _evt)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("intervention graph_delta failed")

        append_event(baby_id, _evt)

        return result
    except Exception as e:
        raise HTTPException(500, f"Intervention failed: {e}")


# ============================================================
# 照护者管理
# ============================================================


class AddCaregiverRequest(BaseModel):
    caregiver_id: str
    role: str = "parent"           # parent / grandparent / nanny / teacher
    display_name: str = "Caregiver"
    emotional_tone: str = "warm"   # warm / neutral / anxious / strict


@router.get("/{baby_id}/caregivers")
def list_caregivers(baby_id: str):
    """列出照护者。"""
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")
    return {
        "caregivers": {cid: c.to_dict() for cid, c in state.caregivers.items()},
        "attachment_per_caregiver": state.attachment_per_caregiver,
    }


@router.post("/{baby_id}/caregivers")
def add_caregiver(baby_id: str, req: AddCaregiverRequest):
    """添加照护者。"""
    from cradle.state import CaregiverProfile
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")
    if req.caregiver_id in state.caregivers:
        raise HTTPException(409, f"Caregiver '{req.caregiver_id}' already exists")
    state.caregivers[req.caregiver_id] = CaregiverProfile(
        caregiver_id=req.caregiver_id,
        role=req.role,
        display_name=req.display_name,
        emotional_tone=req.emotional_tone,
    )
    state.attachment_per_caregiver[req.caregiver_id] = "forming"
    save_state(state)
    return {"message": f"Caregiver '{req.caregiver_id}' added", "caregiver": state.caregivers[req.caregiver_id].to_dict()}


@router.post("/{baby_id}/complete")
def complete(baby_id: str):
    """完成当前阶段，生成总结，推进到下一阶段。"""
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    try:
        summary = complete_phase(state)
        next_phase = PHASES[state.current_phase] if state.current_phase < len(PHASES) else None
        return {
            "summary": summary,
            "next_phase": {
                "index": next_phase.index,
                "name": next_phase.name,
                "display_name": next_phase.display_name,
                "age_range": next_phase.age_range(state.lang),
                "age_range_zh": next_phase.age_range_zh,
                "age_range_en": next_phase.age_range_en,
            } if next_phase else None,
            "total_phases": len(PHASES),
        }
    except Exception as e:
        raise HTTPException(500, f"Phase completion failed: {e}")


@router.get("/{baby_id}/history")
def get_history(baby_id: str):
    """获取完整成长历史。"""
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    return {
        "baby_id": state.baby_id,
        "name": state.name,
        "species": state.species,
        "phase_summaries": state.phase_summaries,
        "memories": [m.to_dict() for m in state.memories],
        "milestones": [m.to_dict() for m in state.milestones],
        "fears": state.fears,
        "preferences": state.preferences,
        "attachment_style": state.attachment_style,
    }


@router.get("/{baby_id}/grow/stream")
def grow(baby_id: str):
    """
    手动成长（SSE 流式，备用路径）。

    主路径已由 scheduler 自驱动阶段推进接管。
    此端点保留用于手动触发/调试。
    """
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    if state.current_phase >= len(PHASES):
        raise HTTPException(400, "Already completed all phases")

    # 并发保护：同一宝宝不能同时运行两个 grow_stream
    if _grow_locks.get(baby_id):
        raise HTTPException(409, "Growth simulation already running for this baby.")

    # 不持久化到 events.jsonl 的进度事件（与 advance/stream 对齐）
    _GROW_EPHEMERAL = {"narrating", "phase_completing"}

    def event_generator():
        _grow_locks[baby_id] = True
        try:
            for step in grow_stream(state):
                if step.get("event") not in _GROW_EPHEMERAL:
                    append_event(baby_id, step)
                yield _sse(step)
        except Exception as e:
            err = {"event": "error", "message": str(e)}
            append_event(baby_id, err)
            yield _sse(err)
        finally:
            _grow_locks.pop(baby_id, None)

    return StreamingResponse(
        _paced(_with_heartbeat(event_generator())),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )



@router.get("/{baby_id}/lifeline")
async def lifeline(baby_id: str, after_seq: int = 0):
    """
    生命线 SSE -- 日志读取器 + 实时追踪。

    Phase 1 (回放): 读 events.jsonl 中 seq > after_seq 的事件，50ms/条
    Phase 2 (实时): await notify → 读最新事件 → 即时推送
    每 2s 无事件 → sim_tick (时钟心跳)

    **baby 不存在时返回 204 而非 404**：WHATWG HTML 规范规定 EventSource 收到
    204 必须永久 fail connection 并停止重连；返回 404 浏览器会按 retry interval
    无限重试。陈旧 tab / 缓存 JS / localStorage 残留的已删 baby_id 都靠这条
    末端防御兜底——无论前端如何，浏览器到 204 就会安静下来。
    """
    from cradle.state import load_events_after, get_notify

    state = load_state(baby_id)
    if state is None:
        return Response(status_code=204)

    # 自动注册：如果婴儿已 admitted 但调度器未启动，补注册
    from scheduler import scheduler
    await scheduler.register(baby_id)

    async def event_generator():
        last_seq = after_seq
        notify = get_notify(baby_id)

        # Phase 1: 回放历史事件（跳过 _LIFELINE_BLOCKLIST，保留 seq 游标继续推进）
        events = load_events_after(baby_id, last_seq)
        for evt in events:
            last_seq = evt.get("seq", last_seq)
            if evt.get("event") in _LIFELINE_BLOCKLIST:
                continue
            yield _sse(evt)
            await asyncio.sleep(0.2)  # 200ms 回放节奏，给前端渲染留出呼吸感

        # Phase 2: 实时追踪
        while True:
            # 先读再等（防漏）
            new_events = load_events_after(baby_id, last_seq)
            if new_events:
                for evt in new_events:
                    last_seq = evt.get("seq", last_seq)
                    if evt.get("event") in _LIFELINE_BLOCKLIST:
                        continue
                    yield _sse(evt)
                    await asyncio.sleep(0.2)  # 200ms 实时推送节奏
                continue  # 可能还有更多，立即再读

            # 无新事件，等通知
            notify.clear()
            # clear 后再检查一次（防止 clear 和 set 之间丢通知）
            new_events = load_events_after(baby_id, last_seq)
            if new_events:
                for evt in new_events:
                    last_seq = evt.get("seq", last_seq)
                    if evt.get("event") in _LIFELINE_BLOCKLIST:
                        continue
                    yield _sse(evt)
                    await asyncio.sleep(0.2)
                continue

            try:
                await asyncio.wait_for(notify.wait(), timeout=SIM_TICK_INTERVAL)
            except asyncio.TimeoutError:
                # 推送 sim_tick 心跳
                tick_state = load_state(baby_id)
                if tick_state:
                    yield _sse({
                        "event": "sim_tick",
                        "sim_day": int(tick_state.sim_time // 24),
                        "sim_hour": round(tick_state.sim_time % 24, 1),
                    })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/{baby_id}/heartbeat/stream")
async def heartbeat_stream(baby_id: str):
    """向后兼容：重定向到 lifeline。"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url=f"/cradle/{baby_id}/lifeline?after_seq=0",
        status_code=301,
    )


@router.get("/{baby_id}/touch-actions")
def get_touch_actions(baby_id: str):
    """获取当前阶段可用的肢体互动动作。"""
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")
    from cradle.touch import get_available_actions
    return {"actions": get_available_actions(state.current_phase)}


@router.get("/{baby_id}/events")
def get_events(baby_id: str):
    """获取婴儿的所有历史 SSE 事件。"""
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")
    return {"events": load_events(baby_id)}


@router.get("/{baby_id}/graph")
def get_cradle_graph(baby_id: str):
    """[DEPRECATED] 摇篮生命图谱旧端点。

    v3-business-as-graph 上线后推荐改用 GET /baby/{id}/cradle-graph。
    本端点向后兼容，行为：
      - 有 v3 cradle_graph.json 落库 → 返回该快照（含 nodes/edges）
      - 否则 → 返回空 stub（便于老前端静默过渡）
    """
    from api import registry

    snap = registry.load_cradle_graph(baby_id)
    if snap is not None:
        return snap

    return {
        "id": baby_id,
        "schema_version": "1.0",
        "stage": "cradle",
        "baby_id": baby_id,
        "nodes": [],
        "links": [],
    }


@baby_router.get("/baby/{baby_id}/cradle-graph")
def get_cradle_graph_v3(baby_id: str):
    """获取摇篮成长图谱快照（v3-business-as-graph schema）。

    查找顺序：
      1. 进程内累积状态（baby 正在 active session 中且已 emit 过 delta）
      2. archive/{id}/cradle_graph.json（已落库的终局或阶段快照）
      3. 都没有 → 404

    返回 body：
      {baby_id, species, sex, schema, status, saved_at, phases_completed,
       center_anchor, role, nodes[], edges[], stats}
    """
    from api import registry
    from cradle import graph_session

    # Live 状态优先——正在跑的 session 最新
    live = graph_session.get_state(baby_id)
    if live.get("nodes") or live.get("edges"):
        state = load_state(baby_id)
        species = getattr(state.identity, "species", "human") if state and getattr(state, "identity", None) else "human"
        # BabyState 没有顶级 sex，真值在 state.phenotype["sex"]（cradle/__init__.py:139）
        sex = "unknown"
        if state is not None:
            phenotype = getattr(state, "phenotype", None)
            if isinstance(phenotype, dict) and phenotype.get("sex"):
                sex = phenotype["sex"]
        phases_completed = getattr(state, "current_phase", 0) if state else 0
        status = "alive"
        # 进入世界后 state.current_phase 可能仍为 11，但 graph_session 已落库后续 session 不再 live
        if state and bool(getattr(state, "world_ready", False)):
            status = "world_ready"
        return graph_session.snapshot_for_endpoint(
            baby_id,
            species=species, sex=sex, status=status,
            phases_completed=phases_completed,
        )

    # Fallback: 已落库的快照
    snap = registry.load_cradle_graph(baby_id)
    if snap is not None:
        return snap

    raise HTTPException(404, f"Cradle graph not found for baby '{baby_id}'")


@router.get("/{baby_id}/readiness")
def get_readiness(baby_id: str):
    """检查世界就绪度。"""
    try:
        return check_world_readiness(baby_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ============================================================
# 旧 /social/* 端点已迁移至 /conversations（见 api/conversations.py）。
# 多宝宝社交 → POST /conversations {kind:"group", ...}
# 1v1 亲子 → POST /conversations {kind:"dm", ...} 或继续走 /interact 代理
# ============================================================


def _paced(gen):
    """在快速事件之间插入微延迟，确保每个 SSE 事件独立 flush。"""
    for item in gen:
        yield item
        time.sleep(_PACE_DELAY)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_heartbeat() -> str:
    """SSE 注释行，保持连接活跃。浏览器不会触发 onmessage。"""
    return ": heartbeat\n\n"


def _with_heartbeat(gen):
    """
    包装 SSE 生成器，在事件间隔过长时插入 heartbeat。
    防止浏览器/代理判定连接死亡。
    """
    last_event_time = time.monotonic()
    for item in gen:
        now = time.monotonic()
        if now - last_event_time > SSE_HEARTBEAT_INTERVAL:
            yield _sse_heartbeat()
        yield item
        last_event_time = time.monotonic()
