# Plan: causal-graph

## Phase 0 -- 因果标签 + 力导向图基础（1-2 周）

### 后端：因果标签引擎

- [ ] 1. 创建 cradle/causality.py 因果标签生成模块
  - [ ] 1.1 定义标签命名规范常量（SENSORY_CAUSE_RULES, EVENT_EFFECT_RULES）
    - 输入: events/definitions.py 的 Event 数据类字段
    - 输出: 两个 dict 常量，键为事件 sensory_channels/category，值为 cause_tag 模板
    - 验收: 覆盖所有 91 种事件定义的感官通道映射
  - [ ] 1.2 实现 generate_cause_tags(event, identity, state) -> list[str]
    - 输入: Event + Identity + BabyState
    - 输出: cause_tags 列表，遵循 namespace:key 命名规范
    - 验收: 感官通道匹配（dominant/weak）+ 唤醒基线 x 强度 + 压力上下文 + 缺陷匹配 + 阶段上下文，所有分支有单元测试
  - [ ] 1.3 实现 generate_effect_tags(event, result, state_before, state_after) -> list[str]
    - 输入: Event + LLM result dict + 前后 BabyState 快照
    - 输出: effect_tags 列表
    - 验收: 压力 delta + 依恋变化 + 能力解锁/回退 + 情绪效价，state diff 准确检测
  - [ ] 1.4 实现 rebuild_tags_from_memory(memory, identity) -> tuple[list, list]
    - 输入: Memory + Identity
    - 输出: (cause_tags, effect_tags) 尽力回填
    - 验收: 从 Memory.trace 关键词匹配 + emotional_valence + growth_signal 提取

- [ ] 2. 改造 mind.py："先决策再叙事"流程
  - [ ] 2.1 process_daily_with_nanny() 接入因果标签
    - 改造: 在规则处理日常事件后调用 causality.generate_cause_tags/generate_effect_tags
    - 输出: result dict 新增 cause_tags, effect_tags 字段
    - 验收: 日常事件 100% 通过规则生成标签，零 LLM 依赖
  - [ ] 2.2 process_environment_events() 接入因果标签
    - 改造: LLM prompt 中注入 cause_tags 作为上下文
    - 输出: LLM 返回 JSON 新增 llm_cause_tags，与规则 cause_tags 合并（规则优先）
    - 验收: LLM prompt 模板包含 cause_tags，合并逻辑不覆盖规则标签
  - [ ] 2.3 process_critical_event() 接入因果标签
    - 改造: 同 2.2，且 effect_tags 在父母决策后生成（包含 decision 标签）
    - 验收: 关键事件的 effect_tags 包含 caregiver:{id}:{action} 标签
  - [ ] 2.4 generate_heartbeat_evaluation() 接入因果标签
    - 改造: 心跳事件用纯规则标签
    - 验收: 心跳事件产出 cause_tags（阶段+唤醒+感官），effect_tags 可空

- [ ] 3. 改造 nanny.py：事件写入携带因果标签
  - [ ] 3.1 simulate_phase() 中 state_before 快照机制
    - 改造: 在每个事件处理前保存 state 关键字段快照（stress_level, attachment_style, capabilities）
    - 验收: 快照为浅拷贝 dict，不复制完整 BabyState（性能）
  - [ ] 3.2 append_event() 调用携带 cause_tags/effect_tags
    - 改造: 所有 append_event 调用的 data dict 新增 cause_tags 和 effect_tags
    - 验收: events.jsonl 中新事件包含这两个字段，旧事件缺失时 load 默认空列表

- [ ] 4. 向后兼容保障
  - [ ] 4.1 events.jsonl 读取兼容
    - 改造: load_events_after() 解析 data 时对 cause_tags/effect_tags 做 .get(key, [])
    - 验收: 旧格式 events.jsonl 加载无报错
  - [ ] 4.2 旧数据回填工具
    - 实现: rebuild_all_tags(baby_id) 遍历 state.memories 调用 rebuild_tags_from_memory
    - 验收: 对已有宝宝执行后，所有 Memory 获得尽力回填的标签

### 前端：力导向关系图 + 因果标签显示

- [ ] 5. CausalTags 组件
  - [ ] 5.1 创建 src/components/CausalTags.jsx
    - 输入: causeTags: string[], effectTags: string[], onTagClick: (tag) => void
    - 输出: 标签芯片组（cause 左箭头蓝底, effect 右箭头绿底, 先天因素金底星形）
    - 验收: 标签按 namespace 分类渲染不同样式，空数组时不渲染
  - [ ] 5.2 在 EventCard 中集成 CausalTags
    - 改造: 从 SSE 事件 data 中提取 cause_tags/effect_tags 传入 CausalTags
    - 验收: 事件卡片下方显示标签，旧事件（无标签）正常显示无标签区域

- [ ] 6. 安装 react-force-graph-2d 依赖
  - 命令: npm install react-force-graph-2d
  - 验收: package.json 新增依赖，Vite 构建通过，开发服务器正常启动

- [ ] 7. 创建 src/hooks/useCausalGraph.js
  - [ ] 7.1 实现 SSE 事件流因果标签收集
    - 输入: SSE 事件中的 cause_tags/effect_tags
    - 输出: 维护 nodes Map 和 edges 数组
    - 验收: 新事件到达时 100ms 批量合并后更新图谱数据
  - [ ] 7.2 实现 traceUpstream 本地 BFS 追溯
    - 输入: nodeId
    - 输出: 高亮节点集合 + 高亮边集合
    - 验收: 300 节点图追溯 < 5ms
  - [ ] 7.3 实现 stats 统计（节点数、边数）
    - 验收: 实时反映当前图谱规模

- [ ] 8. 创建 src/components/LifeGraph.jsx（统一图谱组件）
  - [ ] 8.1 ForceGraph2D 容器 + 基础配置
    - 实现: 引入 react-force-graph-2d，配置 cooldownTicks=100, warmupTicks=50
    - 验收: 空图谱可渲染，缩放平移正常
  - [ ] 8.2 nodeCanvasObject 自定义节点渲染
    - 实现: 按 category 绘制不同形状（六边形/圆/方/星/菱/圆角方/大圆/钻石）和颜色
    - 验收: 8 种节点类型视觉可区分，hover 显示节点名称
  - [ ] 8.3 linkCanvasObject 自定义边渲染
    - 实现: 按 edge_type 绘制不同线型（实线/虚线/点线）+ 箭头 + 可选标签
    - 验收: 边默认半透明，高亮时全不透明
  - [ ] 8.4 onNodeClick 交互
    - 实现: 点击节点 → 调用 traceUpstream → SET_HIGHLIGHT
    - 验收: 点击后上游链路高亮，非相关节点淡化
  - [ ] 8.5 onNodeHover 悬浮提示
    - 实现: hover 节点显示简要信息（名称、类型、阶段）
    - 验收: hover 响应即时，离开即消失

- [ ] 9. 创建 src/components/EntityLegend.jsx
  - 实现: 底部图例栏，显示 8 种节点类型的颜色+形状+标签，点击可过滤
  - 验收: 图例与实际节点视觉一致，点击图例项触发 SET_FILTER

- [ ] 10. 创建 src/components/GraphToolbar.jsx
  - 实现: 工具栏按钮（边标签开关、重置布局、全屏切换）
  - 验收: 边标签开关触发 TOGGLE_LABELS，重置布局触发 ForceGraph2D reheat

- [ ] 11. App.jsx 改造
  - [ ] 11.1 新增 graphReducer（ADD_NODES, ADD_EDGES, SET_FILTER, TOGGLE_LABELS, SET_HIGHLIGHT, CLEAR_GRAPH）
    - 验收: reducer 纯函数，所有 action 有对应处理，节点去重 by node_id
  - [ ] 11.2 renderConceiving 左面板替换
    - 改造: 左侧 w-1/2 面板渲染 `<LifeGraph stage="womb" />`，右侧保持现有
    - 验收: 子宫页面左侧显示力导向图，右侧阶段卡片/监视器/控制台不受影响
  - [ ] 11.3 子宫 SSE 事件分发到 graphReducer
    - 改造: womb SSE 事件处理中，提取因果相关数据 dispatch 到 graphReducer
    - 验收: 子宫阶段进行时图谱实时增长

- [ ] 12. Cradle.jsx 改造
  - [ ] 12.1 左面板替换为 LifeGraph
    - 改造: 左侧 w-[45%] 渲染 `<LifeGraph stage="cradle" />`
    - 验收: 摇篮页面左侧显示力导向图，右侧事件日志/对话区不受影响
  - [ ] 12.2 摇篮 SSE 事件分发到 graphReducer
    - 改造: 提取 cause_tags/effect_tags dispatch 到 graphReducer
    - 验收: 摇篮事件到达时图谱实时新增节点和边

### 文档回环

- [ ] 13. 文档更新
  - [ ] 13.1 创建 cradle/causality.py 的 L3 头部注释
  - [ ] 13.2 更新 cradle/CLAUDE.md（L2）新增 causality.py 成员
  - [ ] 13.3 更新 events/CLAUDE.md 说明 cause_tags/effect_tags 扩展
  - [ ] 13.4 创建 src/components/LifeGraph.jsx 的 L3 头部注释
  - [ ] 13.5 创建 src/hooks/useCausalGraph.js 的 L3 头部注释

---

## Phase 1 -- 因果图谱 MVP + 高级交互（2-3 周）

### 后端：统一因果 Schema + API

- [ ] 14. 数据模型定义
  - [ ] 14.1 创建 cradle/causal_graph.py 数据模型
    - 实现: CausalNode, CausalEdge, CausalGraph dataclass 定义
    - 验收: to_dict/from_dict 可逆，schema_version 字段存在
  - [ ] 14.2 CausalGraph 内存图结构
    - 实现: adjacency + reverse_adjacency 邻接表，trace_upstream/trace_downstream BFS
    - 验收: 500 节点图追溯 < 5ms，max_depth 参数防止异常环

- [ ] 15. 子宫因果子图编译器
  - [ ] 15.1 compile_womb_causal_graph(baby_data, identity) 实现
    - 输入: baby_data dict + Identity 对象
    - 输出: list[CausalNode] + list[CausalEdge]
    - 验收: 从 gestation_log 提取基因节点、感官节点、气质节点，生成 genetic_expression/sensory_development 边
  - [ ] 15.2 在 identity.compile_identity() 中集成
    - 改造: compile_identity 完成后调用 compile_womb_causal_graph，写入 causal_nodes.json + causal_graph.jsonl
    - 验收: 新入摇篮的宝宝自动拥有子宫因果子图
  - [ ] 15.3 bridge:identity 节点生成
    - 实现: 创建桥接节点，连接子宫 trait 节点和摇篮初始 attribute 节点
    - 验收: bridge:identity 节点是子宫子图的汇聚点 + 摇篮子图的发散点

- [ ] 16. 摇篮因果边实时生成
  - [ ] 16.1 nanny._update_stress() 中生成 stress_cascade 边
    - 改造: 压力变化时创建 event->attribute:stress_level 边
    - 验收: 每次显著压力变化（delta > 0.05）产生一条 CausalEdge
  - [ ] 16.2 nanny._check_stress_regression() 中生成 regression 边
    - 改造: 能力回退时创建 attribute:stress->attribute:capability_regression 边
    - 验收: 回退事件产生 regression 类型边
  - [ ] 16.3 nanny.resolve_critical_event() 中生成 parental_decision 边
    - 改造: 父母决策后创建 decision->attribute 边
    - 验收: 决策边包含 caregiver_id 和具体 action 信息
  - [ ] 16.4 nanny.complete_phase() 中生成 capability_unlock 边
    - 改造: 能力解锁时创建 milestone->capability 边
    - 验收: 每个新能力有对应的 capability_unlock 边
  - [ ] 16.5 append_causal_edges() 持久化实现
    - 实现: append-only 写入 causal_graph.jsonl，带 seq 和 schema_version
    - 验收: 原子写入（与 events.jsonl 同模式），crash-safe

- [ ] 17. 因果图谱 API
  - [ ] 17.1 GET /cradle/baby/{baby_id}/causal-graph 实现
    - 实现: 从 causal_nodes.json + causal_graph.jsonl 读取，支持 after_seq/life_stage/phase/collapse_level 参数
    - 验收: 全量查询 < 100ms，增量查询 < 30ms（500 节点规模）
  - [ ] 17.2 GET /cradle/baby/{baby_id}/causal-trace/{node_id} 实现
    - 实现: 构建内存图 -> BFS 追溯 -> 返回链路节点和边
    - 验收: upstream/downstream/both 三种方向，max_depth 参数生效
  - [ ] 17.3 API 路由注册到 api/cradle.py
    - 验收: OpenAPI 文档自动生成，参数类型校验通过

### 前端：高级交互

- [ ] 18. 聚类折叠功能
  - [ ] 18.1 节点 >200 时自动聚类
    - 实现: d3-force cluster 力，将同阶段节点聚合为超级节点
    - 验收: 聚类后可见节点 < 30，点击超级节点展开内部节点
  - [ ] 18.2 默认阶段级视图
    - 实现: 初始渲染时自动折叠到阶段级（~20 节点），用户可手动展开
    - 验收: 首次渲染节点数可控，布局快速收敛

- [ ] 19. 因果链追溯高亮（traceUpstream 增强）
  - [ ] 19.1 useCausalGraph.traceUpstream 从 SSE 轻量版升级到 API 完整版
    - 实现: 初始加载完整图谱后本地 BFS，fallback API
    - 验收: 点击性格特质 -> 上游全链高亮（含跨阶段 bridge 节点）
  - [ ] 19.2 高亮路径动画
    - 实现: 高亮边使用渐变色 + 流动效果（Canvas strokeDash 偏移动画）
    - 验收: 追溯路径视觉醒目，非相关节点 opacity 0.15

- [ ] 20. 创建 src/components/NodeDetailPanel.jsx
  - 实现: 点击节点弹出浮窗，显示节点完整信息（名称、类型、阶段、权重、上游数、下游数）
  - 验收: 浮窗定位在节点附近，点击空白处关闭

- [ ] 21. 边标签开关
  - 实现: GraphToolbar 中的开关按钮 -> TOGGLE_LABELS -> linkCanvasObject 条件渲染标签
  - 验收: 开启时边中点显示因果标签，关闭时只显示连线

- [ ] 22. 创建 src/components/GraphStats.jsx
  - 实现: 显示当前图谱统计（N 个节点、M 条边、最长因果链深度）
  - 验收: 实时更新，不触发额外渲染

- [ ] 23. 移动端降级
  - [ ] 23.1 视口检测 + 条件渲染
    - 实现: `<768px` 时隐藏 LifeGraph，显示线性时间线替代
    - 验收: resize 事件触发切换，无闪烁
  - [ ] 23.2 线性时间线组件
    - 实现: 简化版因果展示（纵向时间线 + cause/effect 标签）
    - 验收: 移动端可读，核心因果信息不丢失

### 文档回环

- [ ] 24. 文档更新
  - [ ] 24.1 创建 cradle/causal_graph.py 的 L3 头部注释
  - [ ] 24.2 更新 cradle/CLAUDE.md 新增 causal_graph.py + API 成员
  - [ ] 24.3 更新 api/cradle.py L3 头部新增因果图谱路由
  - [ ] 24.4 创建 src/components/NodeDetailPanel.jsx 的 L3 头部注释
  - [ ] 24.5 创建 src/components/GraphStats.jsx 的 L3 头部注释

---

## Phase 2 -- 全生命周期（持续）

- [ ] 25. 摇篮期因果累积完善
  - [ ] 25.1 每次父母对话/互动 -> 结构化 CausalEdge
    - 改造: generate_interaction_response() 产出因果边（interaction -> attribute 变化）
    - 验收: 对话类互动产生 social_interaction 类型边
  - [ ] 25.2 每次心跳主动行为 -> 结构化 CausalEdge
    - 改造: heartbeat_provider 产出因果边（initiative -> behavior_pattern）
    - 验收: 主动行为积累可追溯

- [ ] 26. 世界期因果 Schema
  - [ ] 26.1 WorldReadiness 桥接节点
    - 实现: check_world_readiness() 成功时创建 bridge:world_readiness 节点
    - 验收: 摇篮关键属性/里程碑 -> bridge:world_readiness -> 世界初始属性
  - [ ] 26.2 世界事件因果边
    - 实现: world.py process_event() 产出 CausalEdge
    - 验收: 世界期事件与摇篮期共用 CausalEdge schema

- [ ] 27. 跨阶段全链路追溯
  - [ ] 27.1 三阶段因果图合并
    - 实现: CausalGraph.merge(womb_graph, cradle_graph, world_graph) 通过 bridge 节点拼接
    - 验收: 从世界期属性追溯到子宫期基因，链路完整无断裂
  - [ ] 27.2 前端跨阶段追溯 UI
    - 实现: 追溯高亮跨越三种颜色区域（蓝->绿->橙）
    - 验收: 用户点击世界期特质，可视化链路横跨三个生命阶段

- [ ] 28. 图谱分析增值功能
  - [ ] 28.1 因果影响力排行（哪些节点影响最多下游）
    - 实现: PageRank 或 out-degree 排序
    - 验收: 前端显示 top-5 影响力节点
  - [ ] 28.2 "如果当时..."反事实模拟（远期）
    - 设计: 用户选择一个历史决策 -> 模拟不同选择的因果链变化
    - 验收: 仅设计文档，不实现
