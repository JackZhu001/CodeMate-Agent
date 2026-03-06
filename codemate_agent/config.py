"""
配置管理模块

从环境变量和配置文件加载配置。
"""

import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

# 模块加载时自动加载 .env 文件
load_dotenv()


@dataclass
class Config:
    """应用配置"""

    # API 提供商配置
    api_provider: str = field(default_factory=lambda: os.getenv("API_PROVIDER", "minimax"))

    # API 配置（支持多种提供商）
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("MODEL", "mini-max-chat"))
    base_url: str = field(default_factory=lambda: os.getenv("BASE_URL", "https://api.minimaxi.com/anthropic/v1"))

    # Light 模型配置（用于简单任务的轻量模型）
    light_model: str = field(default_factory=lambda: os.getenv("LIGHT_MODEL", ""))
    light_api_key: str = field(default_factory=lambda: os.getenv("LIGHT_API_KEY", ""))
    light_base_url: str = field(default_factory=lambda: os.getenv("LIGHT_BASE_URL", ""))

    # Agent 配置
    max_rounds: int = field(default_factory=lambda: int(os.getenv("MAX_ROUNDS", "50")))
    temperature: float = field(default_factory=lambda: float(os.getenv("TEMPERATURE", "0.7")))
    
    # 子代理配置
    subagent_max_steps: int = field(default_factory=lambda: int(os.getenv("SUBAGENT_MAX_STEPS", "15")))

    # 日志配置
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # Trace 日志配置
    trace_enabled: bool = field(default_factory=lambda: os.getenv("TRACE_ENABLED", "true").lower() == "true")
    trace_dir: Path = field(default_factory=lambda: Path(os.getenv("TRACE_DIR", "logs/traces")))

    # Metrics 配置
    metrics_enabled: bool = field(default_factory=lambda: os.getenv("METRICS_ENABLED", "true").lower() == "true")
    metrics_dir: Path = field(default_factory=lambda: Path(os.getenv("METRICS_DIR", "logs/sessions")))

    # 持久化配置
    persistence_enabled: bool = field(default_factory=lambda: os.getenv("PERSISTENCE_ENABLED", "true").lower() == "true")
    sessions_dir: Path = field(default_factory=lambda: Path(os.getenv("SESSIONS_DIR", "~/.codemate/sessions")))
    memory_dir: Path = field(default_factory=lambda: Path(os.getenv("MEMORY_DIR", "~/.codemate/memory")))

    # 项目配置
    config_dir: Path = field(default_factory=lambda: Path.home() / ".codemate")

    def __post_init__(self):
        """初始化后处理"""
        self.config_dir = Path(self.config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # 创建日志目录
        self.trace_dir = Path(self.trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)

        self.metrics_dir = Path(self.metrics_dir)
        self.metrics_dir.mkdir(parents=True, exist_ok=True)

        # 创建持久化目录
        self.sessions_dir = Path(self.sessions_dir).expanduser()
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self.memory_dir = Path(self.memory_dir).expanduser()
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> tuple[bool, Optional[str]]:
        """验证配置有效性"""
        if not self.api_key:
            return False, "未设置 API_KEY，请在 .env 文件中设置或使用环境变量"
        if self.max_rounds <= 0:
            return False, "MAX_ROUNDS 必须大于 0"
        if not 0 <= self.temperature <= 2:
            return False, "TEMPERATURE 必须在 0-2 之间"
        return True, None

    def get_light_config(self) -> dict:
        """
        获取 light 模型的配置
        
        如果未单独配置 light 模型，则使用主模型配置
        
        Returns:
            包含 api_key, model, base_url 的字典
        """
        return {
            "api_key": self.light_api_key or self.api_key,
            "model": self.light_model,
            "base_url": self.light_base_url or self.base_url,
        }

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "Config":
        """从环境变量加载配置"""
        if env_file is None:
            # 尝试查找 .env 文件
            cwd = Path.cwd()
            for path in [cwd, cwd.parent, Path.home()]:
                env_file = path / ".env"
                if env_file.exists():
                    break
            else:
                env_file = None

        if env_file and env_file.exists():
            load_dotenv(env_file)

        return cls()


# 全局配置实例
_global_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置实例"""
    global _global_config
    if _global_config is None:
        _global_config = Config.from_env()
    return _global_config


def set_config(config: Config) -> None:
    """设置全局配置"""
    global _global_config
    _global_config = config
