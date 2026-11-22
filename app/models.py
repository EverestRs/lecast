"""SQLAlchemy ORM 模型：Task / Section / Slide / Script / Tts"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, LargeBinary, DateTime
from app.database import Base


class Task(Base):
    __tablename__ = "task"
    __table_args__ = {"comment": "任务主表"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(String(50), nullable=False, index=True, unique=True, comment="全局唯一任务ID")
    task_name = Column(String(50), nullable=False, comment="任务名称")
    content = Column(Text, nullable=True, comment="Markdown 原文")
    status = Column(String(20), nullable=False, default="uploaded", comment="进度状态")
    tts_voice = Column(String(30), nullable=False, default="冰糖", comment="TTS 合成音色")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_time = Column(DateTime, nullable=True, comment="最后更新时间")


class Section(Base):
    __tablename__ = "section"
    __table_args__ = {"comment": "章节表"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(String(50), nullable=False, index=True, comment="任务ID")
    section_order = Column(Integer, default=0, nullable=False, comment="顺序")
    title = Column(Text, nullable=True, comment="章节标题")
    content = Column(Text, nullable=True, comment="章节内容")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_time = Column(DateTime, nullable=True, comment="最后更新时间")


class Slide(Base):
    __tablename__ = "slide"
    __table_args__ = {"comment": "幻灯片内容表"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(String(50), nullable=False, index=True, comment="任务ID")
    slide_order = Column(Integer, default=0, nullable=False, comment="顺序")
    content = Column(Text, nullable=True, comment="HTML 格式幻灯片内容")
    status = Column(String(10), nullable=False, default="ok", comment="生成状态：ok/failed")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_time = Column(DateTime, nullable=True, comment="最后更新时间")


class Script(Base):
    __tablename__ = "script"
    __table_args__ = {"comment": "讲解脚本表"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(String(50), nullable=False, index=True, comment="任务ID")
    script_order = Column(Integer, default=0, nullable=False, comment="顺序")
    content = Column(Text, nullable=True, comment="脚本内容")
    status = Column(String(10), nullable=False, default="ok", comment="生成状态：ok/failed")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_time = Column(DateTime, nullable=True, comment="最后更新时间")


class Tts(Base):
    __tablename__ = "tts"
    __table_args__ = {"comment": "TTS语音合成结果表"}

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(String(50), nullable=False, index=True, comment="任务ID")
    tts_order = Column(Integer, default=0, nullable=False, comment="顺序")
    audio_url = Column(Text, nullable=True, comment="音频文件访问URL")
    content = Column(LargeBinary, nullable=True, comment="原始音频二进制数据（旧数据兼容，新数据落盘）")
    file_path = Column(String(255), nullable=True, comment="音频相对 DUMP_ROOT 的存储路径")
    status = Column(String(10), nullable=False, default="ok", comment="生成状态：ok/failed")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_time = Column(DateTime, nullable=True, comment="最后更新时间")