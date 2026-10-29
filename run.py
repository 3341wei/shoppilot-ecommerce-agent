# -*- coding: utf-8 -*-
"""本地启动脚本。

    python run.py
"""
from __future__ import annotations

import uvicorn

from backend.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.app_env == "development",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
