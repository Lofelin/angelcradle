# Plan: causal-graph-redesign

> 优先级：子宫 -> 摇篮 -> 世界。每个 Phase 内按依赖关系排序：常量定义 -> 数据模型 -> 后端引擎 -> 前端配置 -> 前端组件 -> 测试 -> 文档。
> Phase 1 拆为 1a 后端(4天) + 1b 前端(5天)，总计 2-3 周。
> Phase 2 约 2 周。Phase 3 约 3 周。
> 每个 Phase 末尾有验证/测试子任务。
> Phase 1 第一个任务是 LLM prompt 原型验证（fail fast）。

---

## Phase 0 -- LLM Prompt 原型验证（1 天，fail fast）

- [ ] 0. LLM prompt 原型验证
  - [ ] 0.1 用现有 LLM 接口测试六层因果链生成 prompt，验证 LLM 能否输出符合 WOMB_LAYER_MAP 的结构化数据
    - 验收: LLM 输出能被 JSON parse 且包含 layer 1-6 的节点数据
  - [ ] 0.2 测试表观遗传三条链（BDNF/IGF2_H19/NR3C1）的 prompt 输出质量
    - 验收: 三条链数据完整，evidence_level 标注正确
  - [ ] 0.3 如果 prompt 验证失败，在此处停止并调整方案再继续
    - 验收: 明确的 go/no-go 决策记录

---

## Phase 1a -- 子宫六层因果链：后端（4 天）

### 常量定义（拆分到 constants/）

- [ ] 1. 新建 constants/ 目录和常量模块
  - [ ] 1.1 新建 constants/womb_constants.py：WOMB_LAYER_MAP、STAGE_TO_LAYERS、WOMB_LAYER_RADIUS_BASE、SIGNAL_PATHWAYS、PATHWAY_CROSSTALK（crosstalk causality_type=weak_causal）、MATERNAL_FUNCTIONS(4个)、PLACENTA_NODE(1个聚合)、STAGE_PLASTICITY、KNOWN_FEEDBACK_LOOPS
    - 验收: 所有 7 个子宫阶段有层级产出定义；母体 4+1 节点（非 6+3）；crosstalk 为 weak_causal
  - [ ] 1.2 新建 constants/cradle_constants.py：BSID_DIMENSIONS（含 simplified_label、deferred 标记）、CAPABILITY_TO_DIMENSION、WHO_MGRS_WINDOWS、CRADLE_EDGE_RULES（含 mediated/moderated）、WEIGHT_CAPS（遗传按维度分设）、ATTACHMENT_THRESHOLD（阈值模型）、MEDIATION_RULES（运动->语言改为 CORRELATES）、MATURATION_CLOCK_GROUPS、GENETIC_WEIGHT_BY_DIMENSION
    - 验收: 7 维度配置完整；依恋为阈值模型（secure=0, insecure=-0.2~-0.3）；运动->语言为 CORRELATES
  - [ ] 1.3 新建 constants/world_constants.py：FISKE_MODELS（含 valence）、DUNBAR_LAYERS（150 软上限）、LIFE_EVENT_EFFECTS（标注 baseline_culture=western_industrial，设为可配置）
    - 验收: Fiske 有 valence(-10~10) 属性；Dunbar 150 为软上限；衰减参数标注"西方工业社会基线"
  - [ ] 1.4 新建 constants/__init__.py：统一导出
    - 验收: from constants import * 可用

### 数据模型与六层引擎

- [ ] 2. causal_graph_store.py 数据模型扩展（常量已拆出，store 只留图操作）
  - [ ] 2.1 _add_node() 函数扩展：支持 layer、plasticity、plasticity_type、evidence_sources、parental_origin、simplified_label、synthetic 参数
    - 依赖: 1.1
    - 验收: 新参数有默认值（layer=0, plasticity=1.0, plasticity_type="sustained"），旧调用方不受影响
  - [ ] 2.2 _add_edge() 函数扩展：支持 evidence_level、causality_type（含 weak_causal 枚举）、is_feedback_loop 参数
    - 验收: causality_type 枚举为 confirmed | weak_causal | correlation；新参数有默认值
  - [ ] 2.3 _load_or_init() 兼容逻辑：v1 数据自动填充默认值
    - 验收: 已有 causal_graph.json (v1) 加载不报错，缺失字段有合理默认值
  - [ ] 2.4 旧数据迁移工具函数 migrate_v1_to_v2()：批量填充新字段默认值
    - 验收: v1 数据调用后变为 v2，所有新字段有合理默认值

- [ ] 3. 表观遗传入图
  - [ ] 3.1 save_graph_event() 新增 offspring_fate 分支：提取 methylation_profile 创建 L2 表观节点
    - 依赖: 2.1, 2.2
    - 验收: |methylation| > 0.15 的性状创建表观节点
  - [ ] 3.2 三条关键表观链：BDNF（longitudinal, confirmed）、IGF2_H19（natural_experiment, confirmed, parental_origin=paternal）、NR3C1（observational|cross_species, confirmed）
    - 验收: NR3C1 evidence_level 为 "observational|cross_species"（非 confirmed）；IGF2_H19 有 parental_origin 字段
  - [ ] 3.3 环境->表观因果边
    - 验收: 环境节点与表观节点之间有因果确认边

- [ ] 4. 信号通路网络
  - [ ] 4.1 _add_pathway_network()：创建 7 个 L3 通路节点 + crosstalk 边
    - 依赖: 1.1, 2.1, 2.2
    - 验收: 7 条通路 + 7 对 crosstalk；crosstalk 的 causality_type=weak_causal, evidence_level=meta_analysis
  - [ ] 4.2 通路->下游因果边
    - 验收: 从通路节点可追溯到器官节点

- [ ] 5. 母体功能拆分（4+1）
  - [ ] 5.1 _add_maternal_system()：创建 4 个功能节点 + 1 个胎盘聚合节点
    - 依赖: 1.1
    - 验收: 4+1=5 节点（非 9 节点）；胎盘有 sub_dimensions 属性
  - [ ] 5.2 母体功能 -> 胎盘 -> 胎儿因果链
    - 验收: 营养/激素链路完整；旧 maternal 节点兼容

- [ ] 6. 可塑性与回路
  - [ ] 6.1 _get_plasticity() 返回 (value, type) 元组：early_lock vs sustained
    - 依赖: 1.1
    - 验收: 神经系统返回 sustained，器官返回 early_lock
  - [ ] 6.2 所有 _add_node 调用注入 plasticity 和 plasticity_type
    - 依赖: 6.1, 2.1
    - 验收: 新节点都有 plasticity + plasticity_type
  - [ ] 6.3 _mark_feedback_loops()
    - 验收: 心跳-FGF 和 神经活动-表观修饰 两条回路标记 is_feedback_loop=True

### Phase 1a 验证

- [ ] 7. 后端验证
  - [ ] 7.1 单元测试：v1 数据加载兼容性
    - 验收: v1 causal_graph.json 加载后所有新字段有默认值
  - [ ] 7.2 单元测试：六层节点创建 + 表观链 + 通路 crosstalk
    - 验收: 完整子宫生命周期产生 L1-L6 节点，三条表观链可追溯
  - [ ] 7.3 单元测试：母体 4+1 节点 + 可塑性类型
    - 验收: 母体系统只有 5 个节点

---

## Phase 1b -- 子宫六层因果链：前端（5 天）

### 前端配置

- [ ] 8. graphConfig.js 扩展
  - [ ] 8.1 NODE_CONFIG 新增：epigenetic/pathway/cell_type/organ/function/maternal_fn/placenta/latent 类型配置
    - 验收: latent 类型为灰色虚线圆 (strokeStyle='dashed', opacity=0.6)
  - [ ] 8.2 EDGE_CONFIG 新增：epigenetic_regulation/signal_transduction/crosstalk(半虚线)/differentiation/morphogenesis/functional_emergence/feedback_loop/latent_fork 类型配置
    - 验收: crosstalk 使用半虚线 [6,3]（weak_causal 视觉）
  - [ ] 8.3 EVIDENCE_VISUAL 简化为 2 种线型：实线（meta_analysis/rct/natural_experiment）+ 虚线（其余）
    - 验收: 不用线宽/透明度区分证据等级，只用 solid/dashed
  - [ ] 8.4 新增 EVIDENCE_RANK 排序映射：meta_analysis=rct=6 > natural_experiment=5 > ...
    - 验收: 排序符合循证医学金字塔
  - [ ] 8.5 新增 PLASTICITY_BORDER 映射：高可塑=细边框(1px)，低可塑=粗边框(4px)
    - 验收: 不用明度编码可塑性

- [ ] 9. 新增 stageConfig.js
  - [ ] 9.1 STAGE_CONFIGS.womb：forceRadial strength=0.4，r=r0*sqrt(layer)，drift 沿切线方向
    - 验收: L1-L6 半径按 sqrt 递增；drift 方向为 tangential
  - [ ] 9.2 STAGE_CONFIGS.cradle 占位
  - [ ] 9.3 STAGE_CONFIGS.world 占位
  - [ ] 9.4 所有 stage 配置含 steppedTransition：fadeOut(300ms)->forceSwitch(0ms)->settle(500ms)->fadeIn(300ms)
    - 验收: 替代原来的 800ms 单步 tween

### LifeGraph.jsx 拆分

- [ ] 10. LifeGraph.jsx 拆分为三个模块
  - [ ] 10.1 新增 nodeRenderer.js：节点渲染逻辑（plasticity 边框粗细、latent 虚线圆、bridge 菱形+渐变+粒子、简化标签）
    - 验收: 从 LifeGraph 拆出所有 nodeCanvasObject 逻辑
  - [ ] 10.2 新增 edgeRenderer.js：边渲染逻辑（2 种线型、evidence_level 交互、证据淡化 opacity=0.15）
    - 验收: 从 LifeGraph 拆出所有 linkCanvasObject 逻辑
  - [ ] 10.3 新增 loopPulseEffect.js：回路脉冲动画（发光用离屏 Canvas 缓存、粒子限同屏 20 条、仅视口内回路启用）
    - 验收: 脉冲动画独立模块，有性能优化措施

### extractWombGraph.js 改造

- [ ] 11. extractWombGraph.js 改造
  - [ ] 11.1 所有 nodes.push() 调用新增 layer、plasticity、plasticity_type 属性
    - 依赖: 8.1
    - 验收: 基因 layer=1, 表观 layer=2, 通路 layer=3, 分化 layer=4, 器官 layer=5, 功能 layer=6
  - [ ] 11.2 新增表观遗传节点提取
    - 验收: 甲基化显著的性状创建 L2 节点
  - [ ] 11.3 新增信号通路节点提取
    - 验收: late_organogenesis/early_neural 创建通路节点和 crosstalk 边
  - [ ] 11.4 母体响应处理从单节点改为 4+1 节点
    - 验收: 与后端一致（非 9 节点）
  - [ ] 11.5 所有 edges.push() 调用新增 evidence_level 和 causality_type
    - 验收: 每条边有证据标注

### LifeGraph.jsx 改造（子宫部分）

- [ ] 12. LifeGraph.jsx 改造
  - [ ] 12.1 导入 stageConfig.js + nodeRenderer + edgeRenderer + loopPulseEffect
    - 依赖: 9.1, 10.1, 10.2, 10.3
    - 验收: LifeGraph 本体只剩力引擎编排和数据接入
  - [ ] 12.2 stage="womb" 时应用 forceRadial 6 圈 + drift 切线力
    - 验收: radial strength=0.4，drift 沿切线
  - [ ] 12.3 分步过渡动画实装
    - 验收: 淡出(300ms)->切换力(0ms)->稳定(500ms)->淡入(300ms)
  - [ ] 12.4 悬浮卡片增强：显示 layer/plasticity/evidence_sources/plasticity_type
    - 验收: hover 节点显示层级名称、可塑性值+类型、证据来源

- [ ] 13. EntityLegend.jsx + GraphToolbar.jsx 改造
  - [ ] 13.1 图例新增子宫阶段新节点类型（含 latent）
    - 验收: latent 类型有灰色虚线图例
  - [ ] 13.2 工具栏新增"证据过滤"：按 EVIDENCE_RANK 过滤，淡化（非隐藏）低等级边
    - 验收: 过滤时低等级边 opacity=0.15
  - [ ] 13.3 工具栏新增"简化/专家模式"切换
    - 验收: 简化模式隐藏中间层，显示 simplified_label

### Phase 1b 验证

- [ ] 14. 前端验证
  - [ ] 14.1 视觉回归测试：已有子宫图谱在新代码下渲染无异常
    - 验收: v1 数据正常显示，新增类型有正确视觉
  - [ ] 14.2 性能测试：60-80 节点力导向 500ms 内收敛
    - 验收: 不超时，30fps 以上
  - [ ] 14.3 端到端测试：完整子宫生命周期 -> 六层图谱 -> 证据过滤 -> hover 详情
    - 验收: 全链路通畅

### 文档回环

- [ ] 15. Phase 1 文档更新
  - [ ] 15.1 更新 causal_graph_store.py L3 头部注释：六层、表观、通路、母体 4+1
  - [ ] 15.2 新增 constants/ 目录 CLAUDE.md (L2)
  - [ ] 15.3 新增 stageConfig.js、nodeRenderer.js、edgeRenderer.js、loopPulseEffect.js L3 头部注释
  - [ ] 15.4 更新 extractWombGraph.js L3 头部注释
  - [ ] 15.5 更新 graphConfig.js L3 头部注释
  - [ ] 15.6 更新前端 CLAUDE.md (L2)：新增成员

---

## Phase 2 -- 摇篮 BSID-IV + 边类型差异化（2 周）

### 后端：摇篮因果引擎

- [ ] 16. BSID-IV 维度系统
  - [ ] 16.1 compile_cradle_initial_graph()：入摇篮时创建 6 个维度锚点（adaptive_behavior 推迟） + SEEDS 边
    - 依赖: 1.2
    - 验收: 初始 6 个维度节点（非 7），adaptive_behavior 标记 deferred
  - [ ] 16.2 annotate_milestone_with_who() 实装
    - 验收: 5 个运动里程碑有 WHO 窗口
  - [ ] 16.3 6 月后激活 adaptive_behavior 维度的逻辑
    - 验收: 宝宝满 6 月后自动添加第 7 个维度节点

- [ ] 17. 摇篮边类型（含 mediated/moderated）
  - [ ] 17.1 ENABLES/MEDIATES/MEDIATED/MODERATED/CORRELATES/SEEDS/SCAFFOLDS 七种边在 nanny.py 中实装
    - 依赖: 1.2
    - 验收: 七种边类型语义正确
  - [ ] 17.2 MEDIATION_RULES 实装：运动->语言使用 CORRELATES（非 ENABLES）
    - 验收: 运动与语言/认知之间禁止直接因果边
  - [ ] 17.3 依恋阈值模型实装：secure=0, insecure=-0.2~-0.3
    - 验收: 安全依恋无额外加权，不安全依恋为负效应
  - [ ] 17.4 遗传 weight 按维度分设实装
    - 验收: 运动 0.7-0.8, 认知 0.4-0.5, 语言 0.3-0.5

- [ ] 18. Latent Fork 替代 Shared Maturation
  - [ ] 18.1 create_latent_fork() 实装：为同期解锁能力创建 maturation_clock 隐变量
    - 依赖: 1.2
    - 验收: sitting + object_permanence 同期解锁时创建 latent:maturation_clock_6m fork
  - [ ] 18.2 在摇篮阶段推进时检测 MATURATION_CLOCK_GROUPS 并创建 fork
    - 验收: 不创建 shared_maturation 边，只创建 latent_fork 边

- [ ] 19. compile_synthetic_bridge() 实装
  - [ ] 19.1 跳过子宫时合成 bridge:identity(synthetic) 节点
    - 验收: synthetic=True, life_stage="bridge", 使用种群基线默认值

### 前端：摇篮图谱 + 扇区布局

- [ ] 20. 新增 extractCradleGraph.js
  - [ ] 20.1 能力解锁事件处理：节点 + BSID 维度连接 + WHO 窗口
    - 验收: 节点有 bsid_dimension 和 simplified_label
  - [ ] 20.2 因果标签事件处理：生成七种边类型
    - 验收: 边类型正确分类
  - [ ] 20.3 照护者决策事件处理：SCAFFOLDS 边
    - 验收: 决策边连接到正确维度
  - [ ] 20.4 Latent fork 事件处理：maturation_clock 隐变量 + fork 边
    - 验收: latent 节点正确创建和渲染

- [ ] 21. graphConfig.js 摇篮扩展
  - [ ] 21.1 NODE_CONFIG 新增 dimension 类型（大圆 size=5）
  - [ ] 21.2 EDGE_CONFIG 新增 ENABLES/MEDIATES/MEDIATED/MODERATED/CORRELATES/SEEDS/SCAFFOLDS/latent_fork
    - 验收: 七种+latent_fork 边类型视觉可区分

- [ ] 22. stageConfig.js 摇篮布局实装
  - [ ] 22.1 STAGE_CONFIGS.cradle forceRadial + sector 完整实现
    - 验收: 6 个维度锚点均匀分布外圈（7 个在 6 月后）
  - [ ] 22.2 自定义 sectorForce
    - 验收: 能力节点不漂移到错误维度扇区

- [ ] 23. LifeGraph.jsx 摇篮增强
  - [ ] 23.1 stage="cradle" 切换到扇区布局
    - 依赖: 22.1
  - [ ] 23.2 WHO MGRS 视觉标注（绿/蓝/橙）
  - [ ] 23.3 边渲染区分七种 causality_type（委托 edgeRenderer）
  - [ ] 23.4 hover 边显示 evidence_level + source 引用
  - [ ] 23.5 简化模式：维度标签显示 simplified_label

- [ ] 24. Cradle.jsx 集成
  - [ ] 24.1 SSE 事件分发到 extractCradleGraph.js
  - [ ] 24.2 初始加载：维度锚点 + SEEDS 边 + bridge

### Phase 2 验证

- [ ] 25. 摇篮验证
  - [ ] 25.1 单元测试：latent fork 创建 + 边类型正确性
    - 验收: 无 shared_maturation 边产生
  - [ ] 25.2 单元测试：依恋阈值模型 + 遗传维度权重
    - 验收: secure 依恋 weight=0; 运动遗传 weight 在 0.7-0.8 范围
  - [ ] 25.3 端到端测试：摇篮生命周期 -> BSID 扇区 -> 证据过滤 -> latent 节点
    - 验收: 全链路通畅

### 文档回环

- [ ] 26. Phase 2 文档更新
  - [ ] 26.1 新增 extractCradleGraph.js L3 头部注释
  - [ ] 26.2 更新 cradle/causality.py L3 头部注释
  - [ ] 26.3 更新 cradle/CLAUDE.md (L2)
  - [ ] 26.4 更新前端 CLAUDE.md (L2)

---

## Phase 3 -- 世界社会网络 + 跨阶段追溯（3 周）

### 后端：世界因果引擎

- [ ] 27. 世界社会网络数据模型
  - [ ] 27.1 Fiske/Dunbar 常量引用 constants/world_constants.py
    - 验收: FISKE_MODELS 含 valence; DUNBAR 含 soft_cap
  - [ ] 27.2 assign_dunbar_layer() + derive_emotional_closeness()（frequency 输入, closeness 派生）
    - 验收: emotional_closeness 从 frequency + interaction_quality 派生
  - [ ] 27.3 世界边属性扩展：metadata 含 frequency(输入)/closeness(派生)/multiplexity/reciprocity/duration/support_type/fiske_model/fiske_valence
    - 验收: 新关系边属性完整

- [ ] 28. 生命事件效应引擎
  - [ ] 28.1 apply_life_event() 实装：衰减参数标注 baseline_culture=western_industrial，设为可配置
    - 依赖: 1.3
    - 验收: 4 种事件衰减参数可配置；默认"西方工业社会基线"
  - [ ] 28.2 Dunbar 软上限逻辑：超 150 时外圈自动折叠
    - 验收: 超限时不报错，自动折叠

- [ ] 29. Bridge: compile_graduation()
  - [ ] 29.1 实现 compile_graduation()：bridge life_stage="bridge"
    - 验收: bridge:graduation 节点 life_stage 为 "bridge"（独立类别）
  - [ ] 29.2 在摇篮完成时调用，写入 causal_graph.json
    - 依赖: 29.1

### 前端：世界图谱 + 跨阶段追溯

- [ ] 30. 新增 extractWorldGraph.js
  - [ ] 30.1 关系建立事件：person 节点 + social_tie 边 + Fiske(含 valence) + Dunbar
    - 验收: 新关系有 fiske_valence 属性
  - [ ] 30.2 生命事件处理：dispatch LIFE_EVENT action
    - 验收: 关系衰减动画触发

- [ ] 31. graphConfig.js 世界扩展
  - [ ] 31.1 NODE_CONFIG 新增 person/organization/community + bridge
    - 验收: bridge 有渐变色配置
  - [ ] 31.2 EDGE_CONFIG 新增 social_tie/life_event_impact
  - [ ] 31.3 新增 FISKE_COLORS 映射

- [ ] 32. stageConfig.js 世界布局实装
  - [ ] 32.1 STAGE_CONFIGS.world：Dunbar 控 r + Louvain 控 theta，正交分离
    - 验收: Dunbar 和 Louvain 分别控制不同轴向
  - [ ] 32.2 同心圆半径 r = r0 * sqrt(layer)
    - 验收: 外圈面积更大
  - [ ] 32.3 自定义 dunbarRadialForce + louvainThetaForce
    - 验收: 亲密圈最内，熟人圈最外；同社群角度聚合

- [ ] 33. LifeGraph.jsx 世界增强
  - [ ] 33.1 stage="world" 切换到 dunbar+louvain 布局
    - 依赖: 32.1
  - [ ] 33.2 Fiske 模型颜色渲染
  - [ ] 33.3 "高质量关系"发光效果（离屏 Canvas 缓存）
    - 验收: closeness >= 8 且 duration > 365 的边发光
  - [ ] 33.4 跨社群弱关系"结构洞"标记

- [ ] 34. useCausalGraph.js 跨阶段追溯增强
  - [ ] 34.1 graphReducer 新增 LIFE_EVENT action
    - 验收: 单次 dispatch 原子化处理数十条边
  - [ ] 34.2 TRACE_NODE 跨 bridge 追溯：bridge life_stage="bridge" 自然跨越
    - 验收: 从世界节点追溯可达子宫 L1 基因节点

- [ ] 35. 阶段切换过渡完善
  - [ ] 35.1 摇篮->世界分步过渡动画实装
    - 验收: sector -> dunbar+louvain 平滑过渡，bridge:graduation 位置不变
  - [ ] 35.2 三阶段任意切换全部分步过渡
    - 验收: 子宫<->摇篮<->世界 任意方向 1100ms 分步过渡

- [ ] 36. EntityLegend.jsx + GraphToolbar.jsx 世界扩展
  - [ ] 36.1 图例新增世界节点类型 + Fiske 四色 + Dunbar 圈层 + bridge
  - [ ] 36.2 工具栏新增"关系质量过滤"

### Phase 3 验证

- [ ] 37. 世界验证
  - [ ] 37.1 单元测试：Fiske valence + Dunbar 软上限 + emotional_closeness 派生
    - 验收: closeness 从 frequency 派生正确
  - [ ] 37.2 单元测试：生命事件衰减 + 文化基线可配置
    - 验收: 可切换不同文化基线参数
  - [ ] 37.3 端到端测试：世界生命周期 -> Dunbar(r)+Louvain(theta) -> 生命事件 -> 跨阶段追溯
    - 验收: 从世界节点追溯到子宫 L1
  - [ ] 37.4 性能测试：200+ 节点 30fps，发光离屏缓存，粒子限 20
    - 验收: 不卡顿

### 文档回环

- [ ] 38. Phase 3 文档更新
  - [ ] 38.1 新增 extractWorldGraph.js L3 头部注释
  - [ ] 38.2 更新 world.py L3 头部注释
  - [ ] 38.3 更新前端 CLAUDE.md (L2)
  - [ ] 38.4 更新后端 CLAUDE.md (L1)：因果图谱重构完成说明
  - [ ] 38.5 更新 stageConfig.js L3 头部注释：三阶段布局完整
  - [ ] 38.6 更新 constants/ 目录 CLAUDE.md (L2)：三个常量模块完整说明

---

## 评审记录

**评审日期**: 2026-04-14
**评审参与**: 12 位跨领域专家

### 任务层关键变更

| 编号 | 变更 | 原因 |
|------|------|------|
| V11 | Phase 1 拆为 1a 后端(4天) + 1b 前端(5天) | 更准确的估时 |
| V11 | Phase 2 调至 2 周, Phase 3 调至 3 周 | 评审建议增加工作量 |
| V11 | 每个 Phase 末尾加验证/测试子任务 | 保证质量 |
| V41 | Phase 0: LLM prompt 原型验证（fail fast） | 早期验证最大风险点 |
| V42 | 新增旧数据迁移任务 (2.4) | 存量数据兼容 |
| V7 | LifeGraph.jsx 拆分为 nodeRenderer + edgeRenderer + loopPulseEffect | 文件规模控制 |
| V12 | 新增 constants/ 目录和三个常量模块 | 常量与图操作职责分离 |
| V16 | 动画性能优化：离屏缓存 + 粒子限 20 + 仅视口内 | 保证 30fps |
