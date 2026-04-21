# 变更提案：主动行为场景库（initiative-scene-library）

## 动机

`AC-20260417-34518` 事件日志暴露真实 bug：

```
seq=15 ts=1776418724 age_days=1 phase=neonatal event=baby_need
  trigger=too_cold expression=*Fussing* need_id=rule-0-too_cold
```

这条合理（新生儿生理需求触发 cry_only 表达），但同一代码路径在 phase=8（`narrative`，3 岁）时仍会产出 `*Fussing*` / `*Waah!*` 这种新生儿级表达——因为 `scheduler/needs.py:rule_based_need` 把 12 阶段粗暴折叠成 3 档（`phase<=1` / `phase<=3` / `phase>3`），违反 `phases.py:3` 的设计原则"阶段不是时间轴是能力检查点"。

更深层：LLM 路径（`heartbeat.evaluate_heartbeat` → `generate_heartbeat_evaluation`）虽然按 `expression_mode` 做了约束，但**无阶段场景库** few-shot，输出质量完全靠 LLM 即兴，可控性差。

## 目标

- **12 阶段 × 每阶段 ≥ 50 条** = **600+ 主动行为场景**（用户明确数量要求）
- 每条场景原子结构含 trigger / context / expression / signal / facial / body / intent / parent_hint
- 表达严格遵守对应 `expression_mode`（cry_only 不能用词 / first_words 必须真实中文词 / narrative 必须完整句）
- trigger 分布按发育生物学（neonatal 无 autonomy / pre-school 无 teething）
- 规则路径（`rule_based_need`）改为从场景库按 phase 精准采样
- LLM 路径（`generate_heartbeat_evaluation`）prompt 注入 3-5 条同阶段场景做 few-shot
- 产出的主动行为通过 `memory.record_moment` 写入 `actor=self` 的 LifeMoment，与上游长期记忆系统对齐

## 范围

### 包含

- 新增 `backend/scenes/` 数据目录 + 12 个 JSON 文件（每阶段一个，≥50 条）
- 新增 `backend/scenes/` Python 加载模块（懒加载 + in-memory 缓存 + `pick_scene(phase, trigger?, exclude_recent?)`）
- 场景 JSON Schema 锁定字段
- `scheduler/needs.py:rule_based_need` 改造：按 phase 从场景库采样
- `cradle/mind.py:generate_heartbeat_evaluation` 改造：prompt 注入场景 few-shot
- 单测：覆盖率 ≥50/阶段 + 表达合法性（正则匹配 expression_mode 格式）+ trigger 合法性（在 TRIGGER_URGENCY 枚举内）
- 对齐 `memory.record_moment`：每条场景产出主动行为时自动写 LifeMoment（actor=self, trigger=scene.trigger）

### 不包含

- 不改 `EXPRESSION_MODES` / `TRIGGER_URGENCY` 枚举（复用现有）
- 不改 `_SIGNALS` / `_ACTIONS` 常量（nanny_fallback 路径保留，与场景库并行）
- 不做"场景推荐"机器学习（纯规则 + 加权随机）
- 不做 600 条的 LLM 批量生成脚本（由本次变更一次性人工审校产出，交付后只增不减）
- 不做前端 UI 展示场景库（后端数据层）

## Q1-Q5 决策（已拍板）

| 问题 | 决策 |
|---|---|
| Q1 场景原子粒度 | (a) trigger 相同但 context/signal/expression 不同 = 不同场景 |
| Q2 产出方式 | 本模型（Claude）单轮生成 + 审核一步完成（等效 M3 压缩） |
| Q3 存储格式 | JSON |
| Q4 LLM 路径也用 few-shot | 是 |
| Q5 分期 | 全量 600+ 一次完成 |

## 成功标准

- 每个 `scenes/phase_*.json` 含 ≥ 50 条 `InitiativeScene`
- 所有场景 `trigger ∈ TRIGGER_URGENCY.keys()`（19 种枚举）
- 所有场景的 `expression` 通过对应 phase 的 `_validate_expression_output` 静态校验（cry_only 无词汇 / first_words 有真实中文词等）
- `rule_based_need` 不再写死 `*Fussing*`/`*Waah!*` 之类硬编码 vocabulary——全部来自场景库
- `generate_heartbeat_evaluation` prompt 里 `## Example Scenes for This Phase` 块非空
- 现有 2 个 baby (`AC-20260417-14297` / `AC-20260417-34518`) 加载和跑通 SSE 零破坏
- 代码增量：加载模块 ≤ 150 行 + 改造点 ≤ 80 行（主要工作量是数据 JSON）

## 非目标

- **不做**情感微表情库（留给 v2 增强）
- **不做**文化/地域差异（当前所有 baby 共享场景库，不按 birthplace 分化）
- **不做**性别差异（phenotype 不影响场景选择）
- **不做**自动化覆盖率统计 dashboard（一次性单测即可）

## 和 long-term-memory 的关系

- 每次规则/LLM 产出主动行为 → 走 `memory.record_moment(actor="self", trigger=scene.trigger, action=scene.expression, cause_tags=[f"phase:{N}", ...])`
- 场景库的 trigger/context 会让 LifeMoment 的 tag 更有发育学语义，recall 时 tag 一跳能跨阶段命中相关经验
- 没有双源数据冲突（场景库是"行为模板"，LifeMoment 是"实际发生"）
