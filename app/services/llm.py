"""对话生成 LLM 接口封装（OpenAI 兼容协议，当前接入阶跃星辰 StepFun）— 对应原 v1 的 QwenService.java"""

import json
import logging

import httpx

from app.config import (DEFAULT_STEP_KEY, HTTP_TIMEOUT_SECONDS, LLM_CHAT_URL,
                        LLM_JSON_MODE, LLM_MODEL, LLM_REASONING_EFFORT)

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=10.0, read=HTTP_TIMEOUT_SECONDS, write=HTTP_TIMEOUT_SECONDS, pool=10.0)

# 复用连接池；retries 仅对连接类错误自动重试（网络瞬断容错）
_client = httpx.Client(timeout=TIMEOUT, transport=httpx.HTTPTransport(retries=2))


def _resolve_key(api_key: str) -> str:
    """请求未带密钥时回退服务端默认密钥（STEPFUN_API_KEY）"""
    key = (api_key or "").strip()
    if not key:
        key = DEFAULT_STEP_KEY
    if not key:
        raise ValueError("apiKey 不能为空（且服务端未配置 STEPFUN_API_KEY）")
    return key


def chat(
    prompt: str,
    api_key: str,
    model: str = LLM_MODEL,
    max_tokens: int | None = None,
    json_mode: bool | None = None,
) -> str:
    """调用对话模型 Chat API（OpenAI 兼容模式），返回模型回答文本。

    :param max_tokens: 输出上限；None 时不下发该字段（走模型默认）
    :param json_mode: 是否启用 response_format=json_object；None 时取 LLM_JSON_MODE 配置
    :raises ValueError: 参数校验失败
    :raises RuntimeError: API 调用失败（网络、认证、模型错误等）
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt 不能为空")
    api_key = _resolve_key(api_key)

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    # 推理强度：结构化生成用 low 档防止思维链挤占输出预算；配置留空则不下发
    if LLM_REASONING_EFFORT:
        payload["reasoning_effort"] = LLM_REASONING_EFFORT
    if LLM_JSON_MODE if json_mode is None else json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = _client.post(LLM_CHAT_URL, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise RuntimeError(f"对话模型 API 请求失败：{e}") from e

    if resp.status_code != 200:
        raise RuntimeError(f"对话模型 API 返回错误（HTTP {resp.status_code}）：{resp.text[:500]}")

    body = resp.json()
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("对话模型 API 响应中未返回 choices")

    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    # reasoning 是思维链而非业务回答，不能当作 JSON/HTML 内容返回。
    if not content.strip():
        finish_reason = choices[0].get("finish_reason") or "unknown"
        reasoning_tokens = (body.get("usage") or {}).get("completion_tokens_details", {}).get("reasoning_tokens")
        detail = f"，finish_reason={finish_reason}"
        if reasoning_tokens is not None:
            detail += f"，reasoning_tokens={reasoning_tokens}"
        raise RuntimeError(f"对话模型 API 未返回最终回答（content 为空{detail}），请增大 max_tokens 或降低推理强度")
    return content.strip()


def clean_json_response(text: str) -> str:
    """清洗大模型返回的 JSON 字符串（去除 ```json 代码块包裹、截取 JSON 主体）。

    对于 StepFun 推理模型（step-3.7-flash 等），模型可能将 reasoning/reasoning_content
    字段内嵌到返回的 JSON 中；其值含 \\n 等转义字符，某些情况下会让 json.loads 报错。
    本函数仅在解析失败时才尝试剔除这些字段，避免误伤正常业务数据。
    """
    import re
    cleaned = text.strip()
    if cleaned.lower().startswith("```json"):
        prefix_len = len("```json")
        end_marker = cleaned.find("```", prefix_len)
        cleaned = cleaned[prefix_len:end_marker].strip() if end_marker != -1 else cleaned[prefix_len:].strip()
    elif cleaned.startswith("```"):
        end_marker = cleaned.find("```", 3)
        cleaned = cleaned[3:end_marker].strip() if end_marker != -1 else cleaned[3:].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()

    # 尝试直接解析；若失败（StepFun 推理模型的 reasoning 字段常导致 Unterminated string），
    # 则剔除这些字段后重试
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    # StepFun 推理模型（step-3.7-flash 等）常把 reasoning/reasoning_content 字段注入 JSON，
    # 其值可能含换行/特殊字符导致 json.loads 报错；剔除这些字段后重试
    # 注意：\b 不能放在 " 前（" 是非单词字符），改用 [^a-zA-Z0-9_] 负向词边界
    cleaned = re.sub(
        r'(?<=[^a-zA-Z0-9_])"(reasoning|reasoning_content|reason)"\s*:\s*'
        r'(?:"[^"]*"|"[^"\\]*(?:\\.[^"\\]*)*"|\{[^}]*\}|\[[^\]]*\])',
        '',
        cleaned,
        flags=re.DOTALL,
    )
    # 剔除后可能留下连续逗号、多余空格或末尾逗号，归一化
    cleaned = re.sub(r',\s*,', ',', cleaned)      # 双逗号 → 单逗号
    cleaned = re.sub(r'\s+', ' ', cleaned)        # 多余空格合并
    cleaned = re.sub(r',\s*}', '}', cleaned)      # 末尾多余逗号

    # 模型可能先输出代码解释（如 {j}×{i}={i*j}）再输出 JSON，扫描候选对象。
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("sections"), list):
            return cleaned[index:index + end]
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return cleaned[index:index + end]
    return cleaned.strip()
    return cleaned.strip()


def parse_json_str(cleaned: str):
    """解析清洗后的 JSON，失败时报错附原始返回前 200 字便于排查"""
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"AI 返回非标准 JSON（{e}），原始片段：{cleaned[:200]}") from e


def clean_html_output(html: str) -> str:
    """清洗大模型返回的 HTML（去除 ```html 代码块包裹）"""
    cleaned = html.strip()
    if cleaned.lower().startswith("```html"):
        end_marker = cleaned.find("```", 8)
        cleaned = cleaned[8:end_marker].strip() if end_marker != -1 else cleaned[8:].strip()
    elif cleaned.startswith("```"):
        end_marker = cleaned.find("```", 3)
        cleaned = cleaned[3:end_marker].strip() if end_marker != -1 else cleaned[3:].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return cleaned
