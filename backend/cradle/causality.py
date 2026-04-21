"""
因果标签生成引擎——为每个事件生成结构化的因果标签。

纯规则引擎，零 LLM 调用，确定性输出。
标签格式: namespace:key 或 namespace:action:detail (ADR-5)。

[INPUT]: events/definitions.py 的 Event, cradle/state.py 的 BabyState/Identity/Memory
[OUTPUT]: generate_cause_tags(), generate_effect_tags(), rebuild_tags_from_memory()
[POS]: cradle/ 的因果标签引擎，为每个事件生成结构化的因果标签
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from __future__ import annotations

# ── 感官通道常量 ──

ALL_SENSES = ("hearing", "vision", "touch", "smell", "proprioception")

# 感官通道别名 → 标准通道名
SENSORY_ALIASES = {
    "auditory": "hearing", "visual": "vision", "tactile": "touch",
    "olfactory": "smell", "vestibular": "proprioception",
    "gustatory": "smell",
    "hearing": "hearing", "vision": "vision", "touch": "touch",
    "smell": "smell", "proprioception": "proprioception",
}

# ── A. 标签命名规范常量 ──

# 感官通道 → (dominant_tag, weak_tag)
SENSORY_CAUSE_RULES = {
    s: (f"sensory_dominant:{s}", f"sensory_weak:{s}") for s in ALL_SENSES
}

# 事件类别 → effect_tag
EVENT_EFFECT_RULES = {
    "daily": "category:daily", "environment": "category:environment",
    "critical": "category:critical", "schedule": "category:schedule",
}


# ── B. generate_cause_tags ──

def generate_cause_tags(event_data: dict, identity=None, state=None) -> list[str]:
    """从事件 + 先天身份 + 当前状态生成原因标签。

    所有参数均可为 None，优雅降级。纯函数，确定性，零 LLM。
    """
    if event_data is None:
        return []

    tags: list[str] = []
    channels = _get_channels(event_data)
    intensity = _get_float(event_data, "intensity", 0.0)

    # 1. 感官通道匹配
    if identity is not None:
        sp = getattr(identity, "sensory_profile", None)
        if sp is not None:
            dominant = getattr(sp, "dominant", "")
            weak = getattr(sp, "weak", "")
            for ch in channels:
                n = SENSORY_ALIASES.get(ch, ch)
                if n == dominant:
                    tags.append(f"sensory_dominant:{n}")
                if n == weak:
                    tags.append(f"sensory_weak:{n}")

    # 2. 唤醒基线 x 事件强度
    if identity is not None:
        arousal = getattr(identity, "arousal_baseline", "moderate")
        if arousal == "high" and intensity > 0.3:
            tags.append("arousal:overstimulated")
        elif arousal == "low" and intensity > 0.3:
            tags.append("arousal:sensitive")
        elif arousal == "high" and intensity <= 0.3:
            tags.append("arousal:high")
        elif arousal == "low" and intensity <= 0.2:
            tags.append("arousal:low")

    # 3. 压力上下文
    if state is not None:
        stress_level = _get_stress_level(state)
        if stress_level > 0.7:
            tags.append("stress:high")
        elif stress_level > 0.4:
            tags.append("stress:moderate")

    # 4. 阶段上下文
    if state is not None:
        phase = getattr(state, "current_phase", None)
        if phase is not None:
            tags.append(f"phase:{phase}")

    # 5. 缺陷匹配
    if identity is not None:
        for defect in (getattr(identity, "defects", None) or []):
            dl = defect.lower()
            for ch in channels:
                if SENSORY_ALIASES.get(ch, ch) in dl:
                    tags.append(f"defect:{defect}")
                    break

    return tags


# ── C. generate_effect_tags ──

def generate_effect_tags(
    event_data: dict, result: dict,
    state_before: dict, state_after: dict,
) -> list[str]:
    """从处理结果 + 前后状态快照生成影响标签。纯函数，确定性，零 LLM。"""
    result = result or {}
    state_before = state_before or {}
    state_after = state_after or {}
    tags: list[str] = []

    # 1. 压力 delta
    s_before = _extract_stress(state_before)
    s_after = _extract_stress(state_after)
    delta = s_after - s_before
    if abs(delta) > 0.01:
        sign = "+" if delta > 0 else ""
        tags.append(f"stress:{sign}{delta:.2f}")
    else:
        tags.append("stress:stable")

    # 2. 依恋变化
    att_b = state_before.get("attachment_style", "")
    att_a = state_after.get("attachment_style", "")
    if att_a and att_b != att_a:
        tags.append(f"attachment:toward_{att_a}")

    # 3. 能力变化
    caps_b = set(state_before.get("capabilities", []))
    caps_a = set(state_after.get("capabilities", []))
    for cap in sorted(caps_a - caps_b):
        tags.append(f"capability:unlock:{cap}")

    # 4. 回退检测
    reg_before = state_before.get("regressed_capabilities", [])
    reg_after = state_after.get("regressed_capabilities", [])
    before_names = {
        (r.get("capability", r) if isinstance(r, dict) else r)
        for r in reg_before
    }
    for reg in reg_after:
        name = reg.get("capability", reg) if isinstance(reg, dict) else reg
        if name not in before_names:
            tags.append(f"capability:regress:{name}")

    # 5. 情绪效价
    valence = result.get("emotional_valence", "neutral")
    if valence not in ("positive", "negative", "neutral"):
        valence = "neutral"
    tags.append(f"memory:{valence}")

    # 6. 成长信号
    growth = result.get("growth_signal", "")
    if growth:
        tags.append(f"growth:{growth}")

    # 7. 偏好/恐惧变化
    for key, prefix in (("preferences", "preference"), ("fears", "fear")):
        before = set(state_before.get(key, []))
        after = set(state_after.get(key, []))
        for item in sorted(after - before):
            tags.append(f"{prefix}:add:{item}")

    return tags


# ── D. rebuild_tags_from_memory ──

def rebuild_tags_from_memory(memory=None, identity=None) -> tuple[list[str], list[str]]:
    """从已有 Memory 反推因果标签（尽力而为，旧数据兼容）。"""
    if memory is None:
        return [], []

    cause_tags: list[str] = []
    effect_tags: list[str] = []

    # cause: trace 字段关键词匹配
    trace = (getattr(memory, "trace", "") or "").lower()
    for sense in ALL_SENSES:
        if sense in trace:
            cause_tags.append(f"sensory_related:{sense}")
    if "arousal" in trace:
        cause_tags.append("arousal:related")
    if "defect" in trace or "impair" in trace:
        cause_tags.append("defect:related")

    # cause: 阶段上下文
    phase = getattr(memory, "phase", None)
    if phase is not None:
        cause_tags.append(f"phase:{phase}")

    # cause: identity 辅助，从事件名推断感官匹配
    if identity is not None:
        sp = getattr(identity, "sensory_profile", None)
        event_name = (getattr(memory, "event", "") or "").lower()
        if sp and event_name:
            dominant = getattr(sp, "dominant", "")
            weak = getattr(sp, "weak", "")
            for sense in ALL_SENSES:
                if sense in event_name or any(
                    a in event_name for a, t in SENSORY_ALIASES.items() if t == sense
                ):
                    if sense == dominant:
                        cause_tags.append(f"sensory_dominant:{sense}")
                    if sense == weak:
                        cause_tags.append(f"sensory_weak:{sense}")

    # effect: 情绪效价
    valence = getattr(memory, "emotional_valence", "neutral") or "neutral"
    effect_tags.append(f"memory:{valence}")

    # effect: 成长信号
    growth = getattr(memory, "growth_signal", "") or ""
    if growth:
        effect_tags.append(f"growth:{growth}")

    # effect: 强度推断压力方向
    intensity = getattr(memory, "intensity", 0.0) or 0.0
    if intensity > 0.6:
        effect_tags.append("stress:likely_increase")
    elif intensity < 0.2:
        effect_tags.append("stress:likely_stable")

    return cause_tags, effect_tags


# ── 内部工具函数 ──

def _get_channels(event_data: dict) -> list[str]:
    """从事件数据提取感官通道列表。"""
    channels = event_data.get("sensory_channels", [])
    if isinstance(channels, str):
        channels = [channels]
    return [ch for ch in channels if isinstance(ch, str)]


def _get_float(data: dict, key: str, default: float = 0.0) -> float:
    """安全提取浮点值。"""
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_stress_level(state) -> float:
    """从 BabyState 提取压力值（兼容 dict 和 dataclass）。"""
    stress_obj = getattr(state, "stress", None)
    if stress_obj is not None:
        level = getattr(stress_obj, "stress_level", None)
        if level is not None:
            try:
                return float(level)
            except (TypeError, ValueError):
                pass
    level = getattr(state, "stress_level", None)
    if level is not None:
        try:
            return float(level)
        except (TypeError, ValueError):
            pass
    return 0.0


def _extract_stress(snapshot: dict) -> float:
    """从状态快照 dict 提取压力值。"""
    stress = snapshot.get("stress", {})
    val = stress.get("stress_level", 0.0) if isinstance(stress, dict) else snapshot.get("stress_level", 0.0)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
