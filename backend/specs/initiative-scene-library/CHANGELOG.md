# initiative-scene-library · 变更记录

## 2026-04-20 · 首次交付（Phase A）

### 起因

真实 bug：`AC-20260417-34518` (phase=8 narrative, 3 岁) 的 scheduler `rule_based_need` 
产出 `*Fussing*` 新生儿级表达（事件 seq=15）。追踪到根因是 `scheduler/needs.py:210-234` 
把 12 阶段粗暴折叠成 3 档（`phase<=1` / `phase<=3` / `phase>3`），表达 vocabulary 硬编码，
违反 `phases.py:3` 设计原则"阶段不是时间轴是能力检查点"。

### 用户要求

- **主动行为必须和阶段匹配**（因为没有具体年龄，子宫也是阶段推进的）
- **每个阶段 ≥ 50 个主动行为场景**（12 阶段 × 50 = 600+）

### 前置决策（Q1-Q5）

| 问题 | 决策 |
|---|---|
| Q1 场景原子粒度 | (a) trigger 相同但 context/expression 不同 = 独立场景 |
| Q2 产出方式 | M2 本模型单轮生成 + 审核一步完成 |
| Q3 存储格式 | JSON |
| Q4 LLM 路径也用 few-shot | 是 |
| Q5 分期 | 全量 600+ 一次 |

## 一、新增

### 1.1 `backend/scenes/` 模块

```
backend/scenes/
├── schema.py                   InitiativeScene dataclass（10 字段）
├── __init__.py                 加载门面：load_scenes_for_phase / pick_scene / count_scenes / all_scenes
├── CLAUDE.md                   L2 文档
└── data/                       12 个 JSON 数据文件
```

### 1.2 603 条场景 JSON（每阶段 50+）

| phase | name | expression_mode | scene count | trigger 分布要点 |
|---|---|---|---|---|
| 0 | neonatal | cry_only | 50 | 生理 45 + 情绪 5 |
| 1 | sensory_awakening | coo_and_gaze | 50 | 生理 + fear/lonely 首现 |
| 2 | body_discovery | babble_and_reach | 53 | + curious/play（hand discovery） |
| 3 | object_permanence | gesture_and_point | 50 | **stranger_anxiety 峰值**（fear×8） |
| 4 | locomotion | first_words | 50 | **首真实词里程碑**（单词级） |
| 5 | first_word | two_word | 50 | 工具使用 + 步行 |
| 6 | language_explosion | sentence | 50 | self_recognition + pretend |
| 7 | why_phase | sentence | 50 | why×12 + 情绪风暴 |
| 8 | social_budding | narrative | 50 | 同伴意识 + 道德萌芽 |
| 9 | rule_understanding | reasoning | 50 | **autonomy×12 峰值** + boundary |
| 10 | abstract_beginning | reasoning | 50 | 类比 + 时间 + 假设 |
| 11 | independence | independent | 50 | 独立意见 + 辩论 |

### 1.3 Spec 文档

`backend/specs/initiative-scene-library/`
- `proposal.md` — 动机 / 目标 / 范围 / Q1-Q5 决策 / 成功标准
- `design.md` — Schema / 12 阶段 trigger 分布矩阵 / 接入点 / 单测
- `tasks.md` — 分 6 组任务清单 + 死罪清单
- `CHANGELOG.md` — 本文档

## 二、改动

### 2.1 `scheduler/needs.py:rule_based_need`

**废弃**：硬编码 `triggers` 3 档 + `vocalizations` 3 档（约 40 行 if/else）

**改为**：从场景库采样
```python
from scenes import pick_scene
scene = pick_scene(phase=state.current_phase, trigger=?)
# 高压力时 preferred_triggers = [fear/pain/lonely/gas_colic/overstimulated]
# 返回透传 scene.expression / signal / facial / body / default_tags
```

**影响**：rule_based_need 不再写死 `*Fussing*` / `*Waah!*`——全部来自场景库，表达严格匹配 phase。

### 2.2 `cradle/mind.py:generate_heartbeat_evaluation`

**新增**：prompt 注入 3-4 条同 phase 场景作为 few-shot

```python
from scenes import load_scenes_for_phase
sample = random.sample(phase_scenes, min(4, len(phase_scenes)))
few_shot_block = "## Example Scenes for This Phase (few-shot — follow this style)\n..."
```

**影响**：LLM 看到当前阶段应有的表达风格，降低"narrative 阶段 LLM 输出 cry_only 表达"的违规率。

## 三、验证矩阵（全绿）

| 检查项 | 结果 |
|---|---|
| 每阶段 ≥ 50 条 | ✓ 总 603 |
| 所有 trigger ∈ `initiative_needs.TRIGGER_URGENCY` 枚举（19 种）| ✓ |
| 所有 expression 通过 `cradle.mind._validate_expression_output` 静态校验 | ✓ |
| phase 0 (neonatal) 无 autonomy 场景 | ✓ |
| phase 11 (independence) 无 teething 场景 | ✓ |
| scene id 全局唯一 | ✓ |
| `pick_scene` 轮转 10 次拿到 10 条不同 | ✓ |
| 模块导入不破坏 scheduler / cradle / api | ✓ |
| **原 bug 修复**：phase=8 采样不再产出 `*Fussing*` | ✓ 实测产出 narrative 阶段合理表达 |

### 用户 bug 修复前后对照

| 维度 | 修复前（2026-04-17） | 修复后（2026-04-20） |
|---|---|---|
| phase=8 trigger=too_cold | `*Fussing*` | `pick_scene(phase=8)` 产出 narrative 风格：`'Who is God? Does God live in the sky? Can God see us now?'` |
| 表达源 | 硬编码 5 句新生儿 vocabulary | 50 条 phase 8 narrative 场景 |
| 阶段匹配 | 12 阶段 → 3 档 | 12 阶段 → 12 独立场景库 |

## 四、与长期记忆系统对齐（memory/ 模块）

- 每条场景的 `default_tags` 透传到 `need["cause_tags"]`
- 上游 `record_moment(state, baby_id, trigger=scene.trigger, cause_tags=scene.default_tags)` 
  自动带上 `phase:N` 等 tag，tag 一跳倒排能跨阶段关联同语义场景
- `intent_id="rule-{day}-{scene.id}"` 使 events.jsonl 里可追溯到具体场景源
- LifeMoment `is_first` 字段配合 `state.triggered_events` 去重——首次触发场景获得 high intensity

## 五、死罪清单（禁止触碰）

- ❌ 禁止在 scenes/data 以外的地方写死 vocabulary 数组
- ❌ 禁止某阶段场景数 < 50
- ❌ 禁止 scene.trigger 不在 TRIGGER_URGENCY 枚举
- ❌ 禁止 cry_only 阶段场景的 expression 含真实词汇
- ❌ 禁止 first_words 阶段场景超过 3 词单元（first_words 3 / two_word 6 / sentence+ 不限）
- ❌ 禁止 scene id 重复

## 六、观察期 + 后续

- 上线后手工观察哪些场景被频繁命中、哪些从未采样
- 淘汰低价值 + 补充高需求场景（需求触发后续 spec change）
- 未来 v2 候选扩展：按 `birthplace` 增加文化化场景（春节 / 圣诞节 / 排灯节等）
- 性别差异 / 文化差异本次**不做**（非目标）

## 交付物索引

### 代码
- `backend/scenes/__init__.py` · `schema.py` · `CLAUDE.md`（3 文件）
- `backend/scheduler/needs.py`（rule_based_need 改造）
- `backend/cradle/mind.py`（generate_heartbeat_evaluation few-shot 注入）

### 数据
- `backend/scenes/data/phase_00_neonatal.json` ~ `phase_11_independence.json`（12 文件，603 条）

### 文档
- `backend/specs/initiative-scene-library/proposal.md` · `design.md` · `tasks.md` · `CHANGELOG.md`

### 验证
- 端到端烟测 8 项全绿（含用户 bug 修复验证）
