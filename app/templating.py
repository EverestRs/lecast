"""Jinja2 模板实例（独立模块，避免循环导入）"""

from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.config import DEFAULT_MIMO_KEY, DEFAULT_STEP_KEY, TTS_VOICE, TTS_VOICE_CHOICES

# 发布时更新此版本号以强制刷新浏览器缓存的静态资源
STATIC_VERSION = "20261026.1"

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["static_v"] = STATIC_VERSION
# 服务端是否配置了默认对话模型密钥（前端 SK 弹窗据此提示"可留空"）
templates.env.globals["server_sk"] = bool(DEFAULT_STEP_KEY)
# 服务端是否配置了默认 MiMo 密钥（TTS）
templates.env.globals["server_mimo_sk"] = bool(DEFAULT_MIMO_KEY)
# 音色清单与默认音色（前端 Step5 下拉使用）
templates.env.globals["tts_voices"] = list(TTS_VOICE_CHOICES)
templates.env.globals["tts_voice_default"] = TTS_VOICE