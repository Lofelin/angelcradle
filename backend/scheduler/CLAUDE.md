# scheduler/
> L2 | 父级: /CLAUDE.md

DES 离散事件模拟调度器——全局优先级队列驱动所有 Agent 生命线。
单一主循环 + heapq 优先级���列，所有 baby 共享一条时间线。
per-baby dispatch lock 保证同 baby 串行，不同 baby 天然并发。

## 成员清单

constants.py: 时间比例(TIME_SCALES)、节奏延迟(EVENT_PACE)、需求评估间隔、story 预算、摇篮出口阶段
events.py: SimEvent dataclass + 全局序号生成 + 需求响应信号(signal_need_responded)
naming.py: 11 国文化命名数据池 + auto_name() 规则命名（turbo 模式用）
core.py: LifelineScheduler 类主体（公共接口 + 队列 + 分发 + flush_quiet_days + pace）
handlers.py: 三大事件处理器 on_phase_start/on_day_tick/on_phase_complete + process_story（独立异步函数，通过 sched 参数访问调度器实例）。**LifeMoment 里程碑集成**：stress_regression → capability_lost / regression_recovery → capability_recovered / capabilities_unlocked → capability_gained / milestones → milestone_reached / phase_completed → phase_advanced / cradle_complete → cradle_complete，全部走 memory.record_milestone 独立写入（milestones.jsonl 真相源）。
needs.py: 主动需求处理 handle_need + nanny_fallback 保姆降级 + rule_based_need 规则引擎。**需求双写**：baby_need 事件同时写入 events.jsonl（供 get_status 恢复 pending need 状态）与 baby 的 DM 会话（post_baby_message subtype="need"，前端聊天窗口展示）。家长通过 /conversations 或 /interact 代理响应后，post_parent_message 的 DM 副作用会调 signal_need_responded 唤醒 handle_need 的等待。**LifeMoment 集成**：nanny_fallback 写 actor=caregiver:nanny + outcome="fallback" 的 LifeMoment，连续忽略 >= 3 次时 effect_tags 带 attachment:toward_avoidant。
story.py: LLM 叙事 generate_story + 批量跳天 calc_skip_target/batch_skip_days。**LifeMoment 集成**：generate_story 的 Memory 创建点改为 memory.record_moment(actor="world", _legacy_memory_override=memory) 单写入口。

## 对外暴露

```python
from scheduler import scheduler, TIME_SCALES, EVENT_PACE, signal_need_responded
```

## 依赖关系

- cradle/state.py: 状态加载/保存/事件日志
- cradle/phases.py: 阶段定义
- cradle/nanny.py: 阶段完成/能力解锁/里程碑
- cradle/mind.py: LLM 调用
- world.py: 日程生成/事件处理/快照
- events/: 事件定义
- cradle/initiative_needs.py: 摇篮期需求政策（trigger 枚举 / 频率门 / 保姆降级）
- config.py: 全局时间比例配置

## 内部依赖方向（单向无循环）

```
__init__.py → core.py → constants, events
                  ↓ (延迟 import)
             handlers.py → constants, events, naming, story, needs
                              ↓
                          story.py → constants
                          needs.py → events
```

[PROTOCOL]: 变更时更新此文档，然后检查 CLAUDE.md
