# -*- coding: utf-8 -*-
"""验证 clean_json_response 剔除 StepFun reasoning 推理字段"""
import json
from app.services.llm import clean_json_response, parse_json_str


def test_clean_json_strips_reasoning_field():
    # 构造含字面换行符的非法 JSON（模拟 StepFun 模型将推理内容注入 JSON 后的真实输出）
    raw = '{"sections": [{"title": "test", "content": "body"}], ' \
          '"reasoning": "chain of thought' + chr(10) + ' with newlines", ' \
          '"reasoning_content": "more thoughts"}'
    cleaned = clean_json_response(raw)
    # 解析应成功
    result = parse_json_str(cleaned)
    assert result["sections"][0]["title"] == "test"
    assert "reasoning" not in cleaned

def test_clean_json_strips_reasoning_between_fields():
    # 相邻字段的逗号问题："a":1,"reasoning":"x\ny","b":2 应变成 "a":1,"b":2
    raw = '{"a":1,"reasoning":"thought' + chr(10) + 'more","b":2}'
    cleaned = clean_json_response(raw)
    result = parse_json_str(cleaned)
    assert result == {"a": 1, "b": 2}


def test_clean_json_skips_code_brace_before_sections():
    raw = (
        '下面是代码解释：{j}×{i}={i*j}"，end="\\t") print()\n'
        '最终结果：{"sections":[{"title":"章节一","content":"正文"}]}'
    )
    result = parse_json_str(clean_json_response(raw))
    assert result["sections"][0]["title"] == "章节一"

def test_clean_json_strips_reasoning_with_special_chars():
    raw = (
        '{"sections":[{"title":"项目基本信息与实验概述",'
        '"content":"# 三级项目：基于华为Atlas 200\\n\\n> 对应项目"}],'
        '"reasoning":"some reasoning text with \\n special chars"}'
    )
    cleaned = clean_json_response(raw)
    result = parse_json_str(cleaned)
    assert result["sections"][0]["title"] == "项目基本信息与实验概述"


def test_clean_json_still_handles_fence_and_text():
    # 原有行为：```json 代码块包裹
    fenced = '```json\n{"a": 1}\n```'
    assert parse_json_str(clean_json_response(fenced)) == {"a": 1}
    # 原有行为：JSON 前后附文字
    wrapped = '好的，结果如下：\n{"sections": []}\n以上。'
    assert parse_json_str(clean_json_response(wrapped)) == {"sections": []}
