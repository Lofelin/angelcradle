# 阶段 A 观察期记录 · long-term-memory

> 上线后 ≥ 2 周的观察窗口。每天记录一条以上 recall 样例 / 收集 bad case / 追踪 len(state.memories) 增长曲线。
> 数据足够后（见 proposal.md §阶段 B 触发条件），起 `phase-b-unify-memory` spec change。

## 上线日志

- 上线日期：（待填）
- 首批受影响 baby：`AC-20260417-14297`（3 条老 memories）/ `AC-20260417-14226`（无 state.json）
- 灰度策略：MEMORY_V2=on 默认

## 每日 recall 样例记录

### YYYY-MM-DD
- Context：
- current_tags：
- Top-K 结果：
- 是否符合直觉：✅/❌
- 备注：

## Bad Case 收集

| # | 日期 | Context | 期望 | 实际 | 归因 |
|---|---|---|---|---|---|
| 1 |   |   |   |   |   |

累计 ≥ 3 起跨阶段语义泛化 bad case 时，启动 Phase B 引入嵌入模型讨论。

## 不变量指标

| 日期 | baby_id | len(state.memories) | count_life_moments | 偏差 |
|---|---|---|---|---|
|   |   |   |   |   |

偏差必须恒等于 0；若出现偏差立即启动 self_heal 并排查调用路径。

## CI lint + 四象限测试状态

| 日期 | lint | 四象限 | self_heal | 备注 |
|---|---|---|---|---|
|   | OK/FAIL | OK/FAIL | OK/FAIL |   |

## Phase B 触发条件核对（阶段 A 结束前）

1. [ ] 双写期 ≥ 2 周
2. [ ] CI 不变量零告警
3. [ ] 四象限测试零失败
4. [ ] V2=on vs V2=off 的 mind.py prompt golden diff 稳定（可选：每日采样一份 prompt 归档）

三条全绿 → 起新 spec change `phase-b-unify-memory` 准备 deprecate state.memories 双写 + 精调神经科学参数（Wickelgren 幂律 / REM/SWS 区分 / arousal/valence 拆分）。
