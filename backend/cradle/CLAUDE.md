# cradle/
> L2 | 父级: /CLAUDE.md

摇篮模块——将子宫产出的 Baby 从出生培养到可以进入世界。
12 个成长阶段，保姆自动照料，随机事件塑造个性，多照护者在关键时刻介入。
六大维度增强：压力回退/恢复、喂养睡眠、情绪调节、体格发育、照护者画像、动态事件权重。
**自驱动阶段推进**：scheduler 检测阶段边界后自动运行阶段模拟并完成推进，关键事件收集到 pending_criticals 队列等父母随时处理，但不阻塞生命推进。BabyState.pending_criticals / phase_advancing 为持久化协调信号。

## 成员清单

phases.py: 12 阶段定义 + 10 种表达模式（cry_only → independent）+ 世界就绪条件
state.py: 数据模型（BabyState/Identity/SensoryProfile/Memory/Milestone/CaregiverProfile/StressState/NutritionSleepState/EmotionalState/PhysicalState）+ archive/ 持久化（原子写入: tempfile+os.replace）+ baby_id 白名单校验（防路径遍历）+ simulated_phases 幂等保护 + 旧 ParentProfile 兼容迁移 + 自驱动生命字段（life_tags/last_active_ts/sim_time/time_scale）+ update_age_from_sim_time() 映射。**世界上下文字段**：triggered_events（全局已触发事件名，first_X/critical 去重）+ world_snapshot（WorldSnapshot 缓存，持久化到 state.json 保证重启连续性）+ rebuild_triggered_events() 旧数据兼容重建。**事件日志基础设施**：append_event() 返回 seq（单调递增）+ threading.Lock 写入锁 + asyncio.Event 通知（get_notify）+ per-baby asyncio.Lock 状态锁（get_baby_lock）+ load_events_after(after_seq) 增量读取。Memory/Milestone.from_dict 使用防御性 d.get() 解析（容忍多余字段）
events.py: thin wrapper over events/ 包，保持 roll_events() 原签名向后兼容，事件定义/权重调制已迁移至 events.definitions / events.modifiers
identity.py: 身份编译器，gestation_log → Identity（规则提取 + LLM 约束生成 + 降级）
causality.py: 因果标签生成引擎（纯规则，零 LLM），generate_cause_tags/generate_effect_tags/rebuild_tags_from_memory，为每个事件生成 namespace:key 格式因果标签（ADR-5），所有函数纯函数确定性，参数 None 优雅降级
mind.py: 认知反应系统（感知过滤 + 统一叙事 + 关键事件 + 阶段总结），四个 LLM prompt 均扩展上下文（压力/回退/情绪/体格/照护者），generate_interaction_response 支持 action_type（message/touch）+ touch_description 参数 + 表达模式后验证（_validate_expression_output：cry_only~gesture_and_point 禁止真实词汇，first_words/two_word 限制词单元数），肢体互动优先触觉反应，generate_phase_summary 输出新增 stress_note/physical_note 字段，LLM 失败或表达违规时安全降级为预设反应。心跳 LLM 失败时默认静默（不触发主动行为）。**因果标签集成**：narrate_phase_events 在 LLM 调用前为每个事件预计算 cause_tags 并附加到场景输出，process_critical_event 在 LLM 调用前生成 cause_tags 并附加到返回结果。**LifeMoment 记忆注入（阶段 A）**：三个 LLM 入口 (generate_interaction_response / narrate_phase_events / process_critical_event) 改走 memory.recall + build_memory_prompt_block，MEMORY_V2=off 时回退 state.memories[-3:] 旧行为。mind.py:681/836 的 Memory() 创建已改造为 memory.record_moment(actor="world"/"caregiver", _legacy_memory_override=memory) 单写入口，保留 LLM trace 原文。
touch.py: 肢体互动动作定义（23 个动作，5 类：抚触/拥抱/亲昵/安抚/游戏），每个动作有阶段范围限制确保适龄，get_available_actions(phase) 按类别分组返回可用动作
nanny.py: 保姆引擎（simulate_phase + resolve_critical_event + complete_phase + grow_stream 含心跳注入），缺陷→能力约束映射 + _update_stress/_check_stress_regression（机械移除能力）/_check_regression_recovery（机械恢复能力）/_update_phase_state（含阶段自动标签 PHASE_AUTO_TAGS + fine_motor/self_regulation/transitional_object/imaginary_friend 写入）/_update_caregiver_profile + 6 个新里程碑定义 + LLM 超时保护 + 幂等性检查。压力衰减按阶段天数计算（0.995^days），喂养模式按 age_days 判断（对齐 WHO 指南），依附双向状态转移（secure⇄anxious⇄avoidant），complete_phase 同步 attachment_per_caregiver，生长曲线身高/体重独立 10% 方差。resolve_critical_event 应用 DECISION_TAG_EFFECTS + toilet_trained/room_separated 写入，命名仪式走完整照护者更新流程。grow_stream 在 phase_simulated 后注入 heartbeat 评估。**因果标签集成**：_snapshot_state() 快照 stress/attachment/capabilities/fears/preferences，simulate_phase_stream 每个 scene 前后快照生成 effect_tags 并传播到 SSE 事件，resolve_critical_event 同理在状态变更前后生成 effect_tags。**摇篮图谱集成**：simulate_phase_stream 在 scene/capabilities/milestones/stress 产出后调用 cradle_graph_store 入图，resolve_critical_event 调用 save_critical_graph + save_caregiver_graph + save_psychosocial_graph，complete_phase 调用 save_phase_graph 提取全维度快照。**LifeMoment 集成（阶段 A）**：nanny.py:791 场景 Memory 和 :991 关键事件 Memory 的 state.memories.append 改造为 memory.record_moment（jsonl 真相源 + 降级回写，保留 LLM trace 原文通过 _legacy_memory_override）。
heartbeat_provider.py: 心跳适配器，实现 MonologueProvider 协议。CRADLE_BEHAVIORS（12 阶段行为空间数据）+ CradleMonologueProvider（build_inner_monologue 构造英文内心独白供 LLM 判断）+ shift_attachment_toward_avoidant（忽略导致依恋偏移）。延迟导入 nanny/state 避免循环依赖。**LifeMoment 集成**：build_inner_monologue 的 Recent Experiences 小节 V2=on 时走 memory.recall（相关性 + forget_score + tag 一跳），V2=off 保留 state.memories[-3:]。
conversation_store.py: 会话资源持久化层（archive/conversations/{conv_id}/）。conv_id 校验（`dm:{baby_id}` / `gp:{sorted_joined}`）+ meta.json（participants/kind/display_name/icebreaker_done/message_count/last_active_ts）+ messages.jsonl（per-conv 单调 seq）+ get_conv_notify（asyncio.Event）+ get_conv_lock（asyncio.Lock）+ list_conversations(baby_id=?) 按 last_active_ts 倒序。与 state.py 的 baby 级基础设施同构但命名空间独立。
initiative_needs.py: 摇篮期主动需求政策——`NeedUrgency` 三类枚举（physiological/emotional/social）+ 19 个 trigger 枚举（hunger/sleepy/fear/lonely/curious...）+ 超时表（2/3/5 min）+ LLM 驱动的 `evaluate_need()`（复用 heartbeat 引擎，2min 频率门 + sim_day 冷却）+ 保姆降级文本生成器（signal × actor × action × outcome 组合，数千种拼接）+ `TRIGGER_LABELS` 前端展示映射。2026-04-21 从顶级 `backend/initiative_needs.py` 迁入，因职责只服务摇篮期且反向依赖 cradle 子模块。
conversation.py: 会话编排层，1v1（DM）与多宝宝群聊（group）资源同构。make_conv_id 确定性生成 → 同组宝宝复用。post_parent_message：持久化家长消息 → 群聊首次触发破冰（串行每宝宝 1 句）、否则 P1 round-robin（每宝宝响应 1 句）→ DM 复用 mind.generate_interaction_response（保留 touch 语义），群聊使用 _call_group_agent（多 agent 共享历史 + 各自视角 chat messages）。post_baby_message：宝宝主动发言（heartbeat/baby_need 触发），不连锁其他宝宝。state_changes 即时结算（preference/comfort_source/fear），无"end_session"语义。每条消息同步回写各 baby events.jsonl 的 `conversation_message` 薄索引（供因果图未来扩展）。M5 将替代 social.py。**LifeMoment 集成（阶段 A）**：post_baby_message 触发时写 actor=self + outcome=pending 的 LifeMoment；_persist_baby_response 写 baby 对家长消息回应的 LifeMoment；_apply_dm_parent_side_effects 调 mark_responded(state=state) 时 heartbeat 通过 companion_seq 链接 responded 新 moment（append-only C8 铁律）。
social.py: **[已删除]** 旧的内存社交会话实现（SocialSession），已被 conversation.py + conversation_store.py 替代。

## 对外暴露

```python
from cradle import admit, check_world_readiness, load_state, list_cradle_babies
from cradle import simulate_phase, resolve_critical_event, complete_phase
from cradle import PHASES
from cradle.state import CaregiverProfile
from cradle.touch import TOUCH_ACTIONS, get_available_actions
from cradle.heartbeat_provider import CradleMonologueProvider, CRADLE_BEHAVIORS, shift_attachment_toward_avoidant
# 会话资源（M1+）
from cradle import make_conv_id, get_or_create_conversation, rename_conversation
from cradle import get_conversation, list_conversations, list_messages
from cradle import post_parent_message, post_baby_message
from cradle import load_conv_messages_after, get_conv_notify, get_conv_lock
```

## 图谱概念两分（v3，refactor-cradle-graph-phase-axis）

| 概念 | 性质 | id 规约 | 来源 | 角色 |
|------|------|---------|------|------|
| **progression** | 引擎调度游标（运行时） | `progression:{phase_name}` | `cradle.phases.PHASES` 12 步 | 挂在 `baby:core` 下的叙事时间线，事件性节点（fear/preference/scene/event/stress）的源 |
| **phase** | 发育期（领域知识） | `phase:{dim}:{stage}` | `cradle.ontology.DIMENSION_PHASES` 6 维 × 4-5 stage | L2 节点，强制 `BELONGS_TO → dimension:{dim}`，capability/milestone 的 `OCCURS_IN` 唯一合法目标 |

铁律：capability/milestone 的 `OCCURS_IN` 永远不指向 progression；progression 永远不持有 `BELONGS_TO → dimension`。校验器 `META-RULE-PHASE` / `META-RULE-OCCURS-TARGET` 强制此约束。

## 依赖关系

- cradle_graph_store.py: 摇篮六层发育因果图谱引擎（L1身份→L2阶段→L3能力→L4心理→L5维度→L6经验），v3 拆分 progression / per-dim phase 两类节点；与子宫 causal_graph_store.py 分离
- events/: 共享事件基础设施（Event 数据类 + 事件定义 + 权重调制器），cradle/events.py 是 thin wrapper
- womb/genetics.py: 复用 _create_client, _call_llm, _parse_json, PROVIDERS
- api/registry.py: 加载出生数据（延迟导入避免循环依赖）
- heartbeat.py: BehaviorSpace/InitiativeState 数据模型 + evaluate_heartbeat() 引擎
- scheduler.py: DES 调度器（全局优先级队列 + 单主循环，per-baby dispatch lock 并发），通过 api/cradle.py 间接依赖，admit 时注册 agent
- world.py: 世界层（日程模板 + 事件处理 + 标签规则），消费 events/ 和 cradle/state.py

## 数据流

```
阶段推进（手动触发）:
Baby JSON (archive/) → admit() → Identity 编译 → BabyState (archive/)
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

自驱动生命（DES 调度器，全局优先级队列）:
admit() → scheduler.register() → push phase_start 事件到队列
    → phase_start: 初始化阶段 → push day_tick(day=0)
    → day_tick(day): 批量 routine + snapshot + need + 涌现掷骰
        → is_story_worthy? → LLM 叙事 → autonomous_event
        → 否 → template_reaction → autonomous_routine
        → push day_tick(day+1) 或 phase_complete
    → phase_complete: 压力回退/恢复 + 能力解锁 + LLM 总结
        → push 下一 phase_start 或 cradle_complete
    单主循环 pop → per-baby dispatch lock 保证串行 → fire-and-forget task
    不同 baby 天然并发，N 个 baby 不需要 N 个协程
    所有事件写 events.jsonl（日志即真相），前端通过 lifeline SSE 读取

前端观察（lifeline SSE 日志读取器）:
GET /lifeline?after_seq=X
    → Phase 1: 读 events.jsonl seq > X → 50ms/条回放
    → Phase 2: await asyncio.Event 通知 → 实时推送
    → 2s 无事件 → sim_tick 心跳
    断连重连 → 前端带 last_seq → 从断点继续
```

[PROTOCOL]: 变更时更新此文档，然后检查 CLAUDE.md
