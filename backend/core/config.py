# -*- coding: utf-8 -*-
"""全局配置：pydantic-settings，启动时完成基础校验。

密钥只从环境变量或 .env 读取，代码中不出现真实值。
development 模式允许缺少 LLM Key（对应接口返回 503），便于先看前端。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """应用配置，环境变量名与 .env 一致（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # ---------------- 运行环境 ----------------
    app_env: Literal["development", "production", "test"] = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    cors_origins_raw: str = Field(default="", validation_alias="CORS_ORIGINS")

    # ---------------- 访问控制 ----------------
    api_keys_raw: str = Field(default="", validation_alias="API_KEYS")
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60
    ingest_rate_limit_requests: int = 3
    ingest_rate_limit_window_seconds: int = 3600
    demo_role_header_enabled: bool = True
    # 仅当服务部署在可信反向代理之后才开启，否则客户端可伪造 X-Forwarded-For 绕过限流
    trust_proxy_headers: bool = False

    # ---------------- LLM ----------------
    llm_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
    llm_base_url: str = Field(
        default="https://api.deepseek.com", validation_alias="DEEPSEEK_BASE_URL"
    )
    llm_model: str = Field(default="deepseek-chat", validation_alias="DEEPSEEK_MODEL")
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # ---------------- Embedding / Rerank ----------------
    embed_api_key: str = Field(default="", validation_alias="SILICONFLOW_API_KEY")
    embed_base_url: str = Field(
        default="https://api.siliconflow.cn/v1", validation_alias="SILICONFLOW_BASE_URL"
    )
    embed_model: str = Field(
        default="BAAI/bge-large-zh-v1.5", validation_alias="SILICONFLOW_EMBED_MODEL"
    )
    embed_batch_size: int = 32
    http_timeout_seconds: float = 30.0
    rerank_model: str = Field(
        default="BAAI/bge-reranker-v2-m3", validation_alias="RERANK_MODEL"
    )

    # ---------------- 数据与索引 ----------------
    data_dir: Path = Field(default=Path("./data"), validation_alias="DATA_DIR")
    db_path: Path = Field(default=Path("./data/shop.db"), validation_alias="DB_PATH")
    chroma_dir: Path = Field(default=Path("./chroma_db"), validation_alias="CHROMA_DIR")

    # ---------------- 检索 ----------------
    chunk_size: int = 420
    chunk_overlap: int = 40
    top_k: int = 3
    recall_k: int = 15
    rerank_top_k: int = 3
    warmup_index: bool = True

    # ---------------- Agent ----------------
    stream_enabled: bool = True
    agent_max_tool_calls: int = 6
    pending_action_ttl_seconds: int = 300

    @field_validator("data_dir", "db_path", "chroma_dir", mode="after")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else (ROOT_DIR / value).resolve()

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return str(value).upper()

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP 必须小于 CHUNK_SIZE")
        if self.rerank_top_k > self.recall_k:
            raise ValueError("RERANK_TOP_K 不能大于 RECALL_K")
        if self.agent_max_tool_calls < 1:
            raise ValueError("AGENT_MAX_TOOL_CALLS 必须大于 0")
        if self.rate_limit_requests < 1 or self.rate_limit_window_seconds < 1:
            raise ValueError("限流参数必须为正整数")
        if self.is_production:
            missing = self.missing_required_keys
            if missing:
                raise ValueError("生产环境缺少必要配置：" + "、".join(missing))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def api_keys(self) -> list[str]:
        return [k.strip() for k in self.api_keys_raw.split(",") if k.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    @property
    def embedding_enabled(self) -> bool:
        return bool(self.embed_api_key)

    @property
    def missing_required_keys(self) -> list[str]:
        missing = []
        if not self.llm_api_key:
            missing.append("DEEPSEEK_API_KEY")
        if self.is_production and not self.api_keys:
            missing.append("API_KEYS")
        return missing

    @property
    def chat_ready(self) -> bool:
        return bool(self.llm_api_key)

    def safe_summary(self) -> dict:
        return {
            "app_env": self.app_env,
            "llm_model": self.llm_model,
            "embed_model": self.embed_model,
            "rerank_model": self.rerank_model,
            "llm_key_configured": bool(self.llm_api_key),
            "embed_key_configured": bool(self.embed_api_key),
            "auth_enabled": self.auth_enabled,
            "db_path": str(self.db_path),
            "chroma_dir": str(self.chroma_dir),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
