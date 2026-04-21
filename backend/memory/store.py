"""
LifeMoment / Milestone 持久化层。

关键约定：
- append-only：每个 LifeMoment/Milestone 一行 JSON，追加写
- 单 baby 单序列：life_moments.jsonl 的 seq 与 milestones.jsonl 的 seq **独立**
  （两者各自从 1 开始单调递增；与 events.jsonl 的 seq 也独立）
- 复用 state.py 的 threading.Lock + baby_id 白名单校验
- 原子写：追加失败时文件状态不污染（单行 JSON 写入天然行原子）

[INPUT]: 依赖 cradle.state._validate_baby_id, _baby_dir, _infra_lock
         依赖 memory.schema 的 LifeMoment / Milestone
[OUTPUT]: append_life_moment, load_life_moments, load_recent_moments,
          count_life_moments, next_moment_seq,
          append_milestone, load_milestones, count_milestones, next_milestone_seq
[POS]: memory/ 的存储层，被 ingest / recall / consolidation 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .schema import LifeMoment, Milestone

# 延迟导入 cradle.state 避免循环
from cradle.state import _validate_baby_id, _baby_dir, _infra_lock, _count_lines


# ============================================================
# seq 计数器 + 写入锁（与 state.py 的 _seq_counters 独立，各自文件各一套）
# ============================================================

_moment_seq_counters: dict[str, int] = {}
_moment_seq_locks: dict[str, threading.Lock] = {}

_milestone_seq_counters: dict[str, int] = {}
_milestone_seq_locks: dict[str, threading.Lock] = {}


def _get_moment_seq_lock(baby_id: str) -> threading.Lock:
    with _infra_lock:
        if baby_id not in _moment_seq_locks:
            _moment_seq_locks[baby_id] = threading.Lock()
        return _moment_seq_locks[baby_id]


def _get_milestone_seq_lock(baby_id: str) -> threading.Lock:
    with _infra_lock:
        if baby_id not in _milestone_seq_locks:
            _milestone_seq_locks[baby_id] = threading.Lock()
        return _milestone_seq_locks[baby_id]


def _life_moments_path(baby_id: str) -> Path:
    return _baby_dir(baby_id) / "life_moments.jsonl"


def _milestones_path(baby_id: str) -> Path:
    return _baby_dir(baby_id) / "milestones.jsonl"


# ============================================================
# LifeMoment：读写
# ============================================================

def next_moment_seq(baby_id: str) -> int:
    """分配下一个 LifeMoment seq。必须在 _get_moment_seq_lock 内调用。"""
    _validate_baby_id(baby_id)
    if baby_id not in _moment_seq_counters:
        _moment_seq_counters[baby_id] = _count_lines(_life_moments_path(baby_id))
    _moment_seq_counters[baby_id] += 1
    return _moment_seq_counters[baby_id]


def append_life_moment(baby_id: str, moment: LifeMoment) -> None:
    """
    追加一条 LifeMoment 到 life_moments.jsonl。
    假定 moment.seq 已通过 next_moment_seq 预分配。
    写顺序约定（见 design §7）：本函数总是先于 state.memories.append 执行。
    """
    _validate_baby_id(baby_id)
    path = _life_moments_path(baby_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(moment.to_dict(), ensure_ascii=False)
    # 单行 JSON 追加天然是行原子
    with _get_moment_seq_lock(baby_id):
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_life_moments(baby_id: str) -> list[LifeMoment]:
    """全量加载。小规模（< 几千条）直接内存处理。"""
    _validate_baby_id(baby_id)
    path = _life_moments_path(baby_id)
    if not path.is_file():
        return []
    moments = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                moments.append(LifeMoment.from_dict(json.loads(line)))
            except (json.JSONDecodeError, ValueError, TypeError):
                # 损坏行忽略，不污染其他
                continue
    return moments


def load_recent_moments(baby_id: str, limit: int = 20) -> list[LifeMoment]:
    """加载最近 N 条（按文件尾部，效率 > 全量加载再切片）。"""
    _validate_baby_id(baby_id)
    path = _life_moments_path(baby_id)
    if not path.is_file():
        return []
    # 小规模直接读全部再取尾部；若未来膨胀可换成反向读取
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    tail = lines[-limit:] if limit > 0 else lines
    moments = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            moments.append(LifeMoment.from_dict(json.loads(line)))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return moments


def count_life_moments(baby_id: str) -> int:
    """文件行数 = LifeMoment 条数（每行一条）。"""
    _validate_baby_id(baby_id)
    return _count_lines(_life_moments_path(baby_id))


def rewrite_life_moments(baby_id: str, moments: list[LifeMoment]) -> None:
    """
    整体重写 life_moments.jsonl（用于 consolidation 重算 forget_score 或 prune）。
    原子替换：tempfile + os.replace。
    """
    import os
    import tempfile

    _validate_baby_id(baby_id)
    path = _life_moments_path(baby_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for m in moments:
                f.write(json.dumps(m.to_dict(), ensure_ascii=False) + "\n")
        with _get_moment_seq_lock(baby_id):
            os.replace(tmp, str(path))
            # 刷新 seq 计数器
            _moment_seq_counters[baby_id] = max((m.seq for m in moments), default=0)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ============================================================
# Milestone：读写（同套设计）
# ============================================================

def next_milestone_seq(baby_id: str) -> int:
    _validate_baby_id(baby_id)
    if baby_id not in _milestone_seq_counters:
        _milestone_seq_counters[baby_id] = _count_lines(_milestones_path(baby_id))
    _milestone_seq_counters[baby_id] += 1
    return _milestone_seq_counters[baby_id]


def append_milestone(baby_id: str, milestone: Milestone) -> None:
    _validate_baby_id(baby_id)
    path = _milestones_path(baby_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(milestone.to_dict(), ensure_ascii=False)
    with _get_milestone_seq_lock(baby_id):
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_milestones(baby_id: str) -> list[Milestone]:
    _validate_baby_id(baby_id)
    path = _milestones_path(baby_id)
    if not path.is_file():
        return []
    milestones = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                milestones.append(Milestone.from_dict(json.loads(line)))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    return milestones


def count_milestones(baby_id: str) -> int:
    _validate_baby_id(baby_id)
    return _count_lines(_milestones_path(baby_id))
