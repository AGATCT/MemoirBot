"""
配置管理模块。

从环境变量和 .env 文件加载配置，提供默认值。
使用 pydantic-settings 管理所有配置项。
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，自动从环境变量 / .env 文件加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM 配置 ---
    deepseek_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.7
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # --- 数据目录 ---
    personal_agent_data_dir: str = "./data"

    # --- 服务配置 ---
    host: str = "127.0.0.1"
    port: int = 8000

    # --- 记忆系统配置 ---
    extraction_interval: int = 3        # 每 N 轮对话触发一次提取
    dream_interval_hours: int = 24      # Dream 最小间隔（小时）
    dream_min_sessions: int = 5         # Dream 最少积累会话数
    dream_check_interval_minutes: int = 60  # Dream 调度检查间隔（分钟）

    # --- 派生属性 ---
    @property
    def data_dir(self) -> Path:
        return Path(self.personal_agent_data_dir).resolve()

    @property
    def diaries_dir(self) -> Path:
        return self.data_dir / "diaries"

    @property
    def chats_dir(self) -> Path:
        return self.data_dir / "chats"

    @property
    def memories_dir(self) -> Path:
        return self.data_dir / "memories"

    @property
    def profile_dir(self) -> Path:
        return self.data_dir / "profile"

    @property
    def system_dir(self) -> Path:
        return self.data_dir / "system"


# 全局单例
settings = Settings()
