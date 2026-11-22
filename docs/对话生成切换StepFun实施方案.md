# 对话生成切换阶跃星辰 Step 3.7 Flash 实施方案

> 更新时间：2026-08-26
> 目标：将 v2 系统对话生成（分章 / 幻灯片 HTML / 讲解稿）由通义千问 `qwen-plus` 切换为阶跃星辰 `step-3.7-flash`，采用**配置化**改造 —— URL / 模型 / 密钥全部环境变量化。
> 验证方式：按需求以**独立 `.py` 测试脚本**实测真实调用效果（见第六节），并保留 pytest 套件做回归。

---

## 一、可行性结论

**可以替换。** StepFun Chat Completions 是标准 OpenAI 兼容协议，与现有 `app/services/qwen.py` 的请求构造（`model/messages/max_tokens/response_format`）和响应解析（`choices[0].message.content`）完全同构，核心调用逻辑零改动；调用方共 6 处（section 分章/重生、slide 生成/重生、script 生成/重生），全部经 `chat()` 单一入口，参数签名不变。

## 二、Step 3.7 Flash 接口要点

来源：[模型概览](https://platform.stepfun.com/docs/zh/guides/models/step-3.7-flash) 与 [快速上手](https://platform.stepfun.com/docs/zh/guides/models/step-3.7-flash-quickstart)

| 项目 | 内容 |
|---|---|
| 端点 | `POST https://api.stepfun.com/v1/chat/completions`（OpenAI 协议兼容，支持流式/工具调用） |
| 认证 | `Authorization: Bearer $STEP_API_KEY`（与现有实现同构） |
| 模型名 | `step-3.7-flash` |
| 上下文 | 256K tokens（稀疏 MoE，198B 总参 / 11B 激活） |
| 特有参数 | `reasoning_effort`: `low` / `medium`(默认) / `high` 三档推理强度 |
| 定价 | 输入 1.35 元/M tokens（缓存命中 0.27）、输出 8.1 元/M tokens |
| 多模态 | 原生图片/视频理解（本项目暂用不到，留作后续扩展空间） |
| 密钥获取 | [开放平台接口密钥页](https://platform.stepfun.com/interface-key) |

### 调用示例（官方）

```bash
curl https://api.stepfun.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $STEPFUN_API_KEY" \
  -d '{
    "model": "step-3.7-flash",
    "messages": [{"role": "user", "content": "..."}],
    "reasoning_effort": "medium",
    "max_tokens": 1024
  }'
```

## 三、与现有实现差异对照及风险

### 3.1 差异对照

| 维度 | 现状（通义千问 qwen-plus） | Step 3.7 Flash | 处理方式 |
|---|---|---|---|
| 端点 | dashscope compatible-mode | `api.stepfun.com/v1/chat/completions` | 换配置默认值 |
| 模型名 | `qwen-plus` | `step-3.7-flash` | 换配置默认值 |
| 密钥回退 | `DASHSCOPE_API_KEY` | 新增 `STEPFUN_API_KEY` | 配置项新增，旧项删除 |
| 推理模型 | 否 | 是（三档 reasoning_effort） | 显式下发低档位（见 3.2） |
| JSON 强制模式 | 支持 `response_format` | 文档未确认 | 保持关闭（现状即默认关） |

### 3.2 关键风险：推理模型的输出预算 ⚠️

Step 3.7 Flash 是**推理模型**，与 qwen-plus 最大区别：

1. **思维链挤占 `max_tokens` 预算**：`max_tokens` 同时覆盖推理过程与最终答案。现有配置分章/讲解稿 4096、幻灯片 HTML 8192 —— 若用默认 `medium` 档，复杂幻灯片可能因思维链过长触发截断（`finish_reason=length`），产出残缺 JSON/HTML 导致解析失败。
   **对策**：显式下发 `reasoning_effort="low"`。本项目三类任务（分章 JSON、幻灯片 HTML、讲解稿）均为结构化生成，属 low 档适用场景（"信息抽取、改写"）；同时保留环境变量可调档位。
2. **`response_format=json_object` 支持未确认**：现有 `QWEN_JSON_MODE` 开关本就默认关，迁移后保持关，依赖现有 `clean_json_response` 容错清洗已足够。
3. **`temperature=0.3` 参数兼容性待实测**：文档未明确推理模型是否接受该参数，保留下发，若实测报 400 则移除。

---

## 四、实施方案（配置化改造）

设计原则：URL / 模型名 / 密钥全部环境变量化。今后切换任何 OpenAI 兼容供应商（DeepSeek / Kimi 等）只需改 env，不动代码；如需临时切回千问同理。

### 改动清单（7 个文件）

#### 1) `app/config.py` — 对话服务配置区重写

```python
# ── AI 服务 ──
# 对话生成（OpenAI 兼容供应商，当前为阶跃星辰 StepFun）
LLM_CHAT_URL = os.environ.get("LLM_CHAT_URL", "https://api.stepfun.com/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "step-3.7-flash")
DEFAULT_STEP_KEY = (os.environ.get("STEPFUN_API_KEY") or "").strip()
# 推理强度 low/medium/high：结构化生成用 low 防止思维链挤占输出预算；留空则不下发
LLM_REASONING_EFFORT = (os.environ.get("LLM_REASONING_EFFORT") or "low").strip()
# 分章接口 JSON 输出模式开关（StepFun 对 response_format 支持未确认，实测后再开启）
LLM_JSON_MODE = (os.environ.get("LLM_JSON_MODE") or "").lower() in ("1", "true", "yes")

TTS_MODEL = os.environ.get("TTS_MODEL", "mimo-v2.5-tts")      # MiMo 部分不变
...
```

删除项：`QWEN_MODEL`、`QWEN_JSON_MODE`、`DEFAULT_DASHSCOPE_KEY`。

#### 2) `app/services/qwen.py` → 重命名为 **`app/services/llm.py`**

模块名 `qwen` 在多供应商架构下已失真，重命名保持语义准确：

```python
"""对话生成 LLM 接口封装（OpenAI 兼容协议，当前接入阶跃星辰 StepFun）"""

from app.config import DEFAULT_STEP_KEY, LLM_CHAT_URL, LLM_MODEL,
                        LLM_REASONING_EFFORT, HTTP_TIMEOUT_SECONDS

def _resolve_key(api_key): ...  # 空则回退 DEFAULT_STEP_KEY

def chat(prompt, api_key, model=LLM_MODEL, max_tokens=None, json_mode=None):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if LLM_REASONING_EFFORT:
        payload["reasoning_effort"] = LLM_REASONING_EFFORT
    # json_mode / response_format 逻辑保持原样（默认不下发）
    ...

def clean_json_response(...)   # 原样迁移，供应商无关
def parse_json_str(...)        # 原样迁移
def clean_html_output(...)     # 原样迁移
```

错误文案"通义千问 API"→"对话模型 API"。原文件删除。

#### 3) 路由层 import 更新（3 个文件，纯机械替换）

| 文件 | 原 import | 改为 |
|---|---|---|
| `routers/section.py` | `from app.services.qwen import chat, clean_json_response, parse_json_str` | `from app.services.llm import ...` |
| `routers/slide.py` | `from app.services.qwen import chat, clean_html_output` | `from app.services.llm import ...` |
| `routers/script.py` | `from app.services.qwen import chat` | `from app.services.llm import ...` |

六个 `chat()` 调用点参数签名不变，零修改。

#### 4) `templates/partials/sk_modal.html` — 标签文案

- "对话生成 API Key<span>（通义千问）</span>" → "对话生成 API Key<span>（阶跃星辰）</span>"
- placeholder 保持 `sk-` 前缀（StepFun 密钥同格式）；form-text 中"服务器已配置默认密钥"提示逻辑不变（数据源换新配置）

#### 5) `app/templating.py` — `server_sk` 全局变量数据源改为 `bool(DEFAULT_STEP_KEY)`（变量名不变，前端零感知）

#### 6) 测试同步

- `tests/test_scripts_and_qwen.py`：import 路径 `app.services.qwen` → `app.services.llm`
- `tests/conftest.py` 及各测试中对 `section_router.chat` 等 monkeypatch 的引用路径同步检查（monkeypatch 打在 router 模块命名空间上则无需改，打在 services 路径上需改）
- **新增独立实测脚本** `test/test_stepfun_live.py`（见第六节）

#### 7) `README.md` — 环境变量表更新

| 变量 | 说明 |
|---|---|
| `STEPFUN_API_KEY` | 服务端默认对话生成密钥（阶跃星辰），前端 SK 弹窗可留空时回退 |
| `LLM_CHAT_URL` | 对话生成端点，默认 StepFun；可指向任意 OpenAI 兼容供应商 |
| `LLM_MODEL` | 默认 `step-3.7-flash` |
| `LLM_REASONING_EFFORT` | 推理强度 low/medium/high，默认 low；留空不下发 |
| `LLM_JSON_MODE` | JSON 强制模式开关，默认关（StepFun 支持未确认） |

同时删除 `DASHSCOPE_API_KEY` 相关行（TTS 已用 `MIMO_API_KEY`）。

### 决策点说明

| 决策 | 选择 | 理由 |
|---|---|---|
| 模块重命名 qwen.py→llm.py | 执行 | 项目已是双供应商架构（对话+TTS 各自独立），命名准确性优先；改动纯机械 |
| reasoning_effort 默认 low | 执行 | 防思维链挤占 4096/8192 输出预算导致截断；env 可调档 |
| 是否保留 DashScope 双后端切换 | 不做专门代码 | 配置化本身具备回退能力：改 env 即可切回任意兼容供应商 |
| finish_reason 截断检测加固 | 列为可选 | 实测若出现截断再加（报错优于静默产出残缺数据） |

---

## 五、风险提示

1. **参数兼容性需实测**：`temperature` 与 `reasoning_effort` 若被 StepFun 拒绝（HTTP 400），按报错移除对应字段即可（一行改动）
2. **成本变化**：输出单价 8.1 元/M 高于多数国产模型，但 low 档显著压缩输出 token；单任务约 3~8 次调用，量级可控。可在控制台账单页观察
3. **JSON 模式勿开启**：`response_format` 支持未经确认，保持默认关
4. **前端提示同步**：SK 弹窗标签改为"阶跃星辰"，避免用户误填千问 key

---

## 六、验证方案（以独立 .py 脚本实测）

按需求采用**编写 Python 测试脚本直接运行**的方式验证真实调用效果，不依赖 pytest fixture：

### 6.1 新增 `test/test_stepfun_live.py`

一个可直接运行的脚本，覆盖三层验证：

```python
"""StepFun 切换实测脚本 — python test/test_stepfun_live.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DEFAULT_STEP_KEY
from app.services.llm import chat, clean_json_response, parse_json_str, clean_html_output

KEY = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STEP_KEY
assert KEY, "请传入 STEP_API_KEY 或设置 STEPFUN_API_KEY 环境变量"

# ① 连通性 + 基础问答
r1 = chat("用一句话介绍阶跃星辰", KEY)
print("① 基础调用:", r1[:50], "...")

# ② 结构化 JSON 输出（模拟分章任务，验证 low 档推理下 max_tokens 预算充足）
md = "# 课件\n## 第一章 Python 基础\n变量与类型...\n## 第二章 流程控制\nif 与循环..."
r2 = chat(f"将以下内容分为两章，严格返回 JSON：{{\"sections\":[{{\"title\":\"...\",\"content\":\"...\"}}]}}\n{md}",
          KEY, max_tokens=4096)
sections = parse_json_str(clean_json_response(r2))
assert isinstance(sections.get("sections"), list), "分章 JSON 解析失败"
print("② 分章 JSON:", [s["title"] for s in sections["sections"]])

# ③ HTML 输出完整性（模拟幻灯片任务，验证无截断）
r3 = chat("生成一页 1920×1080 的 HTML 幻灯片，主题：Python 变量，返回完整 HTML", KEY, max_tokens=8192)
html = clean_html_output(r3)
assert html.strip().startswith("<") and "</html>" in html.lower(), f"HTML 可能截断"
print("③ 幻灯片 HTML:", len(html), "chars, 结尾正常")
print("✅ 三层实测全部通过")
```

运行方式：

```powershell
cd v2
conda run -n <环境名> python test/test_stepfun_live.py <你的STEP_API_KEY>
```

### 6.2 验证清单

| 步骤 | 内容 | 通过标准 |
|---|---|---|
| 1 | 运行 `test_stepfun_live.py` 三层实测 | 三项全部打印 ✅，无 HTTP 400（参数兼容性）、无 JSON 解析失败、HTML 以 `</html>` 收尾 |
| 2 | 设置 `STEPFUN_API_KEY` 启动服务，创建任务走全流程：上传 MD → 分章 → 生成 PPT → 截图 → 讲解稿 | 各步骤正常完成，服务端日志请求发往 `api.stepfun.com` 且无错误 |
| 3 | Step5 语音合成回归 | 不受影响，仍走 MiMo（`X-TTS-Key` 链路独立） |
| 4 | pytest 回归 | `conda run -n <环境名> python -m pytest tests -q` 21 例全绿 |
| 5 | 成本观察 | StepFun 控制台账单页核对调用量符合预期 |

### 6.3 回滚方案

配置化改造后回滚零代码改动：

```powershell
$env:LLM_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
$env:LLM_MODEL = "qwen-plus"
$env:LLM_REASONING_EFFORT = ""    # qwen-plus 非推理模型，不下发该参数
```
