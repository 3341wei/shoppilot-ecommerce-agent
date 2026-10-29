# -*- coding: utf-8 -*-
"""索引重建 CLI。

    python -m backend.services.ingest

未配置 SILICONFLOW_API_KEY 时会跳过向量索引，检索自动降级为 BM25。
"""
from __future__ import annotations

import json

from backend.core.logging import configure_logging
from backend.services.knowledge import build_index, index_stats


def main() -> int:
    configure_logging("INFO", "text")
    result = build_index()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(index_stats(), ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"ok", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
