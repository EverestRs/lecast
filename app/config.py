"""应用配置"""

import os
import shutil
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 数据转储根目录（slide HTML、audio MP3 等）
DUMP_ROOT = BASE_DIR / "data"

# Python 视频处理脚本目录
SCRIPTS_DIR = BASE_DIR / "scripts"

# 数据库路径
DATABASE_URL = f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"

# ── AI 服务 ──
# 对话生成（OpenAI 兼容供应商，当前为阶跃星辰 StepFun；换供应商改 env 即可）
LLM_CHAT_URL = os.environ.get("LLM_CHAT_URL", "https://api.stepfun.com/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "step-3.7-flash")
DEFAULT_STEP_KEY = (os.environ.get("STEPFUN_API_KEY") or "").strip()
# 推理强度 low/medium/high：结构化生成用 low 防止思维链挤占输出预算；留空则不下发
LLM_REASONING_EFFORT = (os.environ.get("LLM_REASONING_EFFORT") or "").strip()

TTS_MODEL = os.environ.get("TTS_MODEL", "mimo-v2.5-tts")
TTS_VOICE = os.environ.get("TTS_VOICE", "冰糖")
# Xiaomi MiMo mimo-v2.5-tts 预置音色清单（逗号分隔可覆盖）
TTS_VOICE_CHOICES = [v.strip() for v in os.environ.get(
    "TTS_VOICE_CHOICES", "冰糖,茉莉,苏打,白桦").split(",") if v.strip()]
DEFAULT_MIMO_KEY = (os.environ.get("MIMO_API_KEY") or "").strip()

# 站点访问口令：设置后所有 /api 与页面需先通过 /login 校验（Cookie 门禁）；不设置则不启用
APP_ACCESS_TOKEN = (os.environ.get("APP_ACCESS_TOKEN") or "").strip() or None

# 分章接口启用 JSON 输出模式（response_format=json_object）。StepFun 支持未确认，实测后再开启
LLM_JSON_MODE = (os.environ.get("LLM_JSON_MODE") or "").lower() in ("1", "true", "yes")

# ── 超时与限额 ──
HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT", "600"))  # LLM/TTS 单次请求读/写超时
SUBPROCESS_MIN_TIMEOUT = float(os.environ.get("SUBPROCESS_MIN_TIMEOUT", "300"))  # 子进程超时下限（秒）
RECORD_TIMEOUT_PER_PAGE = float(os.environ.get("RECORD_TIMEOUT_PER_PAGE", "90"))  # 录制每页耗时预算
TIMEOUT_EXTRA = float(os.environ.get("TIMEOUT_EXTRA", "120"))  # 各阶段固定裕量
COMPOSE_TIMEOUT_FACTOR = float(os.environ.get("COMPOSE_TIMEOUT_FACTOR", "2"))  # 合成超时=音频时长×系数
FFMPEG_PATH = (
    os.environ.get("FFMPEG_PATH")
    or shutil.which("ffmpeg")
    or "ffmpeg"
)
PAGE_SIZE = int(os.environ.get("PAGE_SIZE", "10"))
UPLOAD_MAX_MB = int(os.environ.get("UPLOAD_MAX_MB", "5"))

# 确保数据目录存在
os.makedirs(DUMP_ROOT, exist_ok=True)
os.makedirs(BASE_DIR / "data", exist_ok=True)