"""
摇篮 API 端点。

[INPUT]: 依赖 cradle/ 模块
[OUTPUT]: FastAPI 路由
[POS]: API 层，暴露摇篮功能给前端
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

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
)

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


# ============================================================
# 端点
# ============================================================

@router.post("/admit")
def admit_baby(req: AdmitRequest):
    """将婴儿放入摇篮（同步）。"""
    try:
        state = admit(req.baby_id)
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
        try:
            for step in admit_stream(baby_id):
                data = {k: v for k, v in step.items() if not k.startswith("_")}
                yield _sse(data)
        except ValueError as e:
            yield _sse({"event": "error", "message": str(e)})
        except Exception as e:
            yield _sse({"event": "error", "message": f"Admission failed: {e}"})

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
        "parent_profile": state.parent_profile.to_dict(),
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
                yield _sse(data)
        except Exception as e:
            yield _sse({"event": "error", "message": str(e)})

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
        result = resolve_critical_event(
            state,
            event_name=req.event_name,
            parent_action=req.parent_action,
            parent_input=req.parent_input,
        )
        return result
    except Exception as e:
        raise HTTPException(500, f"Intervention failed: {e}")


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

    def event_generator():
        try:
            for step in grow_stream(state):
                yield _sse(step)
        except Exception as e:
            yield _sse({"event": "error", "message": str(e)})

    return StreamingResponse(
        _paced(_with_heartbeat(event_generator())),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/{baby_id}/readiness")
def get_readiness(baby_id: str):
    """检查世界就绪度。"""
    try:
        return check_world_readiness(baby_id)
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
