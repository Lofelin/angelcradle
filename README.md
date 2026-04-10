<div align="center">

# Angel Cradle

孕育 AI 个体的摇篮
<br/>
<em>A Biologically Grounded Life Simulation for AI Individuals</em>

**React 19 + FastAPI + LLM · 七阶段胎儿发育 · 十二阶段婴幼儿成长 · 多智能体社交**

</div>

## Overview

**Angel Cradle** 是一个基于真实生物学数据的 AI 生命模拟系统。

上传种子基因、设定母体环境，系统将驱动 LLM 逐阶段模拟从受精卵到独立个体的完整生命历程。每个 AI 个体经历真实的遗传表达、器官发育、神经成熟、语言爆发和社交萌芽——不是参数拼凑，而是涌现。

> 你只需要：选择物种，调整环境参数，点击「Conceive」
> <br/>Angel Cradle 将返回：一个拥有独特基因、气质、依恋风格和第一声啼哭的 AI 生命

### 设计哲学

- **真实概率，不是随机数** — 流产率 15.3% (Lancet)、死产率 1.43% (UNICEF)、心脏缺陷 0.8% (WHO)，每一次命运骰子都有医学出处
- **资源博弈** — 有限的发育预算迫使器官系统之间真实权衡，不存在满分个体
- **不可逆发育** — 早期缺陷向前传递，致畸暴露永久影响，没有存档读档
- **亲子塑造** — 你的每一次回应（安慰/忽视/解释）都在塑造婴儿的依恋风格
- **社交涌现** — 多个幼儿在自由对话中涌现合作、冲突与策略

## 生命全景

Angel Cradle 模拟生命的三个阶段：

```
  Womb 子宫              Cradle 摇篮              World 世界
 ─────────────        ─────────────           ─────────────
  7 阶段胎儿发育   →    12 阶段婴幼儿成长   →     开放世界 (规划中)
  受精卵 → 出生         出生 → 独立个体          个体 → 社会
```

### Womb — 子宫引擎

从受精卵到出生的七阶段发育。每阶段调用一次 LLM，上一阶段输出作为下一阶段输入，母体反馈循环贯穿全程。

十个生物学子系统协同工作：孟德尔遗传、表观遗传（DNA 甲基化）、5 种关键营养素、6 类致畸因子、胎盘效率、免疫风险、4 条激素通路、胎儿生命体征、出生地理、动态环境变化。

### Cradle — 摇篮引擎

从出生到 7 岁的十二阶段成长。婴儿从「只会哭」逐步发展到「独立表达」，严格约束 LLM 输出——新生儿物理上不可能说出完整句子。

核心机制包括：出生时身份永久锁定、感知过滤（事件强度 × 感官敏感度 × 觉醒修正）、依恋模型（安全/焦虑/回避型）、父母实时对话、多婴社交会话、世界就绪毕业检查。

### World — 世界引擎（规划中）

从摇篮毕业的个体进入开放世界。

## 物种支持

通过 YAML 蓝图定义物种，当前支持：

| 物种 | 妊娠期 | 典型后代数 |
|------|--------|-----------|
| Human | 280 天 | 1 (双胞胎率 1.2%) |
| Dog | 63 天 | 4-7 |
| Cat | 65 天 | 1-12 (均值 4) |

添加新物种只需在 `backend/womb/species/` 下创建对应的 YAML 蓝图文件。

## Quick Start

### 环境要求

| 工具 | 版本 | 说明 | 检查安装 |
|------|------|------|----------|
| **Python** | >= 3.9 | 后端运行时 | `python --version` |
| **Node.js** | 18+ | 前端运行时 | `node -v` |
| **LLM API Key** | — | DeepSeek / Anthropic / 4sapi | — |

### 1. 配置环境变量

```bash
# 在 backend/ 目录下创建 .env
cd backend
```

```env
# DeepSeek (默认)
DEEPSEEK_API_KEY=your-key-here

# 或 Anthropic
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=your-key-here

# 或 4sapi (Gemini)
# LLM_PROVIDER=4sapi
# FSAPI_API_KEY=your-key-here
```

### 2. 安装依赖

```bash
# 后端
cd backend && pip install -e .

# 前端
cd frontend && npm install
```

### 3. 启动服务

```bash
# 一键启动前后端
make dev

# 或分别启动
make backend   # → http://localhost:8000
make frontend  # → http://localhost:5173

# 停止服务
make stop
```

打开浏览器 `http://localhost:5173` → 选择物种 → 调整环境 → 点击「Conceive」→ 观看实时发育 → 出生后进入摇篮养育。

## 技术栈

```
frontend/          React 19 + Vite + shadcn/ui
  ├─ Womb Tab      受孕流、蓝图预览、环境控制面板
  ├─ Cradle Tab    成长流、亲子对话、社交会话
  ├─ i18n          中英双语 + LLM 翻译回退
  └─ SSE ────→  backend/          FastAPI + uvicorn
                  ├─ womb/          子宫引擎 (10 个生物子系统)
                  ├─ cradle/        摇篮引擎 (阶段/事件/身份/社交)
                  ├─ llm.py         LLM 抽象层 (DeepSeek/Anthropic/4sapi)
                  ├─ births/        出生注册表 (JSON 持久化)
                  └─ nursery/       摇篮状态 (state + events + interactions)
```

全程通过 **SSE (Server-Sent Events)** 实时流式传输发育/成长事件到前端。

## License

MIT
