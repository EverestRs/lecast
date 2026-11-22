# -*- coding: utf-8 -*-
"""StepFun 切换实测脚本（真实调用，非 mock）

用法：
    python tests/test_stepfun_live.py <你的STEP_API_KEY>
或提前设置环境变量 STEPFUN_API_KEY 后省略参数。

三层验证：① 连通性 ② 分章 JSON 结构化输出（low 档推理 + max_tokens 预算）
         ③ 幻灯片 HTML 完整性（无截断，以 </html> 收尾）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DEFAULT_STEP_KEY, LLM_MODEL, LLM_REASONING_EFFORT
from app.services.llm import chat, clean_html_output, clean_json_response, parse_json_str

KEY = sys.argv[1].strip() if len(sys.argv) > 1 else DEFAULT_STEP_KEY
if not KEY:
    print("❌ 未提供密钥：请以参数传入 STEP_API_KEY，或设置环境变量 STEPFUN_API_KEY")
    sys.exit(1)

print(f"模型：{LLM_MODEL} | reasoning_effort：{LLM_REASONING_EFFORT or '不下发'}\n")

# ① 连通性 + 基础问答
r1 = chat("用一句话介绍阶跃星辰StepFun", KEY)
assert r1 and r1.strip(), "① 基础调用返回为空"
print(f"① 基础调用 OK：{r1[:60]}...")

# ② 结构化 JSON 输出（模拟分章任务，验证 low 档推理下 4096 预算充足且 JSON 可解析）
md = ("# 课件示例\n\n## 第一章 Python 基础\n变量、数据类型与运算符的介绍……\n\n"
      "## 第二章 流程控制\n条件语句 if 与循环 for/while 的用法……")
prompt2 = (
    "请将以下课件内容划分为合理的章节，严格按 JSON 格式返回（仅输出 JSON，无任何额外说明）：\n"
    '{"sections": [{"title": "章节标题", "content": "章节内容"}]}\n\n'
    f"待分析内容：\n```markdown\n{md}\n```"
)
r2 = chat(prompt2, KEY, max_tokens=4096)
sections = parse_json_str(clean_json_response(r2))
assert isinstance(sections.get("sections"), list) and sections["sections"], "② 分章 JSON 解析失败"
print(f"② 分章 JSON OK：{[s.get('title') for s in sections['sections']]}")

# ③ HTML 输出完整性（模拟幻灯片任务，验证 8192 预算下无截断）
r3 = chat("生成一页 1920×1080 的完整 HTML 幻灯片，主题：Python 变量。只返回 HTML 代码。", KEY, max_tokens=8192)
html = clean_html_output(r3)
assert html.lstrip().startswith("<"), "③ HTML 开头异常（可能带说明文字）"
assert "</html>" in html.lower(), "③ HTML 未以 </html> 结尾，疑似被截断（可尝试调低 reasoning_effort 或加大 max_tokens）"
print(f"③ 幻灯片 HTML OK：{len(html)} 字符，结尾正常")

print("\n✅ 三层实测全部通过")
