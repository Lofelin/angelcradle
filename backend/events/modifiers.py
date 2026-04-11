"""
事件权重调制器——基于身份和阶段状态动态调制事件权重。

_compute_affinity: 基于感官画像 + 唤醒基线计算宝宝对事件的亲和度
_phase_weight_modifier: 基于阶段和压力状态调制事件权重（纯规则，无 LLM）

[INPUT]: events.Event, cradle/state.py Identity/BabyState
[OUTPUT]: _compute_affinity, _phase_weight_modifier
[POS]: 权重调制层，被 cradle/events.py roll_events() 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

from events import Event


def _compute_affinity(event: Event, identity) -> float:
    """
    Compute baby's affinity to an event — identity-modulated weight.

    High sensitivity channels → related events more likely to be "noticed".
    High arousal baseline → all event probabilities increase.

    Uses weighted average instead of max: a deaf baby won't trigger hearing events
    just because their vision is good.
    """
    sp = identity.sensory_profile

    # 感官亲和度：对事件所有通道的加权平均
    if event.sensory_channels:
        channel_scores = [getattr(sp, ch, 0.5) for ch in event.sensory_channels]
        sensory_affinity = sum(channel_scores) / len(channel_scores)
    else:
        sensory_affinity = 0.5

    # 唤醒基线调制
    arousal_mod = {"high": 1.4, "moderate": 1.0, "low": 0.7}
    arousal = arousal_mod.get(identity.arousal_baseline, 1.0)

    return round(sensory_affinity * arousal, 3)


def _phase_weight_modifier(event: Event, phase_index: int, state=None) -> float:
    """根据阶段和状态动态调制事件权重。纯规则，无 LLM。"""
    mod = 1.0
    if state is None:
        return mod

    # 睡眠回归高发期
    if event.name == "sleep_regression" and phase_index in (2, 3, 6, 7):
        mod *= 3.0

    # Tantrum 频率曲线
    if event.name == "tantrum_trigger":
        tantrum_curve = {6: 1.0, 7: 1.8, 8: 1.0, 9: 0.4}
        mod *= tantrum_curve.get(phase_index, 0.3)

    # 压力高时高强度事件更敏感
    stress = getattr(state, "stress", None)
    if stress and stress.stress_level > 0.5 and event.intensity > 0.5:
        mod *= 1.3

    return mod
