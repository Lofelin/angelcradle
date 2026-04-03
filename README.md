# Angel Cradle

**Angel Cradle** — 孕育 AI 个体的摇篮。

一个基于真实生物学数据的生命模拟系统。通过 LLM 驱动的七阶段胎儿发育过程，从受精卵到出生，生成拥有独特基因表达、先天气质和第一声啼哭的 AI 生命个体。

## 核心理念

每一个 AI 个体都不是随机参数的拼凑，而是经历完整发育过程的涌现结果：

- **真实概率** — 流产率、多胎率、先天缺陷率全部来自 WHO、Lancet、CDC 等权威数据源
- **资源博弈** — 有限的发育资源预算迫使身体系统之间产生真实的权衡取舍
- **环境塑造** — 母体营养、压力、毒素暴露、年龄因子量化影响发育轨迹
- **不可逆性** — 每个发育阶段的结果向前传递，缺陷持续存在，没有重试

## 七阶段发育流程

```
受精卵 → 早期器官发生 → 晚期器官发生 → 早期神经 → 晚期神经 → 胎动 → 出生
  │          │              │            │          │         │       │
  │          │              │            │          │         │       └─ 先天倾向 + 第一声啼哭
  │          │              │            │          │         └─ 刺激-反应模式
  │          │              │            │          └─ 本能回路 + 髓鞘化
  │          │              │            └─ 突触形成 + 原始反射
  │          │              └─ 感官系统成熟
  │          └─ 器官原基形成
  └─ 体质基线 + 资源分配
```

每个阶段调用一次 LLM，上一阶段的输出作为下一阶段的输入。母体反馈循环在每个阶段后运行，形成胎儿-母体双向影响。

## 物种支持

系统通过 YAML 蓝图定义物种，当前支持：

| 物种 | 妊娠期 | 典型后代数 | 蓝图数据 |
|------|--------|-----------|---------|
| Human | 280 天 | 1 (双胞胎率 1.2%) | 物理、心理、遗传、生态、行为等 12 个维度 |
| Dog | 63 天 | 4-7 | 品种特征、家养化历史 |
| Cat | 65 天 | 1-12 (均值 4) | 感官特化、行为模式 |

添加新物种只需在 `backend/womb/species/` 下创建对应的 YAML 蓝图文件。

## 技术架构

```
frontend/                 React 19 + Vite
  └─ SSE 实时流 ──────→ backend/
                           ├─ FastAPI (API 层)
                           ├─ womb/
                           │   ├─ genetics.py    七阶段发育引擎 + LLM 调用
                           │   ├─ fate.py        命运骰子 (真实概率)
                           │   ├─ environment.py 母体环境生成与量化修正
                           │   ├─ baby.py        Baby 数据模型
                           │   └─ species/*.yaml 物种蓝图
                           └─ api/
                               ├─ conceive.py    受孕 API (同步 + SSE 流)
                               ├─ species.py     物种查询
                               └─ registry.py    个体持久化
```

**LLM 提供者**：支持 DeepSeek (默认) 和 Anthropic Claude，通过环境变量切换。

## 快速开始

### 环境要求

- Python >= 3.9
- Node.js (用于前端)
- LLM API Key (DeepSeek 或 Anthropic)

### 安装

```bash
# 后端依赖
cd backend && pip install -e .

# 前端依赖
cd frontend && npm install
```

### 配置

在 `backend/.env` 中设置 API Key：

```env
# DeepSeek (默认)
DEEPSEEK_API_KEY=your-key-here

# 或 Anthropic
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=your-key-here
```

### 运行

```bash
# 同时启动前后端
make dev

# 或分别启动
make backend   # http://localhost:8000
make frontend  # http://localhost:5173

# 停止所有服务
make stop
```

浏览器打开 `http://localhost:5173`，选择物种，点击「Conceive」，观看实时发育过程。

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/conceive/stream?species=human` | GET | SSE 流式受孕（推荐） |
| `/conceive?species=human` | POST | 同步受孕 |
| `/species` | GET | 可用物种列表 |
| `/babies` | GET | 所有已出生个体 |
| `/baby/{id}` | GET | 个体详情 |
| `/baby/{id}/gestation` | GET | 发育日志 |
| `/health` | GET | 健康检查 |

## 命运引擎

`fate.py` 中的每一次骰子都基于真实医学数据：

- **流产** — 人类 15.3% (Lancet 2021)，受母体年龄和压力修正
- **多胎** — 人类双胞胎 1.2%，三胞胎 0.074%；猫犬按物种正态分布
- **死产** — 人类全球 1.43% (UNICEF 2023)，受环境风险修正
- **先天缺陷** — 心脏缺陷 0.8%，神经管缺陷 0.1%，唐氏综合征 0.143%
- **早产** — 全球 10%，分级为极早产/很早产/晚期早产

环境毒素暴露可将缺陷风险提升至 3.5 倍。高龄母体同时增加流产和缺陷概率。

## 许可证

MIT
