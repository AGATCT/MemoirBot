"""
LLM 提供商注册表。

管理所有可用的 LLM 提供商，按名称查找和实例化。
"""

from app.chat.providers.base import LLMConfig, LLMProvider
from app.chat.providers.deepseek import DeepSeekProvider

# 注册表：名称 → 提供商类
_providers: dict[str, type[LLMProvider]] = {
    "deepseek": DeepSeekProvider,
}


def register_provider(name: str, provider_cls: type[LLMProvider]) -> None:
    """注册一个新的 LLM 提供商。"""
    _providers[name] = provider_cls


def get_provider(name: str, config: LLMConfig) -> LLMProvider:
    """根据名称获取 LLM 提供商实例。

    Raises:
        ValueError: 提供商名称不存在
    """
    cls = _providers.get(name)
    if cls is None:
        available = ", ".join(_providers.keys())
        raise ValueError(f"未知的 LLM 提供商: {name}（可用: {available}）")
    return cls(config)


def list_providers() -> list[str]:
    """列出所有可用的 LLM 提供商名称。"""
    return list(_providers.keys())
