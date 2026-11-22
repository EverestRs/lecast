# -*- coding: utf-8 -*-
"""scripts 纯函数与对话模型输出清洗"""
import pytest

from scripts.utils import get_audio_duration_ms, list_slides_and_audios
from app.services.llm import clean_json_response, parse_json_str


def _make_dirs(tmp_path, slide_nums, audio_nums):
    s, a = tmp_path / "slides", tmp_path / "audios"
    s.mkdir(), a.mkdir()
    for n in slide_nums:
        (s / f"slide_{n}.html").write_text("<p/>", encoding="utf-8")
    for n in audio_nums:
        (a / f"speech_{n}.wav").write_bytes(b"id3")
    return s, a


def test_list_pairs_ok(tmp_path):
    s, a = _make_dirs(tmp_path, [1, 2, 3], [1, 2, 3])
    pairs = list_slides_and_audios(s, a)
    assert [int(p[0].stem.split("_")[1]) for p in pairs] == [1, 2, 3]


def test_list_pairs_missing_audio(tmp_path):
    s, a = _make_dirs(tmp_path, [1, 2], [1])
    with pytest.raises(ValueError, match="缺失音频"):
        list_slides_and_audios(s, a)


def test_list_pairs_gap(tmp_path):
    s, a = _make_dirs(tmp_path, [1], [1])
    (s / "slide_5.html").write_text("<p/>")
    with pytest.raises(ValueError, match="不连续"):
        list_slides_and_audios(s, a)


def test_duration_raises_on_bad_file(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"this is not audio")
    with pytest.raises(RuntimeError):
        get_audio_duration_ms(bad)


def test_clean_json_strips_fence():
    assert clean_json_response('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_clean_json_extracts_braces():
    junk = '好的，结果如下：\n{"sections": [{"title": "t"}]}\n以上。'
    assert clean_json_response(junk) == '{"sections": [{"title": "t"}]}'


def test_parse_error_includes_snippet():
    with pytest.raises(RuntimeError, match="原始片段"):
        parse_json_str("完全不是 JSON")


def test_build_pairs_rejects_empty_audio(tmp_path):
    from scripts.compose import build_pairs
    v, a = tmp_path / "v", tmp_path / "a"
    v.mkdir(), a.mkdir()
    (v / "slide_1.mp4").write_bytes(b"x")
    (a / "speech_1.wav").write_bytes(b"")  # 空文件
    with pytest.raises(ValueError, match="音频为空"):
        build_pairs(v, a)
