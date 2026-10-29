# -*- coding: utf-8 -*-
"""LLM 单例（DeepSeek，OpenAI 兼容接口）。"""
from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI

from backend.core.config import get_settings
from backend.core.errors import ServiceUnavailableError


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    settings = get_settings()
    if not settings.llm_api_key:
        raise ServiceUnavailableError("未配置 DEEPSEEK_API_KEY，智能体暂不可用")
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def reset_llm() -> None:
    get_llm.cache_clear()


def extract_text(content) -> str:
    """兼容字符串与 LangChain 的内容块列表。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "text_delta"}:
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return ""
