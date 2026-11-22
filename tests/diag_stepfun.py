"""诊断 StepFun 真实调用：打印完整请求与响应，便于定位空内容问题"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import LLM_CHAT_URL, LLM_MODEL, LLM_REASONING_EFFORT, DEFAULT_STEP_KEY
from app.services.llm import _resolve_key, clean_json_response, parse_json_str
import httpx

KEY = sys.argv[1].strip() if len(sys.argv) > 1 else ""
if not KEY:
    print("用法：python diag_stepfun.py <STEP_API_KEY>")
    sys.exit(1)

prompt = """请分析以下 Markdown 格式的课件内容，将其划分为合理的章节，并为每个章节生成一个标题。

待分析内容：
```markdown
# 浏览器测试
这是一个测试课件。
```

请严格按以下 JSON 格式返回结果（仅输出 JSON，不要任何额外说明）：
{"sections": [{"title": "章节标题", "content": "章节内容"}]}"""

payload = {
    "model": LLM_MODEL,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.3,
    "max_tokens": 4096,
}
if LLM_REASONING_EFFORT:
    payload["reasoning_effort"] = LLM_REASONING_EFFORT

headers = {"Authorization": f"Bearer {_resolve_key(KEY)}", "Content-Type": "application/json"}

print(f"URL: {LLM_CHAT_URL}")
print(f"Model: {LLM_MODEL}")
print(f"Reasoning effort: {LLM_REASONING_EFFORT or '不下发'}")
print(f"\n请求体（前500字）：{json.dumps(payload, ensure_ascii=False, indent=2)[:500]}")
print("\n--- 发送请求 ---")

try:
    resp = httpx.post(LLM_CHAT_URL, json=payload, headers=headers, timeout=120)
    print(f"HTTP {resp.status_code}")
    print(f"响应头：{dict(resp.headers)}")
    text = resp.text[:2000]
    print(f"响应体：\n{text}")
    if resp.status_code == 200:
        body = resp.json()
        choices = body.get("choices")
        print(f"\nchoices 数量：{len(choices) if choices else 0}")
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            print(f"content 长度：{len(content) if content else 0}")
            print(f"content 前200字：{(content or '')[:200]}")
            if content:
                cleaned = clean_json_response(content)
                print(f"\n清洗后前200字：{cleaned[:200]}")
                try:
                    parsed = parse_json_str(cleaned)
                    print(f"解析成功：{json.dumps(parsed, ensure_ascii=False, indent=2)[:500]}")
                except Exception as e:
                    print(f"解析失败：{e}")
    else:
        print(f"请求失败，查看响应体排查原因")
except Exception as e:
    print(f"异常：{type(e).__name__}: {e}")
