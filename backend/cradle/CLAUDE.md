# cradle/
> L2 | 父级: /CLAUDE.md

摇篮模块——将子宫产出的 Baby 从出生培养到可以进入世界。
12 个成长阶段，保姆自动照料，随机事件塑造个性，父母在关键时刻介入。

## 成员清单

phases.py: 12 阶段定义 + 10 种表达模式（cry_only → independent）+ 世界就绪条件
state.py: 数据模型（BabyState/Identity/SensoryProfile/Memory/Milestone/ParentProfile）+ nursery/ 持久化 + simulated_phases 幂等保护
events.py: 事件系统（7 日常 + 15 环境 + 10 关键）+ roll_events() 掷骰，身份调制用加权平均
identity.py: 身份编译器，gestation_log → Identity（规则提取 + LLM 约束生成 + 降级）
mind.py: 认知反应系统（感知过滤 + 统一叙事 + 关键事件 + 阶段总结），LLM 失败安全降级（返回 None）
nanny.py: 保姆引擎（simulate_phase + resolve_critical_event + complete_phase），缺陷→能力约束映射（DEFECT_BLOCKED/DELAYED_CAPABILITIES）+ LLM 超时保护 + 幂等性检查

## 对外暴露

```python
from cradle import admit, check_world_readiness, load_state, list_cradle_babies
from cradle import simulate_phase, resolve_critical_event, complete_phase
from cradle import PHASES
```

## 依赖关系

- womb/genetics.py: 复用 _create_client, _call_llm, _parse_json, PROVIDERS
- api/registry.py: 加载出生数据（延迟导入避免循环依赖）

## 数据流

```
Baby JSON (births/) → admit() → Identity 编译 → BabyState (nursery/)
    → simulate_phase() → 事件掷骰 → 日常(规则) + 环境(LLM) + 关键(等父母)
    → resolve_critical_event() → 父母介入 → 状态更新
    → complete_phase() → 阶段总结 → 推进下一阶段
    → check_world_readiness() → 进入世界
```

[PROTOCOL]: 变更时更新此文档，然后检查 CLAUDE.md
