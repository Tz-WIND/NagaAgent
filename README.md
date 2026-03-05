<div align="center">

# NagaAgent

**你的超级AI秘书**

流式工具调用 · 知识图谱记忆 · Live2D 虚拟形象 · 语音交互 · 娜迦网络社区

[简体中文](README3.md) | [English](README_en.md)

![NagaAgent](https://img.shields.io/badge/NagaAgent-5.1.0-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-green?style=for-the-badge)
![License](https://img.shields.io/badge/License-AGPL%203.0%20%7C%20Proprietary-yellow?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python)

[![Stars](https://img.shields.io/github/stars/Xxiii8322766509/NagaAgent?style=social)](https://github.com/Xxiii8322766509/NagaAgent)
[![Forks](https://img.shields.io/github/forks/Xxiii8322766509/NagaAgent?style=social)](https://github.com/Xxiii8322766509/NagaAgent)
[![Issues](https://img.shields.io/github/issues/Xxiii8322766509/NagaAgent)](https://github.com/Xxiii8322766509/NagaAgent/issues)

**[QQ 机器人联动：Undefined QQbot](https://github.com/69gg/Undefined/)**

</div>

---

**双许可证** · 开源采用 [AGPL-3.0](LICENSE)，闭源采用 [专属许可](LICENSE-CLOSED-SOURCE)（需书面授权）。
商业合作：contact@nagaagent.com / bilibili【柏斯阔落】

---

## 更新日志

| 日期 | 版本 | 内容 |
|------|------|------|
| 🎆 2026-02-26 | 5.1.0 | 娜迦网络社区论坛上线；设置三合一重构；旅行模式；积分配额页；枢机集市与主面板更新 |
| ⚡ 2026-02-25 | 5.1.0 | TTS 全链路修复（CORS / asyncio）；build.py 跨平台构建；上下文压缩持久化；角色系统更新；提示词注入架构重构 |
| 🎵 2026-02-24 | — | Neo4j 连接超时修复；统一 BGM 播放器；音律坊歌单编辑；MCP 管理 UI；悬浮球透明窗口 + 悬停亮度 |
| 🏗️ 2026-02-23 | — | 跨平台构建完善；版本号统一 pyproject.toml 管理；提示词/截图/视觉优化；角色文件打包迁移 |
| 💕 2026-02-22 | — | 积分好感度系统（签到 / 好感度 / 积分）；悬浮球阴影与拖拽修复；登录自动恢复；OpenClaw hooks 修复 |
| 🎶 2026-02-21 | — | 音律坊图标更新；MCP Agents 更新；悬浮球小按钮 |
| 🗜️ 2026-02-20 | — | 上下文压缩三级重构（`<compress>` 标签 / 跨会话继承）；MCP 管理 UI；悬浮球透明窗口；音律坊功能修正 |
| 🔄 2026-02-19 | — | SSE 去除 base64 直接 JSON 传输；移除冗余后台意图分析器；config_manager 自动检测编码 |
| 🔧 2026-02-17 | — | 悬浮球序列帧路径改为相对路径，修复打包后头像不显示 |
| 🚀 2026-02-16 | 5.0.0 | NagaModel 网关统一接入；DeepSeek 推理链实时展示；记忆云海 UI 自适应修复 |
| 🧠 2026-02-15 | — | 统一附加知识块 + 消除历史污染；LLM 流式重试；七天自动登录；开机自启动 |
| 🌊 2026-02-14 | — | NagaMemory 云端远程记忆；意识海 3D 重写；启动粒子动画；版本更新检查弹窗；用户使用协议 |
| ✨ 2026-02-13 | — | 悬浮球 4 状态模式；截屏多模态视觉切换；技能工坊重构；Live2D 表情通道独立 |
| 🎨 2026-02-12 | — | NagaCAS 认证；Live2D 4 通道正交动画架构；Agentic Tool Loop；明日方舟风格启动界面 |
| 📦 2026-02-11 | — | 嵌入式 OpenClaw 打包；启动自动从模板生成配置文件 |
| 🛠️ 2026-02-10 | — | 后端打包优化；技能工坊 MCP 状态修复；去除冗余 Agent/MCP 仅保留 OpenClaw |
| 🌱 2026-02-09 | — | 前端重构；Live2D 禁用眼睛追踪；OpenClaw 更名为 AgentServer |

---

## 目录

1. [快速开始](#快速开始)
2. [功能导览（主面板）](#功能导览主面板)
3. [对话](#1-对话--messagerview)
4. [记忆云海](#2-记忆云海--mindview)
5. [技能工坊](#3-技能工坊--skillview)
6. [娜迦网络](#4-娜迦网络--论坛社区)
7. [枢机集市](#5-枢机集市--marketview)
8. [终端设置](#6-终端设置--configview)
9. [音律坊](#7-音律坊--musicview)
10. [悬浮球](#8-悬浮球--floatingview)
11. [全局功能](#全局功能)
12. [后端架构](#后端架构)
13. [可选配置](#可选配置)
14. [端口一览](#端口一览)
15. [故障排除](#故障排除)

---

## 快速开始

### 环境要求

- Python 3.11（`>=3.11, <3.12`）
- 可选：[uv](https://github.com/astral-sh/uv) — 加速依赖安装
- 可选：Neo4j — 本地知识图谱记忆

### 安装

```bash
git clone https://github.com/Xxiii8322766509/NagaAgent.git
cd NagaAgent


#前端安装
cd frontend
npm install
cd..


#后端安装
# 方式一：setup 脚本（自动检测环境、创建虚拟环境、安装依赖）
python setup.py

# 方式二：uv
uv sync

# 方式三：手动
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
```

### 最小配置

复制 `config.json.example` 为 `config.json`，填入 LLM API 信息：

```json
{
  "api": {
    "api_key": "your-api-key",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v3.2"
  }
}
```

支持所有 OpenAI 兼容 API（DeepSeek、通义千问、OpenAI、Ollama 等）。

### 启动

```bash
cd frontend && npm run dev （配置了一键启动）
```

---

## 功能导览（主面板）

启动后进入**主面板（PanelView）**，采用 3D 视差效果（鼠标移动触发透视旋转）。
所有功能从主面板的八个入口按钮展开：

| # | 入口 | 路由 | 功能概要 |
|---|------|------|----------|
| 1 | **对话** | `/chat` | AI 对话、流式工具调用、上下文压缩 |
| 2 | **记忆云海** | `/mind` | 知识图谱 3D 可视化与 GRAG 记忆管理 |
| 3 | **技能工坊** | `/skill` | MCP 工具管理与社区 Skill 安装 |
| 4 | **娜迦网络** | `/forum` / `/forum/quota` | 社区论坛、积分好感度 |
| 5 | **枢机集市** | `/market` | 背景、音乐、角色、记忆迁移、充值 |
| 6 | **终端设置** | `/config` | 模型连接、记忆连接、音画配置（三合一） |
| 7 | **音律坊** | `/music` | BGM 播放器与歌单管理 |
| 8 | **悬浮球** | — | 进入轻量悬浮球窗口模式 |

---

## 1. 对话 · MessageView

### 流式工具调用

对话引擎通过 SSE 流式输出，同时实时送达前端显示与 TTS 分句播放。
工具调用不依赖 OpenAI Function Calling API，LLM 在文本中以 ` ```tool``` ` 代码块嵌入 JSON，**任何 OpenAI 兼容提供商均可使用**。

**单轮工具调用流程：**

```
LLM 流式输出 ──SSE──▶ 前端实时显示
       │
       ▼
parse_tool_calls_from_text()
  ├─ Phase 1: 提取 ```tool``` 代码块
  └─ Phase 2: 兜底提取裸 JSON
       │
       ▼
  按 agentType 路由
  ├─ "mcp"      → MCPManager.unified_call()
  ├─ "openclaw" → Agent Server /openclaw/send
  └─ "live2d"   → UI 动画通知
       │
       ▼
  asyncio.gather() 并行执行所有工具
       │
       ▼
  结果注入 messages，进入下一轮 LLM 调用（最多 5 轮）
```

- 文本解析：`json5` 容错解析，全角字符自动标准化
- SSE 格式：`data: {"type":"content"|"reasoning","text":"..."}\n\n`（直接 JSON，不含 base64）
- 循环上限：`max_loop_stream = 5`（可配置）

源码：[`apiserver/agentic_tool_loop.py`](apiserver/agentic_tool_loop.py)

### 上下文压缩

会话 token 超过 100k 时自动触发压缩，避免上下文溢出：

| 阶段 | 触发时机 | 行为 |
|------|----------|------|
| **启动压缩** | 会话加载时 | 历史超阈值则立即压缩前段消息 |
| **运行时压缩** | 每轮对话后 | 超限则压缩并注入 `<compress>` 标签 |
| **跨会话继承** | 新会话启动 | 读取上次摘要，滚动累积上下文 |

摘要结构（6 分区）：关键事实 / 用户偏好 / 重要决定 / 待办事项 / 背景信息 / 最近状态。
`<compress>` 标签持久化到会话文件，不计入 LLM token 统计。

### DeepSeek 推理链展示

使用 DeepSeek 时，`reasoning` 字段通过 SSE 实时推送，前端以独立样式展示思考过程。

---

## 2. 记忆云海 · MindView

### GRAG 知识图谱记忆

GRAG（Graph-RAG）从对话中自动提取五元组并存入 Neo4j，对话时自动检索作为 LLM 上下文。

**五元组结构：**`(主体, 主体类型, 谓词, 客体, 客体类型)`

**提取流程：**

1. 结构化提取（优先）：`beta.chat.completions.parse()` + Pydantic `QuintupleResponse`，`temperature=0.3`，重试 3 次
2. JSON 兜底：解析失败时提取首个 `[` 到末尾 `]` 的内容
3. 过滤规则：只保留事实（行为、关系、状态、偏好），过滤隐喻、假设、纯情感

**实体类型：** `person` / `location` / `organization` / `item` / `concept` / `time` / `event` / `activity`

**任务管理器：**
- 3 个 asyncio worker 消费 `asyncio.Queue(maxsize=100)`
- SHA-256 去重：相同文本的重复任务自动跳过
- 每小时清理超过 24h 的已完成任务

**双重存储：**
- 本地：`logs/knowledge_graph/quintuples.json`
- 云端：Neo4j 图数据库，`graph.merge()` upsert

**RAG 检索：** 关键词提取 → Cypher 查询 → 格式化为 `主体(类型) —[谓词]→ 客体(类型)` 注入上下文

**远程记忆：** 登录用户自动使用 NagaMemory 云端，退出或离线时回退本地 GRAG。

源码：[`summer_memory/`](summer_memory/)

### 意识海 3D 可视化

Canvas 2D + 手写 3D 投影（非 WebGL），球面坐标相机，透视除法 `700 / depth`。

**7 层渲染顺序：**
背景渐变 → 地面网格 → 水面平面 → 体积光（3 束光柱）→ 粒子系统（3 层 125 颗）→ 生物荧光浮游生物（10 个带拖尾）→ 知识图谱节点与边（深度排序）

**图谱映射：** `subject/object` → 节点，`predicate` → 有向边，度中心性 → 节点高度权重，上限 100 节点

**交互：** 拖拽旋转、中键平移、滚轮缩放、节点点选/拖拽、关键词搜索过滤

---

## 3. 技能工坊 · SkillView

### 内置 MCP Agent

基于 [Model Context Protocol](https://modelcontextprotocol.io/) 的可插拔工具架构，每个工具以独立 Agent 运行：

| Agent | 功能 |
|-------|------|
| `weather_time` | 天气查询 / 预报、系统时间、自动城市 / IP 检测 |
| `open_launcher` | 扫描系统已安装应用，自然语言启动程序 |
| `game_guide` | 游戏策略问答、伤害计算、配队推荐、自动截图注入 |
| `online_search` | 基于 SearXNG 的网络搜索 |
| `crawl4ai` | 基于 Crawl4AI 的网页内容提取 |
| `playwright_master` | 基于 Playwright 的浏览器自动化 |
| `vision` | 截图分析与视觉问答 |
| `mqtt_tool` | MQTT 协议 IoT 设备控制 |
| `office_doc` | docx / xlsx 内容提取 |

**注册与发现：** `mcp_registry.py` glob 扫描 `**/agent-manifest.json`，`importlib.import_module` 动态实例化。

### MCP 管理 UI

前端 `McpAddDialog.vue` 提供图形化 MCP 工具管理界面，支持在线添加 / 删除工具（无需重启）。

### 社区 Skill 安装

技能工坊支持一键安装社区发布的 Skill（Agent Browser、Brainstorming、Context7、Firecrawl Search 等）。
后端接口：`GET /openclaw/market/items`、`POST /openclaw/market/items/{id}/install`

源码：[`mcpserver/`](mcpserver/)

---

## 4. 娜迦网络 · 论坛社区

### 社区论坛

从主面板"娜迦网络"区块进入，内嵌完整社区功能：

| 视图 | 路由 | 功能 |
|------|------|------|
| `ForumListView` | `/forum` | 帖子列表、分类筛选 |
| `ForumPostView` | `/forum/post/:id` | 帖子详情浏览（当前版本为只读，不提供前端评论与“想要认识”操作） |
| `ForumMessagesView` | `/forum/messages` | 私信消息 |
| `ForumMyPostsView` | `/forum/my-posts` | 我的发帖 |
| `ForumMyRepliesView` | `/forum/my-replies` | 我的回复 |
| `ForumQuotaView` | `/forum/quota` | 积分配额与探索入口 |

源码：[`frontend/src/forum/`](frontend/src/forum/)

### 积分好感度系统

登录用户专属的游戏化互动体系：

| 维度 | 说明 |
|------|------|
| **积分 (Credits)** | 签到 / 连签奖励积累，用于兑换模型额度 |
| **好感度 (Affinity)** | 每次签到增长，反映与娜迦的关系深度 |
| **每日签到** | 用户菜单一键签到，连续签到触发额外奖励 |

相关 API（通过 API Server 代理至 Naga 门户）：`/api/checkin`、`/api/affinity`、`/api/credits`

---

## 5. 枢机集市 · MarketView

枢机集市整合了所有资源获取与管理入口，分为七个 Tab：

| Tab | 说明 |
|-----|------|
| **界面背景** | 切换应用主题背景 |
| **音之巷** | 购买 / 解锁音乐专辑（当前：沙之书） |
| **角色注册** | 绑定 / 切换 AI 角色（需登录） |
| **记忆云迁** | 云端记忆数据迁移与管理 |
| **MCP 工具** | MCP 工具图形化管理 |
| **智能体技能** | 社区 Skill 一键安装 |
| **模型充值** | Naga 门户积分充值 |

---

## 6. 终端设置 · ConfigView

设置页三合一重构，原分散配置集中在单一页面的三个 Tab：

| Tab | 内容 |
|-----|------|
| **模型连接** | LLM API Key、Base URL、模型选择 |
| **记忆连接** | Neo4j 连接参数、NagaMemory 云端配置 |
| **音画配置** | 角色档案、Live2D 模型与 SSAA、TTS 声音、聊天字号 |

### 角色卡系统

`characters/` 目录管理可切换的 AI 角色，每个角色以 JSON 配置文件描述：

```json
{
  "ai_name": "娜杰日达",
  "user_name": "用户",
  "live2d_model": "NagaTest2/NagaTest2.model3.json",
  "prompt_file": "conversation_style_prompt.txt",
  "portrait": "Naga.png",
  "bio": "由开发者柏斯阔落亲手创造的AI助手，简称娜迦。"
}
```

- 每个角色目录包含独立的对话风格提示词、Live2D 模型资源、立绘图像
- 激活角色后，AI 名称与 Live2D 模型由角色 JSON 统一管理，不可在界面手动覆盖
- 默认角色：**娜杰日达**

源码：[`characters/`](characters/)

---

## 7. 音律坊 · MusicView

独立音乐播放器，与主界面 BGM **共享同一播放实例**（统一 BGM 架构）：

- **歌单编辑**（`MusicEditView`）：管理曲目列表，保存后实时同步至全局播放器
- **播放状态同步**：播放 / 暂停图标与音频事件实时联动
- **列表循环**：当前曲目结束后自动播放下一首
- **Live2D 口型同步**：TTS 播放期间，`AdvancedLipSyncEngineV2` 以 60FPS 驱动 Live2D 嘴形

---

## 8. 悬浮球 · FloatingView

点击主面板"悬浮"按钮进入轻量悬浮球窗口模式，四种状态循环切换：

```
ball（100×100 圆球）→ compact（420×100 折叠条）→ full（420×N 展开）→ classic（正常窗口）
```

**外观与动效：**
- 序列帧眨眼动画：5 帧（睁眼 → 半闭 → 闭眼 → 半闭 → 睁眼），70ms / 帧，随机间隔触发
- 生成回复时：球体光晕脉冲特效
- 悬停时：亮度提升效果
- 透明无边框窗口，支持自由拖拽定位

**功能：**
- 悬浮状态下可直接输入对话，历史消息在 compact / full 状态下可回溯
- 截图捕获面板：选取屏幕窗口作为图像附件
- 文件上传支持
- 右键菜单通过 Electron 原生菜单实现（避免小窗口裁剪）

---

## 全局功能

### 语音交互

**TTS（语音合成）**

- 引擎：Edge-TTS，OpenAI 兼容接口 `/v1/audio/speech`
- 架构：3 线程流水线 — 分句队列 → TTS 调用（Semaphore(2) 并发）→ pygame 播放
- Live2D 口型同步：60FPS 提取 5 参数（mouth_open / mouth_form / mouth_smile / eye_brow_up / eye_wide）
- 端口清理：启动时自动检测并释放占用端口

**ASR（语音识别）**

- 本地引擎：FunASR，支持 VAD 端点检测与 WebSocket 实时流
- 三模式自动切换：`LOCAL`（FunASR）→ `END_TO_END`（Qwen Omni）→ `HYBRID`

**实时语音对话**（需 DashScope API Key）

- 基于 Qwen Omni 的全双工 WebSocket 语音交互
- 回声抑制、VAD 检测、音频分块（200ms）、会话冷却控制

```json
{
  "voice_realtime": {
    "enabled": true,
    "provider": "qwen",
    "api_key": "your-dashscope-key",
    "model": "qwen3-omni-flash-realtime"
  }
}
```

源码：[`voice/`](voice/)

---

### Live2D 虚拟形象

使用 **pixi-live2d-display** + **PixiJS WebGL** 渲染 Cubism Live2D 模型。
SSAA 超采样抗锯齿：Canvas 按 `width × ssaa` 渲染，CSS `transform: scale(1/ssaa)` 缩放。

**4 通道正交动画系统**（`live2dController.ts`）：

| 通道 | 控制内容 | 特性 |
|------|----------|------|
| **体态 (State)** | idle / thinking / talking 循环 | hermite 平滑插值，从 `naga-actions.json` 加载 |
| **动作 (Action)** | 点头 / 摇头等头部动作 | FIFO 队列，单一执行 |
| **表情 (Emotion)** | `.exp3.json` 表情文件 | Add / Multiply / Overwrite 三种混合模式，指数衰减过渡 |
| **追踪 (Tracking)** | 鼠标视线跟随 | 可配延迟启动，`tracking_hold_delay_ms` |

合并顺序：体态 → 嘴形 → 动作 → 手动覆盖 → 表情混合 → 追踪混合

---

### OpenClaw 电脑控制

对接 OpenClaw Gateway（端口 18789），通过自然语言调度 AI 编程助手执行本地任务。

- **三级回退启动：** 打包内嵌 → 全局 `openclaw` 命令 → 自动 `npm install -g openclaw`
- 支持 sessionKey hooks（2026.2.17+），可配置自定义 hooks 路径
- `POST /openclaw/send` 发送指令，最长等待 120 秒

**任务调度器（`TaskScheduler`）：**
- 任务步骤记录（目的 / 内容 / 输出 / 分析 / 成功与否）
- 自动提取"关键发现"标记
- 内存压缩：步骤数超阈值时调用 LLM 生成 `CompressedMemory`（key_findings / failed_attempts / current_status / next_steps）
- `schedule_parallel_execution()` 通过 `asyncio.gather()` 并行执行任务列表

源码：[`agentserver/`](agentserver/)

---

### 启动动画

| 阶段 | 内容 |
|------|------|
| **标题阶段** | 黑色遮罩 + 40 颗金色上升粒子 + 标题图片 2.4s CSS keyframe；标题出现时自动播放唤醒语音 |
| **进度阶段** | Neural Network 粒子背景 + Live2D 透出框 + 金色进度条（`requestAnimationFrame` 插值，最低速度 0.5 兜底） |
| **停滞检测** | 3 秒无进度变化显示重启提示；进度 25% 后每秒轮询后端 `/health` |
| **唤醒** | 进度 100% 后显示"点击唤醒"脉冲提示 |

---

## 后端架构

NagaAgent 由四个独立微服务组成，`main.py` 统一编排启动：

```
┌─────────────────────────────────────────────────────────┐
│                   Electron / PyQt5 前端                   │
│  Vue 3 + Vite + UnoCSS + PrimeVue + pixi-live2d-display │
│                                                         │
│  PanelView · MessageView · MindView · SkillView         │
│  MarketView · ConfigView · MusicView · FloatingView     │
│  ForumListView · ForumPostView · ForumQuotaView …       │
└──────────┬─────────────┬──────────────┬─────────────────┘
           │             │              │
   ┌───────▼──────┐ ┌────▼────┐  ┌─────▼──────┐
   │  API Server  │ │  Agent  │  │   Voice    │
   │   :8000      │ │  Server │  │  Service   │
   │              │ │  :8001  │  │   :5048    │
   │ 对话 / SSE   │ │         │  │            │
   │ 工具调用     │ │ 任务调度│  │ TTS / ASR  │
   │ 上下文压缩   │ │ OpenClaw│  │ 实时语音   │
   │ 文档上传     │ │         │  │            │
   │ 认证代理     │ └────┬────┘  └────────────┘
   │ 记忆 API     │      │
   │ Skill 市场   │  ┌───▼──────────┐
   │ 配置管理     │  │  OpenClaw    │
   └──────┬───────┘  │  Gateway    │
          │          │  :18789     │
   ┌──────▼──────┐   └─────────────┘
   │ MCP Server  │
   │   :8003     │
   │ 工具注册    │
   │ Agent 发现  │
   │ 并行调度    │
   └──────┬──────┘
          │
  ┌───────┴───────────────────────┐
  │      MCP Agents（可插拔）      │
  │ 天气 | 搜索 | 抓取 | 视觉     │
  │ 启动器 | 攻略 | 文档 | MQTT   │
  └───────────────────────────────┘
          │
   ┌──────▼──────┐
   │    Neo4j    │
   │   :7687     │
   │  知识图谱   │
   └─────────────┘
```

### 目录结构

```
NagaAgent/
├── main.py                   # 统一入口，编排所有服务
├── build.py                  # 跨平台构建脚本
├── config.json               # 运行时配置（从 config.json.example 复制）
├── pyproject.toml            # 版本 5.1.0，项目元数据与依赖
│
├── apiserver/                # API Server（:8000）
│   ├── api_server.py         #   FastAPI 主应用
│   ├── agentic_tool_loop.py  #   多轮工具调用循环
│   ├── llm_service.py        #   LiteLLM 统一 LLM 调用
│   └── streaming_tool_extractor.py  # 流式分句 + TTS 分发
│
├── agentserver/              # Agent Server（:8001）
│   ├── agent_server.py
│   └── task_scheduler.py     #   任务编排 + 压缩记忆
│
├── mcpserver/                # MCP Server（:8003）
│   ├── mcp_server.py
│   ├── mcp_registry.py       #   manifest 扫描 + 动态注册
│   ├── mcp_manager.py        #   unified_call() 路由
│   ├── agent_weather_time/
│   ├── agent_open_launcher/
│   ├── agent_game_guide/
│   ├── agent_online_search/
│   ├── agent_crawl4ai/
│   ├── agent_playwright_master/
│   ├── agent_vision/
│   ├── agent_mqtt_tool/
│   └── agent_office_doc/
│
├── summer_memory/            # GRAG 知识图谱记忆
│   ├── quintuple_extractor.py
│   ├── quintuple_graph.py
│   ├── quintuple_rag_query.py
│   ├── task_manager.py
│   ├── memory_manager.py
│   └── memory_client.py      #   NagaMemory 远程客户端
│
├── voice/                    # 语音服务（:5048）
│   ├── output/               #   TTS + 口型同步
│   └── input/                #   ASR + 实时语音
│
├── characters/               # 角色配置目录
│   └── 娜杰日达/             #   prompt / Live2D 模型 / 立绘
│
├── frontend/                 # Electron + Vue 3 前端
│   ├── electron/             #   主进程
│   │   └── modules/          #   backend / hotkeys / menu / tray / updater / window
│   └── src/
│       ├── views/            #   所有页面视图
│       ├── forum/            #   论坛模块
│       ├── components/       #   通用组件
│       ├── composables/      #   useAuth / useBackground / useAudio …
│       └── utils/            #   live2dController / session / config
│
├── system/                   # 配置加载、环境检测、系统提示词
├── guide_engine/             # 游戏攻略引擎
└── logs/                     # 运行日志、知识图谱文件
```

---

## 可选配置

<details>
<summary><b>知识图谱记忆（Neo4j）</b></summary>

安装 Neo4j（[Docker](https://hub.docker.com/_/neo4j) 或 [Neo4j Desktop](https://neo4j.com/download/)），配置 `config.json`：

```json
{
  "grag": {
    "enabled": true,
    "neo4j_uri": "neo4j://127.0.0.1:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "your-password"
  }
}
```

不配置 Neo4j 时，GRAG 仅使用本地 JSON 文件存储，功能不受影响。
</details>

<details>
<summary><b>语音交互（TTS / ASR）</b></summary>

```json
{
  "system": { "voice_enabled": true },
  "tts": {
    "port": 5048,
    "default_voice": "zh-CN-XiaoxiaoNeural"
  }
}
```

实时全双工语音对话（需通义千问 DashScope API Key）：

```json
{
  "voice_realtime": {
    "enabled": true,
    "provider": "qwen",
    "api_key": "your-dashscope-key",
    "model": "qwen3-omni-flash-realtime"
  }
}
```
</details>

<details>
<summary><b>Live2D 虚拟形象（自定义模型）</b></summary>

```json
{
  "web_live2d": {
    "ssaa": 2,
    "model": {
      "source": "./models/your-model/model.model3.json",
      "x": 0.5,
      "y": 1.3,
      "size": 6800
    },
    "face_y_ratio": 0.13,
    "tracking_hold_delay_ms": 100
  }
}
```

启用角色卡后，`ai_name` 与 `model.source` 由角色 JSON 自动覆盖，无需手动修改。
</details>

<details>
<summary><b>MQTT 物联网控制</b></summary>

```json
{
  "mqtt": {
    "enabled": true,
    "broker": "mqtt-broker-address",
    "port": 1883,
    "topic": "naga/agent/topic",
    "client_id": "naga-agent-client"
  }
}
```
</details>

---

## 端口一览

| 服务 | 端口 | 说明 |
|------|------|------|
| API Server | 8000 | 主接口：对话、配置、认证、Skill 市场 |
| Agent Server | 8001 | 任务调度、OpenClaw |
| MCP Server | 8003 | MCP 工具注册与调度 |
| Voice Service | 5048 | TTS / ASR |
| Neo4j | 7687 | 知识图谱（可选） |
| OpenClaw Gateway | 18789 | AI 电脑控制（可选） |

---

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| Python 版本报错 | 必须使用 Python 3.11；推荐用 uv 自动管理版本 |
| 端口被占用 | 检查 8000、8001、8003、5048 是否可用 |
| Neo4j 连接超时 / 挂起 | 已在 2.24 修复；确认 Neo4j 服务已启动 |
| TTS 无声音 / CORS 报错 | 已在 2.25 修复；确认 `voice_enabled: true` |
| 启动卡在进度条 | 检查 API Key 是否正确；等待 3 秒后出现重启提示 |
| 悬浮球头像不显示 | 已在 2.17 修复序列帧路径；确认使用最新打包版本 |
| config.json 乱码 | 已在 2.19 修复：config_manager 自动检测文件编码 |
| OpenClaw 启动失败 | 已在 2.24 修复全局模式缺少配置文件的问题 |

```bash
python main.py --check-env --force-check  # 完整环境诊断
python main.py --quick-check              # 快速检查
python update.py                          # 自动 git pull + 依赖同步
```

---

## 贡献

欢迎提交 Issue 和 Pull Request。如有问题，可加入 QQ 频道 **nagaagent1**。

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=RTGS2017/NagaAgent&type=date&legend=top-left)](https://www.star-history.com/#RTGS2017/NagaAgent&type=date&legend=top-left)
