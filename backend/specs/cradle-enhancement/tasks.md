# Plan: cradle-enhancement

## Tasks

### Phase A: 数据模型扩展 (state.py) -- 所有后续任务的基础

- [ ] 1. 新增 StressState 数据类
  - [ ] 1.1 在 state.py 中定义 StressState dataclass (stress_level, regressed_capabilities, resilience_bonus)
  - [ ] 1.2 实现 to_dict() 和 from_dict() 方法
  - [ ] 1.3 在 BabyState 中新增 stress 字段，默认值 StressState()
  - 影响文件: `cradle/state.py`

- [ ] 2. 新增 NutritionSleepState 数据类
  - [ ] 2.1 在 state.py 中定义 NutritionSleepState dataclass (feeding_mode, food_allergies, sleep_quality, sleep_regression_active, night_waking_frequency, room_separated, transitional_object)
  - [ ] 2.2 实现 to_dict() 和 from_dict() 方法
  - [ ] 2.3 在 BabyState 中新增 nutrition_sleep 字段
  - 影响文件: `cradle/state.py`

- [ ] 3. 新增 EmotionalState 数据类
  - [ ] 3.1 在 state.py 中定义 EmotionalState dataclass (tantrum_frequency, emotional_vocabulary, empathy_level, self_regulation_score, imaginary_friend, play_type)
  - [ ] 3.2 实现 to_dict() 和 from_dict() 方法
  - [ ] 3.3 在 BabyState 中新增 emotional 字段
  - 影响文件: `cradle/state.py`

- [ ] 4. 新增 PhysicalState 数据类
  - [ ] 4.1 在 state.py 中定义 PhysicalState dataclass (height_cm, weight_kg, teeth_count, toilet_trained, fine_motor_level)
  - [ ] 4.2 实现 to_dict() 和 from_dict() 方法
  - [ ] 4.3 在 BabyState 中新增 physical 字段
  - 影响文件: `cradle/state.py`

- [ ] 5. CaregiverProfile 直接替换 ParentProfile
  - [ ] 5.1 在 state.py 中定义 CaregiverProfile dataclass (含 caregiver_id, role, display_name + 原 ParentProfile 全部字段)
  - [ ] 5.2 删除 ParentProfile 类
  - [ ] 5.3 BabyState: 删除 parent_profile 字段，新增 caregivers: dict 和 attachment_per_caregiver: dict
  - [ ] 5.4 BabyState.from_dict: 旧 parent_profile JSON 自动迁移为 caregivers["primary_parent"]
  - [ ] 5.5 全局替换引用点:
    - nanny.py: `_update_parent_profile` → `_update_caregiver_profile`，接收 caregiver_id
    - mind.py:567: `state.parent_profile.interaction_count` → `state.caregivers[cid].interaction_count`
    - social.py:397: 同上
    - CLAUDE.md: 更新成员清单
  - 影响文件: `cradle/state.py`, `cradle/nanny.py`, `cradle/mind.py`, `cradle/social.py`, `cradle/CLAUDE.md`

- [ ] 6. BabyState 序列化更新
  - [ ] 6.1 更新 BabyState.to_dict() 包含所有新字段
  - [ ] 6.2 更新 BabyState.from_dict() 用 .get() 兼容旧数据（所有新字段有默认值）
  - [ ] 6.3 更新 list_cradle_babies() 返回新字段摘要
  - [ ] 6.4 手动测试: 加载一个现有 nursery/{baby_id}/state.json 验证不崩溃
  - 影响文件: `cradle/state.py`

### Phase B: 事件系统扩展 (events.py) -- 依赖 Phase A

- [ ] 7. 新增日常事件
  - [ ] 7.1 添加 teething_discomfort 事件 (phase 3-7)
  - [ ] 7.2 添加 picky_eating 事件 (phase 7-9)
  - [ ] 7.3 添加 common_cold 事件 (phase 0-11)
  - [ ] 7.4 添加 sleep_regression 事件 (phase 2-7)
  - [ ] 7.5 添加 play_session 事件 (phase 1-11)
  - [ ] 7.6 添加 growth_spurt 事件 (phase 0-11)
  - 影响文件: `cradle/events.py`

- [ ] 8. 新增环境事件
  - [ ] 8.1 添加 tantrum_trigger 事件 (phase 6-9)
  - [ ] 8.2 添加 imaginary_friend_appears 事件 (phase 8-11)
  - [ ] 8.3 添加 first_drawing 事件 (phase 5-9)
  - [ ] 8.4 添加 empathy_moment 事件 (phase 5-11)
  - 影响文件: `cradle/events.py`

- [ ] 9. 新增关键事件
  - [ ] 9.1 添加 food_allergy 事件 (phase 3-5, 3个父母选项)
  - [ ] 9.2 添加 room_separation 事件 (phase 5-7, 3个父母选项)
  - [ ] 9.3 添加 toilet_training 事件 (phase 7-8, 3个父母选项)
  - [ ] 9.4 添加 kindergarten_entry 事件 (phase 8, 3个父母选项)
  - [ ] 9.5 添加 night_terror 事件 (phase 8-10, 3个父母选项) -- 区别于现有 nightmare
  - [ ] 9.6 添加 imaginary_friend_discovery 事件 (phase 8-11, 3个父母选项)
  - 影响文件: `cradle/events.py`

- [ ] 10. 事件权重动态调制
  - [ ] 10.1 实现 _phase_weight_modifier() 函数
  - [ ] 10.2 在 roll_events() 中集成调制器（睡眠回归高发期、tantrum 曲线、压力敏感度）
  - [ ] 10.3 传入 state 参数（当前 roll_events 只接收 identity，需扩展签名）
  - 影响文件: `cradle/events.py`

### Phase C: 压力回退引擎 (nanny.py) -- 依赖 Phase A + B

- [ ] 11. 压力值更新系统
  - [ ] 11.1 实现 _update_stress() 函数（根据 valence/intensity/parent_present/attachment 更新压力值）
  - [ ] 11.2 定义 UNREGRESSIVE_CAPABILITIES 集合
  - [ ] 11.3 在 simulate_phase_stream 的每个 scene 处理后调用 _update_stress()
  - 影响文件: `cradle/nanny.py`

- [ ] 12. 能力回退与恢复
  - [ ] 12.1 实现 _check_stress_regression() 函数
  - [ ] 12.2 实现 _check_regression_recovery() 函数
  - [ ] 12.3 在 simulate_phase_stream 中集成（叙事后、能力解锁前）
  - [ ] 12.4 修改 _check_capability_unlocks() 跳过 regressed 状态的能力
  - [ ] 12.5 添加 SSE 事件: stress_regression 和 regression_recovery
  - 影响文件: `cradle/nanny.py`

### Phase D: 阶段状态自动更新 (nanny.py) -- 依赖 Phase A + B

- [ ] 13. 实现 _update_phase_state() 函数
  - [ ] 13.1 喂养模式按阶段自动切换
  - [ ] 13.2 夜醒次数基线 + 睡眠回归修正
  - [ ] 13.3 睡眠回归触发/恢复逻辑
  - [ ] 13.4 Tantrum 频率曲线赋值
  - [ ] 13.5 共情等级更新
  - [ ] 13.6 游戏类型更新
  - [ ] 13.7 体格(身高/体重)更新（标准曲线 + 随机偏差）
  - [ ] 13.8 出牙时间线
  - [ ] 13.9 情绪词汇渐进解锁
  - 影响文件: `cradle/nanny.py`

- [ ] 14. 集成到 simulate_phase_stream
  - [ ] 14.1 在阶段开始后、roll_events 前调用 _update_phase_state()
  - [ ] 14.2 新增 SSE 事件 "phase_state_update" 推送状态变更
  - 影响文件: `cradle/nanny.py`

### Phase E: 多照护者集成 (nanny.py + api) -- 依赖 Phase A

- [ ] 15. nanny.py 多照护者支持
  - [ ] 15.1 修改 resolve_critical_event() 接受 caregiver_id 参数
  - [ ] 15.2 修改 _update_attachment() 按 caregiver_id 更新 attachment_per_caregiver
  - [ ] 15.3 修改 _update_parent_profile() 按 caregiver_id 更新 caregivers[cid]
  - [ ] 15.4 保持 state.attachment_style 同步为主照护者的值（兼容）
  - [ ] 15.5 kindergarten_entry 处理: 自动添加 teacher CaregiverProfile
  - 影响文件: `cradle/nanny.py`

- [ ] 16. 新增 API: 照护者管理
  - [ ] 16.1 GET /cradle/{id}/caregivers -- 列出照护者
  - [ ] 16.2 POST /cradle/{id}/caregivers -- 添加照护者 (body: role, display_name, emotional_tone)
  - [ ] 16.3 PUT /cradle/{id}/caregivers/{cid} -- 更新照护者
  - [ ] 16.4 修改 POST /cradle/{id}/intervene 接受 caregiver_id 参数
  - 影响文件: `api/cradle.py`

### Phase F: LLM Prompt 扩展 (mind.py) -- 依赖 Phase A-D

- [ ] 17. narrate_phase_events prompt 扩展
  - [ ] 17.1 在 prompt 的 Current State 部分追加 Physical State / Stress & Regression / Emotional Development / Caregivers 上下文
  - [ ] 17.2 不新增 LLM 调用，仅扩展现有调用的输入
  - 影响文件: `cradle/mind.py`

- [ ] 18. process_critical_event prompt 扩展
  - [ ] 18.1 在 prompt 中追加压力/情绪/体格上下文
  - [ ] 18.2 添加照护者身份上下文（哪个照护者在处理）
  - 影响文件: `cradle/mind.py`

- [ ] 19. generate_phase_summary prompt 扩展
  - [ ] 19.1 在 prompt 中追加本阶段的压力/回退/恢复/喂养/睡眠变化摘要
  - [ ] 19.2 summary JSON 新增 stress_note, physical_note, feeding_note 字段
  - 影响文件: `cradle/mind.py`

- [ ] 20. generate_interaction_response prompt 扩展
  - [ ] 20.1 在 prompt 中追加当前情绪词汇限制（expression mode 之外的第二层约束）
  - [ ] 20.2 如果有 imaginary_friend，在上下文中注入
  - [ ] 20.3 如果有 regressed 能力，在 constraints 中注入
  - 影响文件: `cradle/mind.py`

### Phase G: 新增里程碑 (nanny.py) -- 依赖 Phase A + D

- [ ] 21. 扩展 MILESTONE_DEFINITIONS
  - [ ] 21.1 添加 first_solid_food 里程碑 (phase 3, 触发: feeding_mode == introducing_solids)
  - [ ] 21.2 添加 first_tooth 里程碑 (phase 3, 触发: teeth_count > 0)
  - [ ] 21.3 添加 toilet_trained 里程碑 (phase 7-8, 触发: toilet_training 事件成功)
  - [ ] 21.4 添加 first_tantrum 里程碑 (phase 6-7, 触发: tantrum_trigger 事件)
  - [ ] 21.5 添加 imaginary_friend 里程碑 (phase 8-11, 触发: imaginary_friend 非空)
  - [ ] 21.6 添加 kindergarten_start 里程碑 (phase 8, 触发: kindergarten_entry 事件)
  - [ ] 21.7 修改 _check_milestones() 支持非能力触发的里程碑（事件触发 + 状态触发）
  - 影响文件: `cradle/nanny.py`

### Phase H: API 返回值扩展 -- 依赖 Phase A-G

- [ ] 22. 状态 API 扩展
  - [ ] 22.1 修改 GET /cradle/{id}/status 返回 stress, nutrition_sleep, emotional, physical, caregivers
  - [ ] 22.2 修改 grow_stream SSE 透传新增事件类型 (phase_state_update, stress_regression, regression_recovery)
  - 影响文件: `api/cradle.py`

### Phase I: 前端展示 -- 依赖 Phase H

- [ ] 23. 状态面板增强
  - [ ] 23.1 在 baby status card 中展示身高/体重/牙数
  - [ ] 23.2 展示压力值条（0-1 进度条，颜色随值变化）
  - [ ] 23.3 展示睡眠状态（回归期标记 + 夜醒次数）
  - [ ] 23.4 展示喂养模式
  - [ ] 23.5 展示情绪发展摘要（共情等级 + 脾气频率）
  - 影响文件: `frontend/src/Cradle.jsx`

- [ ] 24. 照护者面板
  - [ ] 24.1 新增照护者列表展示
  - [ ] 24.2 关键事件介入时，允许选择以哪个照护者身份介入
  - [ ] 24.3 照护者添加表单
  - 影响文件: `frontend/src/Cradle.jsx`（如文件过大可拆分组件）

- [ ] 25. SSE 日志新事件类型渲染
  - [ ] 25.1 phase_state_update 事件渲染（喂养变更、体格增长、出牙等用图标区分）
  - [ ] 25.2 stress_regression 事件渲染（黄色警告样式 + 回退能力列表）
  - [ ] 25.3 regression_recovery 事件渲染（绿色成功样式 + 韧性标记）
  - 影响文件: `frontend/src/Cradle.jsx` 或 `frontend/src/components/ConsolePanel.jsx`

### Phase J: 文档更新 -- 依赖所有上述 Phase

- [ ] 26. L2 文档更新
  - [ ] 26.1 更新 cradle/CLAUDE.md: 成员清单补充新数据类说明、事件数量更新、数据流更新
  - [ ] 26.2 更新 specs/cradle/requirements.md 和 design.md: 标注增强版引用
  - 影响文件: `cradle/CLAUDE.md`, `specs/cradle/requirements.md`, `specs/cradle/design.md`

- [ ] 27. L3 文档更新
  - [ ] 27.1 更新 state.py 头部注释 [OUTPUT] 添加新数据类
  - [ ] 27.2 更新 events.py 头部注释事件数量
  - [ ] 27.3 更新 nanny.py 头部注释新增函数
  - [ ] 27.4 更新 mind.py 头部注释
  - 影响文件: `cradle/state.py`, `cradle/events.py`, `cradle/nanny.py`, `cradle/mind.py`
