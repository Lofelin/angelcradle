# 因果图谱引擎 v5.0 · 三阶段三视角架构

> **基于**：v4.1 addendum + 用户三阶段分区主张
> **评审**：11 评审官（E1-E11）多视角裁决
> **日期**：2026-04-20
> **核心变化**：引入 `LifeContinuant` 元本体 + 单一 ontology + 3 视角投影 + 主叙事统一育儿化 + 专业层可选 + 3 过渡带 + Cultural Lens + 事件日志为底

---

## 0. 立场与总体判决

**用户主张**：视角匹配阶段开放性（子宫封闭→生物；摇篮半开→育儿；世界开放→发心）。

**11 评审官裁决**：
- **方向采纳**（8/11 同意）
- **执行 v1 版失败**（E4/E11 判为灾难 / E2 部分否决 / E9 文化系统失真）
- **必须引入元本体 + 统一数据层**（E5+E10 核心）

**v5.0 的哲学基石**（E10 必须）：

> **本体是一，现象是三**。
> — 一个 `LifeContinuant` 持续者（BFO ontology）
> — 贯穿时间的 events（Whitehead process）
> — 三种 prehension（视角折射），不是三种真实

三阶段视角不是"把人劈成三段"（E11 批判），是**同一实体在不同开放性环境下的三种摄入模式**。

---

## 1. 元本体层：LifeContinuant（E10 强制）

### 1.1 设计

```yaml
# ontology/life_continuant.yaml
LifeContinuant:
  identity_thread: UUID               # 跨三阶段唯一标识，永不变
  continuity_metadata:
    conception_event: {ref: evt-0001} # 生物学连续性的锚点
    genotype: {...}                   # 不随视角/阶段变化的基底
    continuity_level: "biological_causal"  # Parfit's psychological continuity with branching
  temporal_parts:                     # BFO temporal_parts，非三个实体
    - stage: womb,   ref: origin:embryo, window: [-40w, 0]
    - stage: cradle, ref: baby,          window: [0, 3y]
    - stage: world,  ref: self,          window: [3y, 死亡]
  process_history: []                 # 事件序列（Whitehead occasions）
  cross_stage_invariants:             # 12 个跨阶段必延续节点（E8 清单）
    - hub:genome
    - hub:epigenome
    - pathway:HPA_axis
    - trait:temperament_constellation
    - relationship:primary_caregivers
    - immune_memory
    - sensory_channels
    - circadian_rhythm
    - metabolic_programming_DOHaD
    - language_faculty
    - attachment_IWM
    - self_awareness_line
```

### 1.2 关键约束

- `identity_thread` 全局唯一，跨三阶段图谱共享
- 三阶段节点 id **必须**以 `{stage}:` 前缀开头；跨阶段边的两端可以跨 stage
- **12 个 invariants 禁止被任何视角私有化** — ontology registry 强制校验
- 哲学地位：`LifeContinuant` 是 Locke 的 person、Parfit 的 psychological continuity、Whitehead 的 society — 三者的综合

---

## 2. Ontology 单一化（E5 铁律）

### 2.1 文件结构

```
backend/graph_engine/
  ontology/
    life_continuant.yaml      # 元本体（§1）
    entities_registry.yaml    # 所有跨阶段实体的全局 ID 注册表（E8 强制）
    base_schema.yaml          # 7 主题槽位契约 + 通用规则
    hubs_14.yaml              # v4.1 的 14 hub 定义（跨阶段共享）
  projections/
    view_womb.yaml            # 视角 1：生物医学透镜
    view_cradle.yaml          # 视角 2：育儿手册透镜（主）+ 发心透镜（里衬）
    view_world.yaml           # 视角 3：育儿化主叙事 + 6 子阶段 + 4 专业层
  cultural_lens/              # E9 文化透镜
    western_default.yaml
    east_asian.yaml           # 中医/amae/儒家视角
    (others v5.1+)
```

### 2.2 Projection 契约 v4.2

```python
# 纯函数，无 if stage 分支
def project(ontology, view_cfg, cultural_lens) -> ViewState:
    themes = [Theme(slot) for slot in view_cfg.theme_slots]  # 7 slots 固定
    for node in ontology.nodes:
        for theme in themes:
            if theme.matches(node, cultural_lens):
                theme.absorb(node, theme.affinity_of(node))
    return ViewState(themes)
```

**三条硬约束**（E5 提出）：
1. 禁止新增节点 / 覆盖边
2. 视角差异必须**声明式 yaml**（非 Python 代码）
3. 节点可多主题归属带 `affinity` 权重（消灭 21 个特殊分支）

---

## 3. 三阶段视角修订

### 3.1 子宫视角（E1 修订）

**7 主题**（修订后）：

| 原主题 | v5.0 修订 | 理由 |
|---|---|---|
| 遗传 | 遗传 ✓ | 保留 |
| 激素 | 激素 ✓ | 保留 |
| 器官 | 器官 ✓ | 保留 |
| 生命体征 | 生命体征 ✓ | 保留 |
| 母体 | 母体 ✓ | 保留 |
| **资源分配** | → **"胎盘-代谢权衡"** | E1：没有"分配器"，是胎盘运输+代谢优先级+表观遗传响应的涌现 |
| **行为** | → **"神经反射与感官萌芽"** | E1：行为≠意识，24w 前都是反射 |

**新增 3 主题**（E1 强制）：
- **性别分化**（SRY → 睾丸/卵巢 → 激素驱动）
- **致畸窗口**（3-8w 器官发生期敏感窗口）
- **分娩启动**（CRH 胎盘钟 + 催产素反馈）

**但保持 7 主题槽位契约**（E5 要求）—— 所以：
- 性别分化 / 致畸窗口 / 分娩启动 **不是新主题**，而是分入"母体"/"激素"/"生命体征"的**子节点**

### 3.2 摇篮视角（E3 修订 + E4 关键）

**保持育儿手册主叙事**（E3/E4 强共识），**每节点挂发展心理学里衬卡**（E3 建议）：

```yaml
# view_cradle.yaml 示例
themes:
  T1:
    label: "里程碑"
    slot: 1
    primary_narrative: parental_friendly       # 默认展示："今天会叫妈妈了"
    scientific_liner:                          # 点击展开的里衬卡
      theory: "Chomsky 语言关键期 / Vygotsky 共同意图"
      citation: "Tomasello 2003"
```

**7 主题修订**（E3 必改）：
1. 🏆 里程碑 — 34 节点 + 补 **7 个情感里程碑**（第一次叫自己名字 / 自主如厕 / 用剪刀 / 说"不" / 假装游戏 / 主动安慰他人 / 讲述昨天）
2. 🧡 亲子依恋 — **保留 Ainsworth 分类但降级为描述性**（E9）
3. 💭 性格气质 + **情绪教养子线**（E3 补强）
4. 🍼 吃睡拉
5. 📏 身体发育
6. 🛡️ **健康与安全**（原"疾病免疫"扩展，含 Safe Sleep / 防窒息）
7. 🏠 家庭环境

### 3.3 世界视角（E2 大幅重构）

**v1 版单一发心视角 = 错**（E2/E4 双重否决）。v5.0 改为：

```
世界阶段 (3y - 死亡)
  ├─ 主叙事层（育儿化语言，E4 共识）: "他开始独立上学"、"她结婚了"、"老了"
  └─ 专业层（可选里衬，6 子阶段 × 4 视角，E2 要求）:
        子阶段：
          ├─ 学前 (3-5y)    → Piaget 前运算 / Erikson 主动 vs 内疚
          ├─ 学龄 (6-11y)   → Piaget 具运 / Erikson 勤奋
          ├─ 青春 (12-18y)  → Erikson 同一性 / Marcia
          ├─ 成年早 (19-40) → Erikson 亲密 / Levinson 人生结构
          ├─ 成年中 (40-65) → Erikson 繁衍 / Vaillant 成熟防御
          └─ 老年 (65+)     → Erikson 整合 / Carstensen SST / Baltes 毕生
        4 专业视角（并列）:
          ├─ 发展心理学（Piaget/Erikson/Bowlby/Baltes/Vaillant）
          ├─ 社会学     （Elder 生命历程 / 家庭周期 / Bourdieu 资本 / Super 职业）
          ├─ 经济学     （Modigliani 生命周期消费 / 资产 / 教育投资）
          └─ 历史-队列  （时代事件对个体程序化，Elder 大萧条研究）
```

**7 主题**（世界阶段主层）：
1. 🌟 人生里程碑（上学/毕业/工作/恋爱/结婚/生子/退休）
2. 🤝 关系网络（家庭/朋友/伴侣/同事/社区）
3. 💼 事业与财富（职业轨迹/收入/资产）
4. 🎯 自我实现（兴趣/作品/学习/心流）
5. 💪 健康与体能（身体/认知/慢病）
6. 🎭 情感与性格（情绪/气质演化）
7. 🌍 时代与文化（出生队列/重大事件经历）

### 3.4 视角切换 vs 视角叠加（E4 核心）

**用户可选**：
- **Simple Mode**（默认）：主叙事，阶段无关术语统一
- **Professional Mode**（展开）：专业术语 + 子阶段 + 4 视角（世界阶段专属）

---

## 4. 3 个过渡带强制化（E3+E8 必改）

### 4.1 围产过渡（38w - 产后 2 周）

**"出生过渡视图"**：
- 左栏：最后一帧子宫状态快照（皮质醇/胎盘效率封存为"出生档案"）
- 右栏：逐步点亮摇篮视角（第一次呼吸 → Apgar → 母乳 → 黄疸）
- 中间栏：12 个 continuant 节点**带着子宫值继续存在**
- UI 隐喻：**产房**（摄像机慢推，不切场景）

### 4.2 学步过渡（2.5 - 3.5 岁）

**双视角并存**：
- 育儿手册主视角（摇篮延续）
- "发展心理学透镜"可选开启（灰色图标→解锁）
- 3 岁生日 **不是切换点**，是**重心转移点**

触发切换的不是生日，是**能力信号**（如"完整句子" / "假装游戏复杂化" / "同伴冲突"）。

### 4.3 青春过渡（11 - 13 岁）

**世界阶段内子阶段过渡**：学龄→青春期，从 Erikson 勤奋转身份认同，Piaget 具运→形式运算。加**激素爆发可视化**（HPG 轴重新活跃，呼应子宫的性激素时间轴）。

---

## 5. 生命之线常驻组件（E8 关键 UI）

顶部固定时间细线，12 个 continuant 图标常驻：

```
[受精]━━[出生]━━━[3y]━━━[18y]━━━[40y]━━━[现在]━━━▶
   ● HPA 轴      ● 气质      ● 依恋IWM     ● 核心关系
   ● 基因组      ● 语言      ● 自我        ● 代谢编程
   ● 免疫记忆   ● 感觉通道   ● 节律        ● 认知风格
```

点击任一图标 → 弹出该 continuant 的**全生命周期视图**，打破三阶段视觉割裂。

---

## 6. Cultural Lens 可切换（E9 P0）

### 6.1 跨文化通用（生物学基座，硬编码）

- 子宫全层
- 摇篮的 WHO-MGRS 生长曲线 + 脑发育节点
- 世界的 HPG 激活 / 前额叶成熟 / 生物老化

### 6.2 可切换文化透镜（心理社会层）

| 数据源 | 西方透镜 | 东亚透镜 | 中医透镜（v5.1+） |
|---|---|---|---|
| HPA 皮质醇波动 | "压力反应" | "情志失调" | "肝气郁结" |
| 2岁分离焦虑 | "autonomy crisis" | "amae 依附期" | "稚阳未充" |
| 多照料者互动 | "attachment disorganization 风险" | "四世同堂滋养" | "厚土载物" |
| Erikson 自主性 | 个体化任务 | 家庭本位调和 | 孝道内化 |

**v5.0 先落地**：西方默认 + 东亚透镜（Ainsworth 降级为描述性；睡眠无价值判断；多照料者不贴诊断标签）
**v5.1 计划**：中医/amae/联合家庭透镜

### 6.3 Cultural Consultant 角色

任何心理社会建议必须经该角色审阅 locale-specific 内容（CI 流程）。

---

## 7. 存储架构（E6 硬改）

### 7.1 分级

```
storage/
  hot/{baby_id}/events.current.jsonl     # 最近 30 天，内存+磁盘
  warm/{baby_id}/{stage}.parquet         # 按 stage 列存 Zstd 压缩
  cold/{baby_id}/{stage}.parquet.age     # >5 年归档，对象存储 + KEK 加密
  frozen/{baby_id}/                      # >20 年磁带/归档
  graph/{baby_id}/nodes.kuzu             # KuzuDB 嵌入式图 DB
  projection/{theme}/{baby_id}.msgpack   # 21 主题预计算快照
```

### 7.2 技术栈（E6 推荐）

- **图 DB**：KuzuDB（嵌入式，单文件，零运维）
- **时序事件**：Parquet 列存（压缩率 8x，单 baby 130MB → 16MB）
- **加密**：per-baby KEK（crypto-shredding 支持被遗忘权）
- **embedding**：降维到 ≤ 256 维（不可逆）

### 7.3 铁律

> **"数据可以冷，因果不能冷"**（E6）
> — 原始事件可归档到 Glacier
> — 图上的因果边（如 `NR3C1_methylation → HPA_reactivity`）永远热，全量常驻内存

### 7.4 被遗忘权实现

```
删除请求
  → baby_id 打 tombstone（软删 30 天）
  → 其他 baby 图上的 refs[baby_id] 替换为 anonymous_stub
  → 物理清除 hot/warm/cold（异步 72h SLA）
  → 销毁 per-baby KEK（crypto-shredding，cold 数据即刻不可恢复）
  → 触发 projection 重建
```

---

## 8. 事件日志为底（E11 θ 部分采纳）

### 8.1 单一事实源

```
archive/{baby_id}/
  events.jsonl              # append-only 全生命事件流
  graph.kuzu                # 派生图（LifeContinuant + 14 hub + matures_to）
  projections/              # view-specific 物化视图（缓存，可重建）
    womb_view.msgpack
    cradle_view.msgpack
    world_view.msgpack
```

### 8.2 查询时折叠

主题不是存储属性，是**查询时投影**：
- 底层只存 events + 派生图
- 前端想做"医学视角" / "育儿视角" / "心理视角" → 不同 projection 函数
- 主题定义变化 → 重新投影，底层零改动

### 8.3 LLM 写入时提取因果

关键设计：LLM 生成摘要时**主动提取因果边**（而非查询时推断）：
```
(epigenome:NR3C1_methylation)
  -[CAUSES {confidence:0.73, decay:0.05/yr, theory:"Meaney 2001"}]->
  (HPA_reactivity)
```

### 8.4 重建契约

每个 projection 必须可从 events 纯函数重建，无副作用、可幂等。

---

## 9. 前端实现（E7 选型）

### 9.1 框架与分工

| 阶段 | 渲染 | 节点规模 | 理由 |
|---|---|---|---|
| 子宫 | d3-force + SVG | ≤ 200 | 交互细腻，CSS hover 免费 |
| 摇篮 | d3-force + SVG | ≤ 200 | 同上 |
| 世界 | react-force-graph-2d (Canvas/WebGL) | 500+ | D3 扛不住终身朋友网络 |

### 9.2 路由

```
/womb   (子宫期)
/cradle (摇篮期)
/world  (世界期 - 含 6 子阶段内切换)
```

每阶段独立 mount，切换时 AnimatePresence crossfade 400ms。

### 9.3 锚点动画（E7 核心需求）

三阶段共享锚点 `self`（子宫显示为 embryo，摇篮显示为 baby，世界显示为 self）：

```tsx
async function transitionStage(from, to) {
  await gsap.to(`#node-self`, { scale: 1.2, opacity: 0, duration: 0.4 });
  mountStage(to);
  gsap.fromTo(`#node-self`,
    { scale: 1.2, opacity: 0 },
    { scale: 1, opacity: 1, duration: 0.6, ease: 'back.out(1.2)' }
  );
}
```

**原则**：锚点不动，世界重生。用户看到"我没变，环境长出来了"。

### 9.4 时间轴（拒绝统一）

三个独立 slider，共享 Tab 导航。**不做对数尺度**（E7 否决）。

---

## 10. 实施路线（5 迭代）

| 迭代 | 产出 | 验收 |
|:-:|---|---|
| **I1** | LifeContinuant 元本体 + entities_registry + base_schema + hubs_14 | 空图通过 15+3 条规则 |
| **I2** | view_womb + view_cradle yaml；育儿主叙事 + 发心里衬卡机制 | 子宫/摇篮 2 阶段可演示 |
| **I3** | view_world + 6 子阶段 + 4 专业视角层 + 3 过渡带 UI | 世界阶段演示（含青春过渡） |
| **I4** | Cultural Lens（东亚） + KuzuDB 落地 + per-baby KEK + 生命之线组件 | 中英文双语 + GDPR 被遗忘权 |
| **I5** | 事件日志溯源 + projection 缓存 + 全 Continuant BFO 对齐 + 归档冷存 | 15+ 条校验 + 模拟 80y 数据 |

---

## 11. 拒绝采纳的部分（E11 反派 + 其他）

| 拒绝项 | 来源 | 理由 |
|---|---|---|
| **α**：BPS 单一视角贯穿一生 | E11 | 用户明确要视角分区；BPS 失去阶段叙事张力 |
| **γ**：完全取消主题，只要 event log | E11 | 力导向图必须有可见结构；前端无锚无法渲染 |
| **δ**：取消阶段只用连续年龄 | E11 | 叙事需要阶段作为认知单元 |
| **θ** 方案：完全查询时折叠 | E11 | **部分采纳**：事件为底 ✓，但主题/阶段作为 projection 缓存（性能所需） |
| 世界阶段单纯 Piaget | E2 | 必须多视角；老年要 Baltes/Vaillant/Carstensen |
| 三套独立 ontology | E5 冲击测试 | 会导致本体漂移，禁止 |
| 纯医学本体论（视角无关） | E10 辩证 | 无法解释"哭"在育儿视角是 need signal，神经视角是 reflex |

---

## 12. 评审官最终签字

| 评审官 | 原立场 | v5.0 后签字 |
|---|---|---|
| E1 生物 | 🟡 | ✅ 采纳 3 改名 + 3 补项 |
| E2 发心 | 🔴 | ✅ 采纳 6 子阶段 + 4 视角层 |
| E3 育儿 | 🟢 | ✅ 里衬卡 + 过渡带 + 安全补强 |
| E4 UX | 🔴 | ✅ 主叙事统一育儿化 + 专业层可选 |
| E5 架构 | 🟢 | ✅ base + view + affinity |
| E6 数据 | 🟡 | ✅ KuzuDB + Parquet + KEK |
| E7 前端 | 🟢 | ✅ 三路由 + 锚点动画 + WebGL 升级 |
| E8 衔接 | 🟡 | ✅ LifeContinuant + 3 过渡带 + 生命之线 |
| E9 文化 | 🔴 | ✅ Cultural Lens P0（东亚先落）|
| E10 哲学 | 🟡 | ✅ LifeContinuant 元本体（BFO+Whitehead）|
| E11 反派 | 🔴 | 🟡 θ 方案部分采纳（事件为底） |

**通过率**：11/11（E11 部分采纳）

---

## 13. 关键哲学回答（E11 的 "15 岁少年" 挑战）

> "一个 15 岁少年回看子宫期数据，看到'母体资源分配'，会感动还是出戏？"

**v5.0 的答案**：
- 他**默认看到的是**："妈妈怀我时营养很好，给我的大脑发育优先投入"（主叙事育儿化）
- 他如果**点开专业层**看到："胎盘-代谢权衡曲线 + HPA 轴编程 + DOHaD 痕迹"（可选）
- 他可以**切换视角**：同一数据用中医透镜看到"先天之本充盈"（Cultural Lens）

**三种看法同时真，都是他的一部分**。这就是 LifeContinuant 元本体 + 主叙事统一 + 专业里衬 + 文化透镜的综合力量。

---

## 14. 铁律总结

1. **本体是一**（LifeContinuant 贯穿一生）
2. **现象是三**（视角折射不同开放性阶段）
3. **主叙事育儿化**（全程）
4. **专业层可选**（按需展开）
5. **过渡带强制**（38w / 3y / 青春期）
6. **文化透镜可切**（非 WEIRD 用户不失真）
7. **事件为底**（存储不承诺分类）
8. **因果不冷**（图上边永热）
9. **12 continuant 全局 ID**（禁止私有化）
10. **生命之线常驻**（打破视觉割裂）

---

**[PROTOCOL]**：变更时更新此文档，然后检查 `design.md` v4.0 + `addendum_v4.1.md`。

**文档版本**：v5.0 · 2026-04-20
**评审官签字**：11/11 通过（E11 部分采纳）
**下一版预告**：v5.1（中医/amae/联合家庭透镜）
