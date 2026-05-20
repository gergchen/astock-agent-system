"""模型适配层 — 模型名称路由与能力检测.

DeepSeek 当前只有一个模型 (deepseek-v4-pro)，此模块为
未来多模型路由预留扩展点。
"""

from dataclasses import dataclass, field


@dataclass
class ModelInfo:
    name: str
    provider: str
    max_tokens: int = 4096
    supports_vision: bool = False
    supports_tools: bool = True
    supports_streaming: bool = False


MODELS: dict[str, ModelInfo] = {
    "deepseek-v4-pro": ModelInfo(
        name="deepseek-v4-pro",
        provider="deepseek",
        max_tokens=4096,
        supports_vision=False,
        supports_tools=True,
        supports_streaming=False,
    ),
}


class ModelAdapter:
    """模型适配器 — 根据能力路由到正确的模型."""

    @staticmethod
    def get_model(name: str | None = None) -> ModelInfo:
        if name is None:
            from ..config import get_config
            name = get_config().llm_model
        if name not in MODELS:
            raise ValueError(f"Unknown model: {name}. Available: {list(MODELS)}")
        return MODELS[name]

    @staticmethod
    def register_model(info: ModelInfo) -> None:
        MODELS[info.name] = info
