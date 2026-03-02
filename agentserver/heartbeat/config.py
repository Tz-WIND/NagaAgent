"""
Heartbeat 配置模型
"""

from pydantic import BaseModel, Field


class HeartbeatConfig(BaseModel):
    """心跳系统配置"""

    enabled: bool = Field(default=False, description="总开关")
    interval_minutes: int = Field(default=30, ge=1, le=1440, description="心跳间隔（分钟）")
    ack_max_chars: int = Field(default=300, ge=50, le=2000, description="静默阈值：响应 ≤ 此长度且含 HEARTBEAT_OK 则不推送")
    active_hours_start: str = Field(default="08:00", description="活跃时段开始，如 '08:00'")
    active_hours_end: str = Field(default="23:00", description="活跃时段结束，如 '23:00'")
    prompt: str = Field(default="", description="自定义心跳 prompt（空则使用默认检查清单）")
    post_conversation_delay_minutes: int = Field(
        default=5, ge=1, le=60,
        description="对话结束后延迟多少分钟执行心跳（事件驱动模式）"
    )
