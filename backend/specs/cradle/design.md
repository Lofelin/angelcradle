# 技术设计：摇篮（Cradle）

## 1. 模块结构

```
backend/cradle/
├── __init__.py      ← admit(), check_world_readiness()
├── phases.py        ← 12 阶段定义 + 表达模式 + 世界就绪条件
├── state.py         ← BabyState/Identity/Memory/Milestone 数据模型 + 持久化
├── events.py        ← 事件定义（7日常 + 15环境 + 10关键）+ 掷骰
├── identity.py      ← 身份编译器（gestation_log → Identity）
├── mind.py          ← 认知反应系统（感知过滤 + LLM 调用）
└── nanny.py         ← 保姆引擎（阶段模拟 + 能力解锁 + 里程碑）

backend/api/cradle.py ← 9 个 API 端点
```

## 2. 数据模型 — `state.py`

### SensoryProfile
```python
hearing: float      # 0.0-1.0
vision: float
touch: float
smell: float
proprioception: float
dominant: str       # 主导感官
weak: str           # 薄弱感官
```

### Identity（出生即锁定）
```python
sensory_profile: SensoryProfile
arousal_baseline: str           # low / moderate / high
reflex_patterns: list[dict]     # 从 early_neural 提取
instinct_loops: list[dict]      # 从 late_neural 提取
temperament: str                # 从 fetal_movement 提取
tendencies: list[str]           # 从 birth 的 genes.expression
defects: list[str]              # 先天缺陷
constraints: list[str]          # 编译的行为约束（自然语言）
```

### BabyState（持续演化）
```python
baby_id, species, name
identity: Identity              # 锁定
current_phase: int              # 0-11
age_days: int
capabilities: list[str]         # 已解锁能力
expression_mode: str            # 当前表达模式
attachment_style: str           # secure / anxious / avoidant / forming
fears, preferences, comfort_sources: list[str]
memories: list[Memory]
milestones: list[Milestone]
parent_profile: ParentProfile
phase_summaries: list[dict]
```

### 持久化
- 路径: `backend/nursery/{baby_id}/state.json`
- 格式: 完整 BabyState JSON
- 时机: 每次状态变更后自动保存

## 3. 身份编译 — `identity.py`

两步编译：

**步骤 1: 规则提取（无 LLM）**
- 感官画像: 从 gestation_log 所有阶段的 resource_allocation + late_organogenesis 的 primary/weak_sense
- 唤醒基线: 从 late_neural 和 fetal_movement 的文本关键词匹配
- 反射: 从 early_neural 的 reflexes 字段直接读取
- 本能回路: 从 late_neural 的 instinct_loops 字段直接读取
- 气质: 从 fetal_movement 的 temperament_seed 字段

**步骤 2: 约束生成（一次 LLM 调用）**
- 输入: 步骤 1 的所有提取数据
- 输出: 5-8 条行为约束（自然语言规则）
- 降级: LLM 不可用时用规则生成基础约束

## 4. 事件系统 — `events.py`

### 三类事件

| 类型 | 数量 | 处理方式 | LLM 调用 |
|------|------|---------|---------|
| 日常 | 7 种 | 规则引擎（强度 × 灵敏度 × 唤醒修正） | 0 |
| 环境 | 15 种 | 批量 LLM（一个阶段所有环境事件打包） | 1/阶段 |
| 关键 | 10 种 | 单独 LLM + 父母介入 | 1/事件 |

### 感知过滤公式
```
感知强度 = 事件强度 × 感官灵敏度
唤醒修正 = {high: 1.3, moderate: 1.0, low: 0.7}
总感知强度 = Σ(各通道感知强度) × 唤醒修正
```

### 掷骰机制
- 日常: 每阶段随机 3 个
- 环境: 每阶段加权随机 2 个
- 关键: 每个独立判定（概率 = weight × 0.3）

## 5. 保姆模拟循环 — `nanny.py`

```
simulate_phase(state)
    ├── 更新日龄和表达模式
    ├── roll_events() → 掷骰生成事件
    ├── _process_daily_events() → 规则引擎
    ├── process_environment_events() → 一次 LLM
    ├── 关键事件标记为待处理 → 返回给调用方
    ├── _check_capability_unlocks() → 解锁能力
    └── _check_milestones() → 检测里程碑

resolve_critical_event(state, event, action)
    ├── process_critical_event() → 一次 LLM
    ├── 更新恐惧/偏好/安慰源
    ├── _update_attachment() → 依恋更新
    └── _update_parent_profile() → 父母画像更新

complete_phase(state)
    ├── generate_phase_summary() → 一次 LLM
    ├── 记录阶段总结
    └── 推进到下一阶段
```

## 6. LLM 调用策略

| 场景 | 调用次数 | Prompt 策略 |
|------|---------|-------------|
| 身份编译 | 1 次 | 完整发育数据 → 5-8 条行为约束 |
| 环境事件 | 1 次/阶段 | 批量所有环境事件 → 逐个反应 |
| 关键事件 | 1 次/事件 | 单个事件 + 父母行为 → 详细反应 |
| 阶段总结 | 1 次/阶段 | 阶段回顾 → 发育总结 |

**关键约束注入**: 每次 LLM 调用都注入身份约束、表达模式、当前能力列表，确保输出一致性。

## 7. API 端点 — `api/cradle.py`

| 端点 | 方法 | 说明 |
|------|------|------|
| `/cradle/admit` | POST | 婴儿入摇篮 |
| `/cradle/babies` | GET | 列出摇篮中所有婴儿 |
| `/cradle/{id}/status` | GET | 当前状态 |
| `/cradle/{id}/advance` | POST | 推进阶段（同步） |
| `/cradle/{id}/advance/stream` | GET | 推进阶段（SSE 流） |
| `/cradle/{id}/intervene` | POST | 父母介入 |
| `/cradle/{id}/complete` | POST | 完成阶段，生成总结 |
| `/cradle/{id}/history` | GET | 完整成长历史 |
| `/cradle/{id}/readiness` | GET | 世界就绪检查 |

## 8. 依恋类型模型

```
secure    ← 响应性行为（comfort, hold, validate, explain_return）
avoidant  ← 忽视行为（let_cry, ignore, sneak_away）
anxious   ← 不一致行为（混合响应和忽视）
forming   ← 初始状态，尚未形成
```

平衡性行为（encourage, boundary, negotiate, gradual）倾向于产生安全依恋。
