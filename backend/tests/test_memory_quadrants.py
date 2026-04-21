"""
四象限测试矩阵（D1-5）：
  V2=on  × memories 有 旧数据 / 无 旧数据
  V2=off × memories 有 旧数据 / 无 旧数据

全部场景下 API 表面行为保持稳定：无 crash、state.memories 完整、降级回写不破坏。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from cradle.state import BabyState, save_state, load_state, Memory   # noqa: E402
from memory import (  # noqa: E402
    record_moment,
    recall,
    is_v2_enabled,
    count_life_moments,
    load_life_moments,
    self_heal,
    RecalledContext,
)


def _new_baby(baby_id: str, with_legacy_memories: bool = False) -> BabyState:
    st = BabyState(baby_id=baby_id, current_phase=3, age_days=500, sim_time=12000.0)
    if with_legacy_memories:
        # 模拟老 baby：state.memories 有 2 条但无对应 life_moments.jsonl
        st.memories.append(Memory(
            phase=3, age_days=400, event="legacy_event_a",
            stimulus="旧刺激", reaction="旧反应",
            trace="旧 trace", emotional_valence="neutral", intensity=0.5,
        ))
        st.memories.append(Memory(
            phase=3, age_days=450, event="legacy_event_b",
            stimulus="另一旧刺激", reaction="旧反应2",
            trace="", emotional_valence="positive", intensity=0.6,
        ))
    save_state(st)
    return st


def _cleanup(baby_id: str) -> None:
    d = BACKEND_ROOT / "archive" / baby_id
    if d.exists():
        shutil.rmtree(d)


def _quadrant_on_with_legacy() -> None:
    """V2=on + 有旧 memories：首次 record_moment 正常；recall 优先相关性；不变量"""
    os.environ["MEMORY_V2"] = "on"
    baby_id = "TEST-QUAD-on-legacy"
    _cleanup(baby_id)
    st = _new_baby(baby_id, with_legacy_memories=True)

    assert is_v2_enabled()
    assert len(st.memories) == 2
    # 写一条新 moment
    m = record_moment(st, baby_id, actor="world", target="self",
                      trigger="new_event", action="新事件发生",
                      intensity=0.7, cause_tags=["phase:3"])
    assert m is not None
    # state.memories 增长到 3，jsonl 有 1 条（老 memories 没进 jsonl）
    assert len(st.memories) == 3
    assert count_life_moments(baby_id) == 1

    # recall 可以正常工作（即使老 memories 没进 jsonl）
    rc = recall(st, context="新", current_tags=set(), token_budget=1000)
    assert isinstance(rc, RecalledContext)
    assert len(rc.episodic) >= 1

    _cleanup(baby_id)
    print("  [V2=on + legacy] OK")


def _quadrant_on_no_legacy() -> None:
    """V2=on + 无旧 memories：新 baby 从零生长，不变量严格"""
    os.environ["MEMORY_V2"] = "on"
    baby_id = "TEST-QUAD-on-fresh"
    _cleanup(baby_id)
    st = _new_baby(baby_id, with_legacy_memories=False)

    assert len(st.memories) == 0
    # 写 3 条
    for i in range(3):
        record_moment(st, baby_id, actor="world", target="self",
                      trigger=f"evt_{i}", action=f"事件 {i}",
                      intensity=0.6 + i * 0.1)

    assert len(st.memories) == 3
    assert count_life_moments(baby_id) == 3
    # 不变量：新 baby 下 state.memories 和 life_moments 数量严格相等
    assert len(st.memories) == count_life_moments(baby_id)

    _cleanup(baby_id)
    print("  [V2=on + fresh] OK + 不变量严格")


def _quadrant_off_with_legacy() -> None:
    """V2=off + 有旧 memories：走旧路径，不触 life_moments.jsonl"""
    os.environ["MEMORY_V2"] = "off"
    baby_id = "TEST-QUAD-off-legacy"
    _cleanup(baby_id)
    st = _new_baby(baby_id, with_legacy_memories=True)

    assert not is_v2_enabled()
    assert len(st.memories) == 2
    # recall 走 _legacy_recall（返回 semantic，episodic 为空）
    rc = recall(st, context="", current_tags=set(), token_budget=1000)
    assert rc.episodic == []
    # 不应创建 life_moments.jsonl（因为 recall 不会写）
    # ——注意：record_moment 无论 V2 开关都会写 jsonl，这是有意设计（避免切换时数据丢失）
    # V2=off 只影响读路径
    _cleanup(baby_id)
    print("  [V2=off + legacy] OK (read goes legacy path)")


def _quadrant_off_no_legacy() -> None:
    """V2=off + 无旧 memories：完全空场景不崩"""
    os.environ["MEMORY_V2"] = "off"
    baby_id = "TEST-QUAD-off-fresh"
    _cleanup(baby_id)
    st = _new_baby(baby_id, with_legacy_memories=False)

    rc = recall(st, context="", current_tags=set(), token_budget=1000)
    assert rc.episodic == []
    assert rc.milestones == []
    _cleanup(baby_id)
    print("  [V2=off + fresh] OK")


def _self_heal_scenario() -> None:
    """崩溃恢复：jsonl 有 2 条 state.memories 只有 1 条 → self_heal 补齐 1 条"""
    os.environ["MEMORY_V2"] = "on"
    baby_id = "TEST-SELFHEAL"
    _cleanup(baby_id)
    st = _new_baby(baby_id)

    # 写 2 条（state.memories 应该有 2 条）
    record_moment(st, baby_id, actor="world", target="self",
                  trigger="e1", action="事件1", intensity=0.6)
    record_moment(st, baby_id, actor="world", target="self",
                  trigger="e2", action="事件2", intensity=0.7)
    assert len(st.memories) == 2
    assert count_life_moments(baby_id) == 2

    # 模拟 Step 3 成功 Step 4 失败的场景：手工砍掉 state.memories 最后一条
    st.memories = st.memories[:-1]
    assert len(st.memories) == 1
    assert count_life_moments(baby_id) == 2   # jsonl 仍有 2 条

    # self_heal 应补齐
    repaired = self_heal(st, baby_id)
    assert repaired == 1, f"expected repair 1, got {repaired}"
    assert len(st.memories) == 2
    print("  [self_heal] OK (崩溃恢复补齐 1 条)")

    _cleanup(baby_id)


def main() -> int:
    print("四象限测试：")
    _quadrant_on_with_legacy()
    _quadrant_on_no_legacy()
    _quadrant_off_with_legacy()
    _quadrant_off_no_legacy()
    print("自检测试：")
    _self_heal_scenario()
    # 重置环境变量防止污染
    os.environ.pop("MEMORY_V2", None)
    print("\n四象限 + 自检全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
