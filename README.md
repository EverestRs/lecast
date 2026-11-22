# 课映 Lecast：一键将 Markdown 课件变成有声教学视频

上传 Markdown 课件，通过 AI 自动完成分章、幻灯片生成、讲解稿撰写、语音合成，最终导出为 MP4 教学视频。

## 快速开始

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
python run.py            # 浏览器打开 http://127.0.0.1:8000/taskList
```

前置条件：Python 3.10+、PATH 中可直接调用的 FFmpeg、一个 OpenAI 兼容的对话模型 API Key（默认阶跃星辰）与一个小米 MiMo TTS Key。密钥可在任务列表页「配置 SK」中填写，也可用服务端环境变量注入。完整步骤见[安装与启动](#安装与启动)。

---

## 功能特性

### 6 步自动化流水线

| 步骤 | 功能 | 说明 |
|------|------|------|
| 1 | **课件上传** | 上传 `.md` 格式 Markdown 文档，创建转换任务 |
| 2 | **智能分章** | 调用阶跃星辰大模型分析文档内容，自动划分逻辑章节 |
| 3 | **生成幻灯片** | 基于每章内容，由 AI 生成适配 1920×1080 大屏的 HTML 页面 |
| 4 | **生成讲解稿** | 为每章生成口语化、自然流畅的语音讲解脚本 |
| 5 | **语音合成 TTS** | 将讲解稿通过小米 MiMo TTS API 合成为 WAV 音频 |
| 6 | **导出视频** | 将 HTML 截图 + 音频合成为最终 MP4 教学视频 |

### 辅助功能

- **任务管理** — 任务列表分页展示、按名称搜索、新建/删除任务，状态徽章列一目了然
- **内容编辑** — 章节标题/内容、幻灯片 HTML、讲解稿均支持手动编辑和单条重生成
- **步骤校验** — 步骤间自动校验前置条件，未完成步骤无法跳过，支持点击步骤条跳转
- **进度恢复** — 刷新页面后自动恢复到上次未完成的步骤
- **PPTX 导出** — 将幻灯片截图导出为 PowerPoint 文件
- **音频播放** — 在浏览器中在线试听每条 TTS 音频
- **视频下载** — 合成完成后在线预览并下载 MP4
- **Toast 通知** — 操作结果以非阻塞式 Toast 提示，替代原生 alert
- **移动端适配** — 小屏设备自动切换为侧边栏折叠 + 步骤条滚动布局

---

## 技术架构

| 组件 | 技术选型 |
|------|----------|
| 后端框架 | FastAPI |
| 数据库 | SQLite（SQLAlchemy ORM） |
| 前端 | Jinja2 模板 + Bootstrap 5（纯 Python，无需 Node.js） |
| AI 对话 | 阶跃星辰 StepFun API（OpenAI 兼容模式，`step-3.7-flash`） |
| TTS 语音 | 小米 MiMo TTS API（OpenAI 兼容模式，`mimo-v2.5-tts`） |
| 视频合成 | Playwright（HTML 截图）+ FFmpeg（音频/视频合成） |
| 幻灯片导出 | python-pptx |

---

## 目录结构

```
lecast/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置（数据库路径、转储目录）
│   ├── database.py          # SQLite 引擎与会话
│   ├── models.py            # ORM 模型（Task/Section/Slide/Script/Tts）
│   ├── schemas.py           # Pydantic 请求/响应模型
│   ├── templating.py        # Jinja2 模板引擎
│   ├── services/
│   │   ├── llm.py           # 对话模型 Chat API（阶跃星辰，OpenAI 兼容）
│   │   ├── tts_api.py       # 小米 MiMo TTS API
│   │   └── video.py         # dump + 视频合成 + PPTX 导出
│   ├── routers/
│   │   ├── task.py          # 任务 CRUD + 状态同步 + dump + 导出/下载视频/PPTX
│   │   ├── section.py       # 分章 + 编辑/重生成
│   │   ├── slide.py         # 生成幻灯片 + 编辑/重生成
│   │   ├── script.py        # 生成讲解稿 + 编辑/重生成
│   │   ├── tts.py           # TTS 合成 + 播放/重生成
│   │   └── pages.py         # 页面路由
│   ├── templates/           # Jinja2 模板文件
│   ├── static/              # CSS + JS 静态资源
│   │   ├── css/style.css
│   │   ├── js/common.js           # Toast 通知等全局工具
│   │   ├── js/task_list.js        # 任务列表页
│   │   ├── js/task_create.js      # 6 步向导核心（导航 + Step 1 + 工具函数）
│   │   └── js/task_create_steps.js# 6 步向导步骤 2-6（分章/幻灯片/讲解稿/音频/导出）
├── scripts/                 # 视频处理 Python 脚本
│   ├── record.py            # HTML → 截图 → MP4
│   ├── compose.py           # 拼接最终视频
│   ├── screenshot_slides.py # HTML → PNG 截图
│   ├── make_pptx.py         # PNG → PPTX
│   └── utils.py             # 工具函数
├── tests/                   # pytest 用例（默认 mock 网络边界）+ 真实联调脚本
├── data/                    # SQLite 数据库 + 产物转储（首次启动自动创建，已 gitignore）
├── logs/                    # 运行日志 app.log（10MB 轮转 ×5，已 gitignore）
├── docs/                    # 实施方案与测试方案文档（见下方文档索引）
├── LICENSE                  # AGPL-3.0 许可证全文
├── requirements.txt         # 运行时依赖（已锁定版本）
├── requirements-dev.txt     # 开发/测试依赖（含 pytest）
├── run.py                   # 启动脚本
└── README.md
```

> `data/`、`logs/`、`__pycache__/`、`.env` 等已在 `.gitignore` 中排除，克隆后首次启动会自动重建。

---

## 文档索引

`docs/` 下按主题归档：

| 文档 | 内容 |
|------|------|
| [测试方案与测试用例](docs/测试方案与测试用例.md) | 分层测试策略（L0–L3）、用例清单、环境准备与执行步骤 |
| [前端缺陷修复实施方案](docs/前端缺陷修复实施方案.md) | 四阶段前端问题修复记录（已全部完成） |
| [系统缺陷修复实施方案](docs/系统缺陷修复实施方案.md) | 六阶段后端 / 脚本 / 架构 / 工程化修复记录 |
| [对话生成切换StepFun实施方案](docs/对话生成切换StepFun实施方案.md) | 对话模型供应商切换与验证清单 |
| [语音合成切换MiMo-TTS实施方案](docs/语音合成切换MiMo-TTS实施方案.md) | TTS 供应商切换（方案 A）与验证清单 |

---

## 环境要求

- Python 3.10+
- FFmpeg（已安装并添加到系统环境变量，视频合成必需）
- 阶跃星辰 API Key（对话生成）与小米 MiMo API Key（语音合成），可由用户浏览器配置或服务端统一配置，见下

### 环境变量（可选）

| 变量 | 说明 |
|------|------|
| `APP_ACCESS_TOKEN` | 站点访问口令。设置后页面需先在 `/login` 输入口令（HttpOnly Cookie，有效期 30 天），`/api` 未登录直接返回 401 JSON；`/static` 与 `/healthz` 免鉴权。不设置则无门禁 |
| `STEPFUN_API_KEY` | 服务端默认对话生成密钥（阶跃星辰）。设置后前端 SK 弹窗可留空，请求未带 `X-API-Key` 时自动回退使用 |
| `MIMO_API_KEY` | 服务端默认小米 MiMo 密钥（TTS 语音合成）。请求未带 `X-TTS-Key` 时自动回退使用 |
| `LLM_CHAT_URL` / `LLM_MODEL` | 对话生成端点与模型，默认阶跃星辰 `https://api.stepfun.com/v1/chat/completions` / `step-3.7-flash`；可指向任意 OpenAI 兼容供应商 |
| `LLM_REASONING_EFFORT` | 对话模型推理强度 low/medium/high，默认 `low`（防思维链挤占输出预算）；置空则不下发该参数 |
| `LLM_JSON_MODE` | 置为 `1` 后分章接口启用 `response_format=json_object`（StepFun 支持未确认，默认关） |
| `TTS_MODEL` / `TTS_VOICE` | TTS 模型与默认音色，默认 `mimo-v2.5-tts` / `冰糖` |
| `TTS_VOICE_CHOICES` | Step5 音色下拉清单，逗号分隔，默认 `冰糖,茉莉,苏打,白桦` |
| `PAGE_SIZE` / `UPLOAD_MAX_MB` | 任务列表分页大小（10）与上传上限 MB（5） |
| `HTTP_TIMEOUT` / `SUBPROCESS_MIN_TIMEOUT` / `RECORD_TIMEOUT_PER_PAGE` 等 | LLM 请求超时 600s、子进程超时下限 300s、录制每页预算 90s |
| `FFMPEG_PATH` | FFmpeg 可执行文件路径。默认从 `PATH` 查找；未加入系统环境变量时用它显式指定，如 `C:\ffmpeg\bin\ffmpeg.exe` |
| `HOST` / `PORT` / `RELOAD` | 仅 `run.py` 启动脚本生效；默认 `127.0.0.1:8000`、关闭 reload |

### 运行测试

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

默认用 mock 隔离网络边界（`llm.chat`、`tts_api.synthesize`），无需真实密钥即可跑全量。需要打真实接口时手工运行 `python tests/test_stepfun_live.py <STEP_API_KEY>`。

---

## 安装与启动

### 1. 安装 Python 依赖

```bash
python -m pip install -r requirements.txt
```

需要运行测试时改用 `python -m pip install -r requirements-dev.txt`（在运行时依赖基础上额外包含 pytest）。

### 2. 安装 Playwright 浏览器

```bash
python -m playwright install chromium
```

### 3. 启动服务

开发环境（本机访问）：

```bash
python run.py
```

生产/局域网部署（关闭热重载，按需绑定地址并配置口令）：

```bash
# Windows PowerShell 示例
$env:HOST="0.0.0.0"; $env:APP_ACCESS_TOKEN="你的口令"; $env:STEPFUN_API_KEY="sk-xxx"; $env:MIMO_API_KEY="你的MiMo密钥"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> 💡 使用 conda 管理环境时，先 `conda create -n <环境名> python=3.10` 创建、`conda activate <环境名>` 激活，再执行上述命令即可；也可用 `conda run -n <环境名> python run.py` 免激活运行。

### 4. 访问应用

打开浏览器访问 `http://127.0.0.1:8000/taskList`（根路径 `/` 会自动跳转到该页）。

### 5. 健康检查与接口文档

- **存活探针**：`GET /healthz` 正常返回 `{"status":"ok"}`；数据库不可用时返回 500 与 `{"status":"db_error"}`。该端点**免鉴权**，可直接对接容器或负载均衡的健康检查。
- **接口文档**：项目共注册 35 个 REST API 端点（另有 6 个页面路由），启动后访问 `/docs`（Swagger UI）、`/redoc` 或 `/openapi.json` 查看；设置 `APP_ACCESS_TOKEN` 后这些路径同样需要口令。

---

## 使用说明

### 首次使用

1. 在任务列表页点击 **配置 SK**，分别输入对话生成（阶跃星辰）与语音合成（小米 MiMo）的 API Key（密文显示，存储在浏览器 localStorage）
2. 点击 **新建任务** 进入 6 步向导

> ⚠️ **安全提示**：浏览器填写的密钥以明文存放于 `localStorage`，仅适用于本机或受信内网。若按上文「生产/局域网部署」对外暴露服务，请务必设置 `APP_ACCESS_TOKEN`，并改用服务端环境变量 `STEPFUN_API_KEY` / `MIMO_API_KEY` 注入密钥，不要在公网环境下通过页面填写。

### 操作流程

| 步骤 | 操作 |
|------|------|
| 选择课件 | 上传 `.md` 文件，填写任务名称 |
| 生成章节 | 点击按钮自动划分，可编辑/重生成单章 |
| 生成幻灯片 | 生成 HTML 幻灯片，轮播预览，可编辑/重生成，导出 PPTX |
| 生成讲解稿 | 生成口语化讲解稿，可编辑/重生成 |
| 生成音频 | 合成 TTS 语音，可在线播放/重生成 |
| 导出视频 | 一键导出最终 MP4 视频，支持在线预览与下载 |

> 💡 步骤条顶部显示当前进度（第 X / 6 步）；点击已完成的步骤可直接跳转；任务状态（已上传/已分章/已生成幻灯片/已生成讲解稿/已合成音频/已完成）会持续跟踪并展示在任务列表中。

---

## 已知限制

| 限制 | 说明 |
|------|------|
| **分辨率固定 1920×1080** | `scripts/*.py` 暴露了 `--width` / `--height`，但服务层未透传，全链路按 16:9 1080p 截图与合成。改分辨率需同时调整 `app/services/video.py` 与分章、幻灯片提示词 |
| **单进程作业模型** | 长任务跑在进程内 daemon 线程（`app/jobs.py`），状态仅存内存。必须以单 worker 启动，`uvicorn --workers N` 会导致作业状态不共享、进度查询为空 |
| **SQLite 单机** | 无并发写保护，多人同时操作同一任务可能遇到锁等待；数据不跨机器共享，不支持多实例部署 |
| **导出耗时较长** | 每章需经历 LLM 生成 → Chromium 渲染截图 → FFmpeg 合成。13 章的课件从分章到导出最终 MP4 实测约 45 分钟，耗时随章节数近似线性增长 |
| **TTS 串行合成** | 逐条调用 MiMo 接口，无并发。单条失败会落 `failed` 占位以保住 `speech_N` 序号连续，不中断整体流程，导出前需重生成 |
| **依赖无头 Chromium** | 截图依赖 Playwright 下载的 Chromium（首次约 150MB）；Linux 服务器无桌面环境时还需执行 `playwright install-deps` |

---

## 常见问题

**Q: 视频导出失败怎么办？**
A: 确保 FFmpeg 已安装且可在命令行中直接调用；检查 `data/` 目录下是否有对应 taskId 的临时文件。

**Q: AI 生成失败怎么办？**
A: 检查对应服务的 API Key 是否正确、是否有效、是否已过期。对话生成（阶跃星辰）与语音合成（小米 MiMo）的密钥相互独立，需分别配置。

**Q: 端口被占用？**
A: 修改 `uvicorn` 命令中的 `--port` 参数，如 `--port 8001`。

**Q: 出错了去哪里看日志？**
A: `logs/app.log`（单文件 10MB 轮转，保留 5 份）。服务端异常会记录完整堆栈，接口返回的 `message` 通常只是概述。

**Q: 数据存在哪里？**
A: 元数据在 `data/app.db`（SQLite，首次启动自动建表），产物按任务落盘在 `data/{taskId}/`：

| 路径 | 内容 |
|------|------|
| `audios/` | MiMo TTS 合成的 WAV 音频（`speech_*.wav` / `tts_*.wav`） |
| `screenshots/` | 幻灯片 HTML 经 Playwright 渲染的 PNG 截图 |
| `videos/` | 每页截图与音频合成的分页 MP4 |
| `final.mp4` | 全片拼接后的最终视频 |

`data/`、`logs/` 均在 `.gitignore` 中，不会进入版本库；删除任务时对应目录会一并清理。

---

## 许可证与商业授权

本项目以 [GNU Affero General Public License v3.0](LICENSE) 发布。

**你可以**：自由使用、修改、分发本项目，包括用于商业目的。

**你需要**：分发原始或修改版本时保留版权声明与许可证副本；若将修改版作为网络服务提供给他人使用，须依据 AGPL-3.0 第 13 条「Remote Network Interaction」向使用者提供完整源代码。

**商业授权**：如希望在闭源产品中集成本项目，或采用与 AGPL-3.0 不兼容的方式使用，可联系另行获取商业许可。

**商标**：许可证仅授予著作权层面的权利，不授予商标权。「课映」名称与标识的使用需另行获得许可。

**免责**：本软件按「现状」提供，不附带任何明示或默示担保，包括但不限于适销性与特定用途适用性担保。

---

Copyright (C) 2026 课映团队