"""Xiaomi MiMo TTS（mimo-v2.5-tts）语音合成接口封装 — 替代原 DashScope qwen3-tts"""

import base64
import logging
from dataclasses import dataclass

import httpx

from app.config import DEFAULT_MIMO_KEY, HTTP_TIMEOUT_SECONDS, TTS_MODEL, TTS_VOICE

logger = logging.getLogger(__name__)

MIMO_TTS_URL = "https://api.xiaomimimo.com/v1/chat/completions"

TIMEOUT = httpx.Timeout(connect=10.0, read=HTTP_TIMEOUT_SECONDS, write=HTTP_TIMEOUT_SECONDS, pool=10.0)

# 与 qwen 同策略：连接池复用 + 连接级自动重试
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
    """请求未带密钥时回退服务端默认密钥（MIMO_API_KEY）"""
    key = (api_key or "").strip()
    if not key:
        key = DEFAULT_MIMO_KEY
    if not key:
        raise ValueError("apiKey 不能为空（且服务端未配置 MIMO_API_KEY）")
    return key


def synthesize(text: str, api_key: str, voice: str = None) -> TtsResult:
    """调用 MiMo TTS（非流式），返回 WAV 音频二进制。

    MiMo 走 OpenAI 兼容 chat 格式：待合成文本必须放 assistant 角色；
    返回的 base64 音频内联在 choices[0].message.audio.data，无需二次下载。

    :param voice: 音色；None 时取服务端配置 TTS_VOICE；旧 DashScope 音色名自动映射
    :raises ValueError: 参数校验失败
    :raises RuntimeError: API 调用失败
    """
    if not text or not text.strip():
        raise ValueError("text 不能为空")
    api_key = _resolve_key(api_key)
    voice = _LEGACY_VOICE_MAP.get(voice, voice or TTS_VOICE)

    payload = {
        "model": TTS_MODEL,
        "messages": [{"role": "assistant", "content": text.strip()}],
        "audio": {"format": "wav", "voice": voice},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

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