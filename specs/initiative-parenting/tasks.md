# Plan: initiative-parenting

## Tasks

- [ ] 1. 创建 initiative_needs.py 数据模块
  - [ ] 1.1 定义 NeedUrgency 枚举（physiological/emotional/social）和 URGENCY_TIMEOUT 映射
  - [ ] 1.2 定义 TRIGGER_URGENCY 映射（trigger -> urgency）
  - [ ] 1.3 定义 PHASE_TRIGGER_WEIGHTS（每阶段 trigger 权重池，Phase 0-8，9-11 fallback 到 8）
  - [ ] 1.4 定义 NEED_EXPRESSIONS 模板（每 trigger x expression_mode 的表达文本，至少覆盖 hunger/fear/pain/sleepy/play/share/curious/bored x cry_only/babble/first_words/simple_sentence）
  - [ ] 1.5 定义 NANNY_RESPONSES 降级模板（每 trigger 2-3 条，含 text + role）
  - [ ] 1.6 添加 L3 头部注释（INPUT/OUTPUT/POS/PROTOCOL）

- [ ] 2. 实现需求评估函数 evaluate_need()（LLM 驱动）
  - [ ] 2.1 在 initiative_needs.py 中实现 evaluate_need(state, lock) -> dict | None
  - [ ] 2.2 实现频率门卫：pending 检测 + frequency_gate + MIN_NEED_INTERVAL_DAYS 冷却
  - [ ] 2.3 调用 evaluate_heartbeat()（复用 heartbeat.py 引擎 + CradleMonologueProvider 构造内心独白）
  - [ ] 2.4 将 heartbeat 返回的 initiative 转换为需求格式（trigger → urgency → timeout_sec）
  - [ ] 2.5 确认 cradle/mind.py 中 generate_heartbeat_evaluation 已实现（如无则补充）

- [ ] 3. 实现 scheduler 响应信号机制
  - [ ] 3.1 在 scheduler.py 中添加 _respond_events 字典和 _get_or_create_respond_event() 函数
  - [ ] 3.2 添加 signal_need_responded(baby_id) 公开函数
  - [ ] 3.3 更新 scheduler.py 的 L3 头部注释（OUTPUT 增加 signal_need_responded）

- [ ] 4. 实现 scheduler._handle_need() 方法
  - [ ] 4.1 在 LifelineScheduler 中添加 _handle_need() async 方法
  - [ ] 4.2 实现需求 ID 生成 + initiative state 更新
  - [ ] 4.3 实现 append_event(baby_need) 写入
  - [ ] 4.4 实现 await asyncio.wait_for(respond_event.wait(), timeout) 等待逻辑
  - [ ] 4.5 实现用户响应分支（写 need_responded + responder=parent 事件）
  - [ ] 4.6 实现超时分支（调用 _nanny_fallback）

- [ ] 5. 实现 scheduler._nanny_fallback() 方法
  - [ ] 5.1 在 LifelineScheduler 中添加 _nanny_fallback() async 方法
  - [ ] 5.2 实现模板选取（从 NANNY_RESPONSES 随机）
  - [ ] 5.3 实现降级效果（stress -0.05, consecutive_ignores++, pending 清空）
  - [ ] 5.4 实现连续忽略 >= 3 时的依恋偏移（调用 shift_attachment_toward_avoidant）
  - [ ] 5.5 实现 append_event(need_responded, responder=nanny) 写入

- [ ] 6. 修改 scheduler._run_day() 集成需求评估
  - [ ] 6.1 在步骤 2（世界快照刷新）之后、步骤 3（涌现事件选取）之前，插入 evaluate_need() 调用
  - [ ] 6.2 当 evaluate_need 返回非 None 时，调用 await self._handle_need()
  - [ ] 6.3 确保需求处理后继续正常的涌现事件流程

- [ ] 7. 修改 api/cradle.py interact 端点
  - [ ] 7.1 在 mark_responded 之后，检测 state.initiative.pending_initiative_id 是否非空
  - [ ] 7.2 如有 pending need，应用额外效果（stress -0.1, 依恋向 secure 偏移）
  - [ ] 7.3 调用 signal_need_responded(baby_id) 唤醒 scheduler
  - [ ] 7.4 确保效果应用在 save_state 之前

- [ ] 8. 更新文档（DocOps 回环）
  - [ ] 8.1 更新 scheduler.py L3 头部注释
  - [ ] 8.2 更新 cradle/CLAUDE.md（新增 initiative_needs.py 成员描述，更新数据流图）
  - [ ] 8.3 更新 api/cradle.py L3 头部注释（interact 端点新增需求响应信号）
  - [ ] 8.4 检查 /CLAUDE.md 是否需要更新（如有顶级文件新增）
