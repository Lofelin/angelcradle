# cradle/
> L2 | 父级: /CLAUDE.md

摇篮模块——将子宫产出的 Baby 从出生培养到可以进入世界。
12 个成长阶段，保姆自动照料，随机事件塑造个性，多照护者在关键时刻介入。
六大维度增强：压力回退/恢复、喂养睡眠、情绪调节、体格发育、照护者画像、动态事件权重。

## 成员清单

phases.py: 12 阶段定义 + 10 种表达模式（cry_only → independent）+ 世界就绪条件
state.py: 数据模型（BabyState/Identity/SensoryProfile/Memory/Milestone/CaregiverProfile/StressState/NutritionSleepState/EmotionalState/PhysicalState）+ nursery/ 持久化（原子写入: tempfile+os.replace）+ baby_id 白名单校验（防路径遍历）+ simulated_phases 幂等保护 + 旧 ParentProfile 兼容迁移 + 自驱动生命字段（life_tags/last_active_ts/sim_time/time_scale）+ update_age_from_sim_time() 映射
events.py: thin wrapper over events/ 包，保持 roll_events() 原签名向后兼容，事件定义/权重调制已迁移至 events.definitions / events.modifiers
identity.py: 身份编译器，gestation_log → Identity（规则提取 + LLM 约束生成 + 降级）
mind.py: 认知反应系统（感知过滤 + 统一叙事 + 关键事件 + 阶段总结），四个 LLM prompt 均扩展上下文（压力/回退/情绪/体格/照护者），generate_interaction_response 支持 action_type（message/touch）+ touch_description 参数 + 表达模式后验证（_validate_expression_output：cry_only~gesture_and_point 禁止真实词汇，first_words/two_word 限制词单元数），肢体互动优先触觉反应，generate_phase_summary 输出新增 stress_note/physical_note 字段，LLM 失败或表达违规时安全降级为预设反应
touch.py: 肢体互动动作定义（23 个动作，5 类：抚触/拥抱/亲昵/安抚/游戏），每个动作有阶段范围限制确保适龄，get_available_actions(phase) 按类别分组返回可用动作
nanny.py: 保姆引擎（simulate_phase + resolve_critical_event + complete_phase + grow_stream 含心跳注入），缺陷→能力约束映射 + _update_stress/_check_stress_regression/_check_regression_recovery/_update_phase_state/_update_caregiver_profile + 6 个新里程碑定义 + LLM 超时保护 + 幂等性检查。压力衰减按阶段天数计算（0.995^days），喂养模式按 age_days 判断（对齐 WHO 指南），依附同步显式查找 primary_parent，生长曲线身高/体重独立 10% 方差。grow_stream 在 phase_simulated 后注入 heartbeat 评估（heartbeat_initiative/heartbeat_ignored SSE 事件）
heartbeat_provider.py: 心跳适配器，实现 MonologueProvider 协议。CRADLE_BEHAVIORS（12 阶段行为空间数据）+ CradleMonologueProvider（build_inner_monologue 构造英文内心独白供 LLM 判断）+ shift_attachment_toward_avoidant（忽略导致依恋偏移）。延迟导入 nanny/state 避免循环依赖。

## 对外暴露

```python
from cradle import admit, check_world_readiness, load_state, list_cradle_babies
from cradle import simulate_phase, resolve_critical_event, complete_phase
from cradle import PHASES
from cradle.state import CaregiverProfile
from cradle.touch import TOUCH_ACTIONS, get_available_actions
from cradle.heartbeat_provider import CradleMonologueProvider, CRADLE_BEHAVIORS, shift_attachment_toward_avoidant
```

## 依赖关系

- events/: 共享事件基础设施（Event 数据类 + 事件定义 + 权重调制器），cradle/events.py 是 thin wrapper
- womb/genetics.py: 复用 _create_client, _call_llm, _parse_json, PROVIDERS
- api/registry.py: 加载出生数据（延迟导入避免循环依赖）
- heartbeat.py: BehaviorSpace/InitiativeState 数据模型 + evaluate_heartbeat() 引擎
- scheduler.py: DES 调度器（通过 api/cradle.py 间接依赖，admit 时注册 agent）
- world.py: 世界层（日程模板 + 事件处理 + 标签规则），消费 events/ 和 cradle/state.py

## 数据流

```
阶段推进（手动触发）:
Baby JSON (births/) → admit() → Identity 编译 → BabyState (nursery/)
    → simulate_phase() → 事件掷骰（含动态权重调制）
        → 日常(规则) + 环境(LLM) + 关键(等父母)
        → _update_phase_state() → 阶段状态自动更新（喂养/睡眠/情绪/体格）
        → _update_stress() → 压力累积
        → _check_stress_regression() → 能力回退检测
        → _check_regression_recovery() → 回退恢复 + 韧性加成
    → resolve_critical_event(state, event, action, caregiver_id)
        → 父母介入 → 状态更新
        → _update_caregiver_profile() → 照护者画像更新
    → complete_phase() → 阶段总结（含 stress_note/physical_note）→ 推进下一阶段
    → check_world_readiness() → 进入世界

自驱动生命（DES 调度器持续运行）:
admit() → scheduler.register() → 生成首日日程 → 优先级队列
    → 取事件 → world.process_event()
        → 日常(规则引擎) → 状态微调 → autonomous_routine SSE
        → 有事(LLM) → 时段总结 + 记忆 → autonomous_event SSE
    → roll_emergent_event() → 可能插入涌现事件
    → sleep 事件 → 生成次日日程 → 循环
```

[PROTOCOL]: 变更时更新此文档，然后检查 CLAUDE.md
