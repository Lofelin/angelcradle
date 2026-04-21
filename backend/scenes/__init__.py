"""
主动行为场景库加载入口。

懒加载 + 进程级单例缓存。首次调用 load_scenes_for_phase(N) 时解析
data/phase_{N:02d}_*.json，后续命中返回同一 list 引用。

[INPUT]: 依赖 scenes.schema.InitiativeScene，JSON 数据文件 scenes/data/phase_*.json
[OUTPUT]: load_scenes_for_phase, pick_scene, count_scenes, all_scenes, reset_cache
[POS]: scenes/ 的加载门面，被 scheduler/needs.py 和 cradle/mind.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import random as _random
import threading
from pathlib import Path
from typing import Iterable, Optional

from .schema import InitiativeScene

_DATA_DIR = Path(__file__).parent / "data"

# 进程级缓存：phase -> list[InitiativeScene]
_cache: dict[int, list[InitiativeScene]] = {}
_lock = threading.Lock()


def _data_path(phase: int) -> Optional[Path]:
    """按 glob 匹配 data/phase_{NN}_*.json，返回第一个命中。"""
    patterns = [f"phase_{phase:02d}_*.json", f"phase_{phase}_*.json"]
    for pat in patterns:
        matches = sorted(_DATA_DIR.glob(pat))
        if matches:
            return matches[0]
    return None


def load_scenes_for_phase(phase: int) -> list[InitiativeScene]:
    """
    加载指定 phase 的场景库。懒加载 + 线程安全缓存。
    文件不存在或解析失败时返回 []。
    """
    if phase in _cache:
        return _cache[phase]
    with _lock:
        if phase in _cache:
            return _cache[phase]
        path = _data_path(phase)
        if path is None or not path.is_file():
            _cache[phase] = []
            return _cache[phase]
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _cache[phase] = []
            return _cache[phase]
        if not isinstance(raw, list):
            _cache[phase] = []
            return _cache[phase]
        scenes: list[InitiativeScene] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                scenes.append(InitiativeScene.from_dict(item))
            except Exception:
                continue
        _cache[phase] = scenes
        return scenes


def count_scenes(phase: int) -> int:
    return len(load_scenes_for_phase(phase))


def all_scenes() -> dict[int, list[InitiativeScene]]:
    """仅用于单测/调试：加载全部 12 阶段。"""
    return {p: load_scenes_for_phase(p) for p in range(12)}


def pick_scene(
    phase: int,
    trigger: Optional[str] = None,
    exclude_ids: Optional[Iterable[str]] = None,
    rng: Optional[_random.Random] = None,
) -> Optional[InitiativeScene]:
    """
    按 phase 随机挑选一条场景。

    - trigger: 若指定，仅从该 trigger 候选中选
    - exclude_ids: 排除的 id 集合（避免重复命中）
    - rng: 可注入伪随机（单测用）
    """
    scenes = load_scenes_for_phase(phase)
    if not scenes:
        return None
    pool = scenes
    if trigger:
        pool = [s for s in pool if s.trigger == trigger]
    if exclude_ids:
        excl = set(exclude_ids)
        pool = [s for s in pool if s.id not in excl]
    if not pool:
        # 退回到无 exclude 版本（避免一直返回 None）
        pool = [s for s in scenes if (not trigger or s.trigger == trigger)]
        if not pool:
            return None
    r = rng or _random
    return r.choice(pool)


def reset_cache() -> None:
    """仅用于测试。"""
    with _lock:
        _cache.clear()


__all__ = [
    "InitiativeScene",
    "load_scenes_for_phase",
    "count_scenes",
    "all_scenes",
    "pick_scene",
    "reset_cache",
]
