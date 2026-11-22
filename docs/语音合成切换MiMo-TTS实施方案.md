# 语音合成切换 Xiaomi MiMo-V2.5-TTS 实施方案（方案 A）

> 更新时间：2026-08-26
> 目标：将 v2 系统 TTS 服务由 DashScope `qwen3-tts-flash` 切换为小米 MiMo-V2.5-TTS，采用**方案 A**（直接落盘 `.wav`，不做 mp3 转码）。

---

## 一、可行性结论

**可以替换，且改动面很小。**

- TTS 在本项目中是独立封装（`app/services/tts_api.py`），调用方仅两处（`routers/tts.py` 的批量生成与单条重生成），只依赖 `synthesize()` 返回的 `bytes` 与 `audio_url`。
- 音频播放走本地接口 `/api/tts/audio`（前端 `<audio>` 直接指向该接口），不依赖远端音频 URL；`Tts.audio_url` 字段仅作存档，置空不影响任何功能。
- 下游视频合成使用 ffmpeg，对音频容器格式不敏感，`.mp3 → .wav` 仅需同步文件名。

### 附带发现的现存 Bug

`tts_api.py` 第 39 行引用了从未定义/导入的 `TTS_LANGUAGE`，当前 `synthesize()` 一旦调用即抛 `NameError`。本次重写自然消除该问题。

---

## 二、MiMo-V2.5-TTS 接口要点

来源：[官方文档 - 语音合成（MiMo-V2.5-TTS 系列）](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis-v2.5)

| 项目 | 内容 |
|---|---|
| 端点 | `https://api.xiaomimimo.com/v1/chat/completions`（OpenAI 兼容格式） |
| 模型 | `mimo-v2.5-tts`（预置音色）/ `mimo-v2.5-tts-voicedesign`（文生音色）/ `mimo-v2.5-tts-voiceclone`（音色复刻） |
| 待合成文本 | 必须放在 `role: assistant` 消息的 `content` 中 |
| 风格指令 | 可选，放 `role: user` 消息中（不影响合成文本内容）；支持自然语言与 `[音频标签]` 两种控制方式 |
| 音色参数 | `audio: {"format": "wav", "voice": "<音色名>"}` |
| 返回结果 | base64 音频内联于 `choices[0].message.audio.data`，无需二次下载 |
| 输出格式 | 仅支持 `wav` / `pcm16`（24kHz 单声道），**无 mp3 输出** |
| 预置音色 | 冰糖/茉莉（中文女）、苏打/白桦（中文男）、Mia/Chloe/Milo/Dean（英文） |
| 密钥 | 小米平台独立申请 `MIMO_API_KEY`，当前限时免费 |

### 调用示例（非流式）

```python
import base64, httpx

resp = httpx.post(
    "https://api.xiaomimimo.com/v1/chat/completions",
    headers={"Authorization": f"Bearer {MIMO_API_KEY}"},
    json={
        "model": "mimo-v2.5-tts",
        "messages": [
            {"role": "assistant", "content": "待合成的讲解稿文本"}
        ],
        "audio": {"format": "wav", "voice": "冰糖"},
    },
)
audio_bytes = base64.b64decode(resp.json()["choices"][0]["message"]["audio"]["data"])
```

---

## 三、与现有实现的差异对照

| 维度 | 现状（DashScope qwen3-tts-flash） | MiMo-V2.5-TTS | 影响 |
|---|---|---|---|
| 协议 | DashScope 私有 `input{text, voice, language_type}` | OpenAI messages + `audio{}` | 重写请求体 |
| 获取音频 | `output.audio.url` → 再 HTTP 下载 | base64 内联解码 | 少一步网络下载，逻辑更简单 |
| 音色 | Cherry / Serena / Ethan / Chelsie | 冰糖 / 茉莉 / 苏打 / 白桦 … | 需映射表兼容存量任务 |
| 密钥回退 | `DASHSCOPE_API_KEY` | 新增 `MIMO_API_KEY` | 新增配置项 |
| 语言参数 | `language_type` | 无此参数 | 直接删除 |
| 音频格式 | mp3 | wav（24kHz） | 落盘扩展名与 MIME 同步调整 |

---

## 四、实施方案 A（直接落盘 .wav）

### 4.1 改动清单（共 5 处）

#### 1) `app/config.py` — AI 服务配置区

```python
# ── AI 服务 ──
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")
TTS_MODEL = os.environ.get("TTS_MODEL", "mimo-v2.5-tts")          # 改
TTS_VOICE = os.environ.get("TTS_VOICE", "冰糖")                    # 改
# MiMo mimo-v2.5-tts 预置音色清单（逗号分隔可覆盖）
TTS_VOICE_CHOICES = [v.strip() for v in os.environ.get(
    "TTS_VOICE_CHOICES", "冰糖,茉莉,苏打,白桦").split(",") if v.strip()]   # 改
DEFAULT_DASHSCOPE_KEY = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
DEFAULT_MIMO_KEY = (os.environ.get("MIMO_API_KEY") or "").strip()   # 新增
```

前端音色下拉读取 `window.TTS_VOICES`（由模板注入 `TTS_VOICE_CHOICES`），自动跟随新清单，**零改动**。

#### 2) `app/services/tts_api.py` — 核心重写（约 60 行）

```python
"""Xiaomi MiMo TTS 语音合成接口封装（OpenAI 兼容 chat 格式）"""

import base64
import logging
from dataclasses import dataclass

import httpx

from app.config import DEFAULT_MIMO_KEY, HTTP_TIMEOUT_SECONDS, TTS_MODEL, TTS_VOICE

logger = logging.getLogger(__name__)

MIMO_TTS_URL = "https://api.xiaomimimo.com/v1/chat/completions"

TIMEOUT = httpx.Timeout(connect=10.0, read=HTTP_TIMEOUT_SECONDS,
                        write=HTTP_TIMEOUT_SECONDS, pool=10.0)
_client = httpx.Client(timeout=TIMEOUT, transport=httpx.HTTPTransport(retries=2))

# 存量任务 DB 中旧 DashScope 音色就近映射，避免历史记录失效
_LEGACY_VOICE_MAP = {
    "Cherry": "茉莉",
    "Serena": "冰糖",
    "Ethan": "苏打",
    "Chelsie": "茉莉",
}


@dataclass
class TtsResult:
    audio_url: str | None
    bytes: bytes


def _resolve_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        key = DEFAULT_MIMO_KEY
    if not key:
        raise ValueError("apiKey 不能为空（且服务端未配置 MIMO_API_KEY）")
    return key


def synthesize(text: str, api_key: str, voice: str = None) -> TtsResult:
    """调用 MiMo TTS（非流式），返回 WAV 音频二进制。

    :param voice: 音色；None 时取服务端配置 TTS_VOICE；旧音色名自动映射
    :raises ValueError: 参数校验失败
    :raises RuntimeError: API 调用失败
    """
    if not text or not text.strip():
        raise ValueError("text 不能为空")
    api_key = _resolve_key(api_key)
    voice = _LEGACY_VOICE_MAP.get(voice, voice or TTS_VOICE)

    payload = {
        "model": TTS_MODEL,
        # 文档要求：待合成文本必须放 assistant 角色，user 角色可选传风格指令
        "messages": [{"role": "assistant", "content": text.strip()}],
        "audio": {"format": "wav", "voice": voice},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        resp = _client.post(MIMO_TTS_URL, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise RuntimeError(f"MiMo TTS API 请求失败：{e}") from e

    if resp.status_code != 200:
        raise RuntimeError(f"MiMo TTS API 返回错误（HTTP {resp.status_code}）：{resp.text[:500]}")

    choices = resp.json().get("choices") or []
    audio = ((choices[0].get("message") or {}).get("audio") or {}) if choices else {}
    data = audio.get("data")
    if not data:
        raise RuntimeError("MiMo TTS API 响应中 message.audio.data 为空")

    return TtsResult(audio_url=None, bytes=base64.b64decode(data))
```

要点：
- **签名不变**：`synthesize(text, api_key, voice)` 保持原样，两个调用方零改动。
- `_resolve_key` 不再复用 `qwen._resolve_key`（其回退是 DASHSCOPE key），独立回退 `MIMO_API_KEY`。
- 删除 `download_audio()` 与 `language_type` 字段。

#### 3) `app/services/video.py` — 音频落盘扩展名 `.mp3` → `.wav`

共 4 处：

| 位置 | 原内容 | 改为 |
|---|---|---|
| `tts_abs_path` 相关 | `audios/tts_{order}.mp3` | `audios/tts_{order}.wav` |
| `save_tts_audio` 返回值 | `{taskId}/audios/tts_{order}.mp3` | `{taskId}/audios/tts_{order}.wav` |
| 合成前复制 | `dst = audios_dir / f"speech_{tts.tts_order}.mp3"` | `... .wav` |
| 合成扫描 glob | `audios_dir.glob("speech_*.mp3")` | `audios_dir.glob("speech_*.wav")` |

下游 `scripts/compose.py` 由 ffmpeg 读入音频做视频合成，容器格式自动探测，无需修改。

#### 4) `app/routers/tts.py` — 微调

```python
# /api/tts/audio 接口
inline_disposition = {"Content-Disposition": f'inline; filename="{task_id}_tts_{tts_order}.wav"'}
...
return FileResponse(path=fp, media_type="audio/wav", headers=inline_disposition)
...
return Response(content=tts.content, media_type="audio/wav", headers=inline_disposition)
```

`audio_url=result.audio_url` 两处保持原样（新实现返回 None，字段仅存档）。

> 兼容提示：切换上线前已生成的旧 `.mp3` 文件仍按旧扩展名落盘，`file_path` 记录未变，
> `/api/tts/audio` 按 `file_path` 读取不受影响；仅 MIME 头统一改为 `audio/wav`，
> 浏览器对 `<audio>` 会按实际容器探测，播放无碍。如需严格区分，可在 FileResponse 处按扩展名选择 media_type。

#### 5) `app/database.py` / `app/models.py` — 默认音色

```python
# database.py
ensure_column("task", "tts_voice", "VARCHAR(30) NOT NULL DEFAULT '冰糖'")

# models.py
tts_voice = Column(String(30), nullable=False, default="冰糖", comment="TTS 合成音色")
```

存量任务的旧音色值（Cherry 等）由 `_LEGACY_VOICE_MAP` 兜底，**无需迁移数据库**。
前端 [task_create_steps.js](../app/static/js/task_create_steps.js) 第 639 行硬编码 fallback `'Cherry'` 建议顺手删除，统一取 `window.TTS_VOICE_DEFAULT`。

### 4.2 决策说明：为何选方案 A

| 对比项 | 方案 A：直存 .wav（选定） | 方案 B：ffmpeg 转 mp3 再落盘 |
|---|---|---|
| 实现成本 | 低，仅改文件名/MIME | 中，每次合成多一次子进程调用 |
| 音质 | 无转码损耗 | 有损压缩 |
| 磁盘占用 | 约 10 倍于 mp3 | 小 |
| 全链路一致性 | 扩展名/类型全量同步 | 保持现状不动 |

本项目为内部工具型系统，任务量有限，磁盘占用可控；优先保证链路简单与零转码损耗。

---

## 五、风险与注意事项

1. **双密钥并存**：若文案/脚本生成仍用通义千问，则 `DASHSCOPE_API_KEY` 与 `MIMO_API_KEY` 同时生效；
   前端 `X-API-Key` 头传入的密钥会直接用于对应服务，两套服务的回退变量互不干扰。
2. **计费**：MiMo TTS 当前限时免费，正式启用前在[账单明细](https://platform.xiaomimimo.com/#/console/usage)确认政策变化。
3. **文本长度**：官方未标注单次合成文本上限；超长讲解稿合成失败会落入现有"逐条重试"兜底流程，风险可控。
4. **模型版本**：MiMo-V2 系列已于 2026-06-30 下线，务必使用 `mimo-v2.5-*` 系列模型名。
5. **后续扩展空间**：`voicedesign`（文生音色）/ `voiceclone`（音色复刻）模型接口形态一致，
   未来增加"自定义音色"功能仅需扩展 payload 构造，架构已留口子。

---

## 六、验证步骤

1. 配置环境变量 `MIMO_API_KEY` 后启动服务。
2. 创建测试任务，走完整流程：上传 MD → 分章 → 生成 PPT → 截图 → 生成讲解稿 → **Step5 生成全部音频**。
3. 校验：
   - `data/<taskId>/audios/` 下生成 `tts_N.wav`，可用播放器确认声音正常、音色正确；
   - 任务创建页 Step5 列表中 `<audio>` 可正常播放（经 `/api/tts/audio`）；
   - 单条"重生成"功能正常；
   - Step6 导出视频成功且配音与画面同步（验证 ffmpeg 读 wav 正常）。
4. 存量任务回归：打开一个旧任务（音色为 Cherry），执行单条重生成，确认映射到新音色后正常出声。
5. 运行既有测试套件（`tests/`），确认无回归。
