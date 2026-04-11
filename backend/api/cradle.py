"""
摇篮 API 端点。

[INPUT]: 依赖 cradle/ 模块、scheduler.py（调度器单例）
[OUTPUT]: FastAPI 路由（含 touch-actions、heartbeat/stream 统一生命流 SSE、interact 标记心跳响应）
[POS]: API 层，暴露摇篮功能给前端；heartbeat/stream 订阅调度器事件通道
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

# SSE heartbeat 间隔（秒）
SSE_HEARTBEAT_INTERVAL = 15

# SSE 响应头：禁止所有层面的缓冲
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

# 快速事件之间的微延迟（秒）
_PACE_DELAY = 0.05

from cradle import (
    admit, admit_stream, load_state, list_cradle_babies,
    check_world_readiness, simulate_phase, simulate_phase_stream,
    resolve_critical_event, complete_phase, grow_stream, PHASES,
    append_event, load_events, append_interaction, load_interactions,
    save_state,
)
from cradle.mind import generate_interaction_response

router = APIRouter(prefix="/cradle")


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


class InteractRequest(BaseModel):
    message: str
    action_type: str = "message"   # "message" | "touch"
    touch_key: Optional[str] = None   # 肢体动作标识（action_type=touch 时必填）


class SocialStartRequest(BaseModel):
    baby_ids: list[str]
    context: str = ""


class SocialTurnRequest(BaseModel):
    session_id: str


class SocialMessageRequest(BaseModel):
    session_id: str
    message: str


class SocialEndRequest(BaseModel):
    session_id: str


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
def admit_baby_stream(baby_id: str):
    """
    将婴儿放入摇篮（SSE 流式）。

    事件流：
    - {"event": "loading", ...}
    - {"event": "extracting", ...}     — 规则提取完成
    - {"event": "compiling", ...}      — LLM 编译开始
    - {"event": "constraints_ready"}   — 约束编译完成
    - {"event": "admitted", ...}       — 入摇篮完成
    """
    def event_generator():
        admitted = False
        try:
            for step in admit_stream(baby_id):
                data = {k: v for k, v in step.items() if not k.startswith("_")}
                append_event(baby_id, data)
                yield _sse(data)
                if step.get("event") == "admitted":
                    admitted = True
        except ValueError as e:
            err = {"event": "error", "message": str(e)}
            append_event(baby_id, err)
            yield _sse(err)
        except Exception as e:
            err = {"event": "error", "message": f"Admission failed: {e}"}
            append_event(baby_id, err)
            yield _sse(err)
        finally:
            # 入摇篮成功后注册到调度器（后台任务）
            if admitted:
                try:
                    from scheduler import scheduler
                    loop = asyncio.get_event_loop()
                    loop.create_task(scheduler.register(baby_id))
                except RuntimeError:
                    pass  # 无事件循环时忽略，heartbeat/stream 连接时会自动注册

    return StreamingResponse(
        _paced(_with_heartbeat(event_generator())),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/babies")
def list_babies():
    """列出摇篮中所有婴儿。"""
    return {"babies": list_cradle_babies()}


@router.get("/{baby_id}/status")
def get_status(baby_id: str):
    """获取婴儿当前状态。"""
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    phase = PHASES[state.current_phase]
    return {
        "baby_id": state.baby_id,
        "name": state.name,
        "species": state.species,
        "current_phase": {
            "index": phase.index,
            "name": phase.name,
            "display_name": phase.display_name,
            "age_range": phase.age_range,
            "description": phase.description,
        },
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
    }


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

    def event_generator():
        try:
            for step in simulate_phase_stream(state):
                data = {k: v for k, v in step.items() if not k.startswith("_")}
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
def intervene(baby_id: str, req: InterveneRequest):
    """父母介入处理关键事件。"""
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
                "age_range": next_phase.age_range,
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
    自动成长（SSE 流式）。

    从当前阶段开始自动推进，连续跑所有阶段。
    遇到关键事件时暂停（yield paused），等待：
      1. POST /{baby_id}/intervene 处理关键事件
      2. 重新调用 GET /{baby_id}/grow/stream 继续成长

    无关键事件的阶段自动完成（含 LLM 阶段总结）。
    全部阶段完成后 yield growth_complete。
    """
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    if state.current_phase >= len(PHASES):
        raise HTTPException(400, "Already completed all phases")

    # 并发保护：同一宝宝不能同时运行两个 grow_stream
    if _grow_locks.get(baby_id):
        raise HTTPException(409, "Growth simulation already running for this baby.")

    def event_generator():
        _grow_locks[baby_id] = True
        try:
            for step in grow_stream(state):
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


@router.post("/{baby_id}/interact")
def interact(baby_id: str, req: InteractRequest):
    """亲子对话：父母发消息，婴儿根据 expression_mode 反应。"""
    if _grow_locks.get(baby_id):
        raise HTTPException(409, "Growth simulation is running. Please wait or pause first.")

    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    # 肢体互动：查找动作描述，构造 LLM 输入
    touch_desc = None
    if req.action_type == "touch" and req.touch_key:
        from cradle.touch import TOUCH_ACTIONS
        action = next((a for a in TOUCH_ACTIONS if a.key == req.touch_key), None)
        if action is None:
            raise HTTPException(400, f"Unknown touch action: {req.touch_key}")
        if not (action.phase_range[0] <= state.current_phase <= action.phase_range[1]):
            raise HTTPException(400, f"Touch action '{req.touch_key}' not available at phase {state.current_phase}")
        touch_desc = action.description

    recent = load_interactions(baby_id, limit=5)
    result = generate_interaction_response(state, req.message, recent,
                                           action_type=req.action_type,
                                           touch_description=touch_desc)

    # 应用状态变更（LLM 判断的发育效应）
    changes = result.get("state_changes", {})
    applied_changes = {}
    if changes.get("new_preference"):
        pref = changes["new_preference"]
        if pref not in state.preferences:
            state.preferences.append(pref)
            applied_changes["new_preference"] = pref
    if changes.get("new_comfort_source"):
        src = changes["new_comfort_source"]
        if src not in state.comfort_sources:
            state.comfort_sources.append(src)
            applied_changes["new_comfort_source"] = src
    if changes.get("fear_reduced"):
        fear = changes["fear_reduced"]
        if fear in state.fears:
            state.fears.remove(fear)
            applied_changes["fear_reduced"] = fear
    if changes.get("new_fear"):
        fear = changes["new_fear"]
        if fear not in state.fears:
            state.fears.append(fear)
            applied_changes["new_fear"] = fear

    # 构建记录
    import time as _time
    record = {
        "parent_message": req.message,
        "action_type": req.action_type,
        "touch_key": req.touch_key,
        "baby_response": result["baby_response"],
        "expression_mode": state.expression_mode,
        "emotional_tone": result.get("emotional_tone", "neutral"),
        "phase": state.current_phase,
        "age_days": state.age_days,
        "state_changes": applied_changes or None,
    }

    # 双写：interactions.jsonl + events.jsonl
    append_interaction(baby_id, record)
    append_event(baby_id, {"event": "interaction", **record})

    # 更新主照护者 interaction_count
    primary_cg = state.caregivers.get("primary_parent")
    if primary_cg:
        primary_cg.interaction_count += 1
    elif state.caregivers:
        # 没有 primary_parent 时回退到第一个照护者
        next(iter(state.caregivers.values())).interaction_count += 1

    # 更新活跃时间戳（亲子互动 = 活跃）
    state.last_active_ts = _time.time()

    # 标记主动行为已被响应（SSE 流会处理后续心跳评估）
    from heartbeat import mark_responded
    mark_responded(state.initiative, state.caregivers)
    state.initiative.last_interact_ts = _time.time()

    save_state(state)

    return {
        "baby_response": result["baby_response"],
        "expression_mode": state.expression_mode,
        "emotional_tone": result.get("emotional_tone", "neutral"),
        "state_changes": applied_changes or None,
        "timestamp": _time.time(),
    }


@router.get("/{baby_id}/heartbeat/stream")
async def heartbeat_stream(baby_id: str):
    """
    统一生命流 SSE。
    合并调度器自主生命事件 + 心跳主动行为。

    事件流：
    - {"event": "autonomous_catchup", ...}    — 离线追赶摘要
    - {"event": "autonomous_event", ...}      — 自主生命事件（有"事"）
    - {"event": "autonomous_routine", ...}    — 日常事件
    - {"event": "heartbeat_initiative", ...}  — 宝宝主动行为
    - {"event": "heartbeat_ignored", ...}     — 被忽略后的反应
    - ": heartbeat"（SSE 注释）               — 保活信号
    """
    state = load_state(baby_id)
    if state is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found in cradle")

    async def event_generator():
        from scheduler import scheduler

        # 追赶模式：补跑离线期间事件
        catchup_events = await scheduler.catchup(baby_id)
        if catchup_events:
            summary = {
                "event": "autonomous_catchup",
                "total_events": len(catchup_events),
                "sim_days": (
                    catchup_events[-1].get("sim_day", 0)
                    - catchup_events[0].get("sim_day", 0) + 1
                ) if catchup_events else 0,
                "events": catchup_events[-10:],  # 只推最近 10 条
            }
            yield _sse(summary)

        # 确保注册到调度器
        if baby_id not in scheduler._agents:
            await scheduler.register(baby_id)

        # 订阅事件通道
        queue = scheduler.subscribe(baby_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=SSE_HEARTBEAT_INTERVAL,
                    )
                    yield _sse(event)
                except asyncio.TimeoutError:
                    yield _sse_heartbeat()
        finally:
            scheduler.unsubscribe(baby_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
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


@router.get("/{baby_id}/readiness")
def get_readiness(baby_id: str):
    """检查世界就绪度。"""
    try:
        return check_world_readiness(baby_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ============================================================
# 多婴儿社交端点
# ============================================================

from cradle.social import (
    start_session, advance_turn, add_parent_message,
    get_session_history, end_session, is_in_session,
)


@router.post("/social/start")
def social_start(req: SocialStartRequest):
    """创建社交会话。"""
    if len(req.baby_ids) < 2:
        raise HTTPException(400, "At least 2 babies required")
    if len(req.baby_ids) != len(set(req.baby_ids)):
        raise HTTPException(400, "Duplicate baby IDs")

    states = []
    for bid in req.baby_ids:
        if _grow_locks.get(bid):
            raise HTTPException(409, f"Growth running for: {bid}")
        if is_in_session(bid):
            raise HTTPException(409, f"Baby {bid} already in a social session")
        state = load_state(bid)
        if state is None:
            raise HTTPException(404, f"Baby '{bid}' not found in cradle")
        if state.current_phase < 8:
            raise HTTPException(400, f"Baby '{bid}' not eligible (phase {state.current_phase}, need >= 8)")
        states.append(state)

    session = start_session(states, req.context)
    return {
        "session_id": session.session_id,
        "participants": [
            {"baby_id": s.baby_id, "name": s.name or s.baby_id,
             "expression_mode": s.expression_mode, "phase": s.current_phase}
            for s in states
        ],
        "context": session.context,
    }


@router.post("/social/turn")
def social_turn(req: SocialTurnRequest):
    """推进一轮社交对话。"""
    try:
        return advance_turn(req.session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/social/message")
def social_message(req: SocialMessageRequest):
    """家长在社交会话中发言。"""
    try:
        return add_parent_message(req.session_id, req.message)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/social/{session_id}/history")
def social_history(session_id: str):
    """获取社交会话历史。"""
    try:
        return get_session_history(session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/social/end")
def social_end(req: SocialEndRequest):
    """结束社交会话，结算 state_changes。"""
    try:
        return end_session(req.session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


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
