# -*- coding: utf-8 -*-
"""测试夹具：每个测试会话使用独立临时数据库，完全不依赖外网与真实密钥。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须在导入 backend 之前设置，保证 Settings 读取到测试配置
_TMP_DIR = Path(tempfile.mkdtemp(prefix="shoppilot-test-"))
os.environ["APP_ENV"] = "test"
os.environ["DB_PATH"] = str(_TMP_DIR / "shop.db")
os.environ["CHROMA_DIR"] = str(_TMP_DIR / "chroma")
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["SILICONFLOW_API_KEY"] = ""
os.environ["API_KEYS"] = ""
os.environ["DEMO_ROLE_HEADER_ENABLED"] = "true"
os.environ["RATE_LIMIT_REQUESTS"] = "1000"


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    """重建并灌入演示数据，整个测试会话共用。"""
    from backend.core.config import reset_settings

    reset_settings()
    from scripts.seed_db import main

    argv = sys.argv
    sys.argv = ["seed_db.py"]
    try:
        main()
    finally:
        sys.argv = argv
    yield Path(os.environ["DB_PATH"])


@pytest.fixture()
def client(seeded_db):
    from fastapi.testclient import TestClient

    from backend.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
