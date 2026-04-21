"""
系统级 API——全局配置端点。

[INPUT]: config.py 全局速率管理
[OUTPUT]: GET/PATCH /system/time-scale
[POS]: API 层系统配置端点，被前端全局导航消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_time_scale, set_time_scale, VALID_TIME_SCALES

router = APIRouter(prefix="/system", tags=["system"])


class TimeScaleRequest(BaseModel):
    time_scale: str  # "slow" | "normal" | "fast" | "turbo"


@router.get("/time-scale")
async def get_system_time_scale():
    """获取当前全局速率。"""
    return {"time_scale": get_time_scale()}


@router.patch("/time-scale")
async def set_system_time_scale(req: TimeScaleRequest):
    """设置全局速率。影响子宫/摇篮/世界所有模块。"""
    if req.time_scale not in VALID_TIME_SCALES:
        raise HTTPException(400, f"Invalid time_scale: {req.time_scale}")
    set_time_scale(req.time_scale)
    return {"time_scale": get_time_scale()}
