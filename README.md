# ShopPilot · 电商业务 Agent 智能体

> **FastAPI + LangChain 1.x + LangGraph + SQLite/ChromaDB** 的电商业务智能体。
> 一个 Agent 贯通 **售前导购 → 订单物流 → 售后处理 → 运营分析**，
> 内置可复现的演示数据，不需要对接真实电商平台。

**当前状态：可运行 MVP（速通版）** —— 后端、前端、测试均已完成，
`pytest` 42 项离线测试通过，`ruff check` 无告警。

---

## 1. 已实现能力

| 角色 | 场景 | Agent 做的事 |
|---|---|---|
| 买家 | 售前导购 | 自然语言 + 类目/价格/库存过滤检索商品 → 商品卡片 → 组合优惠券试算到手价 |
| 买家 | 订单物流 | 校验订单归属 → 查订单/物流 → 自动识别停滞超过 48 小时 |
| 买家 | 售后处理 | 检索政策 → 规则引擎判定退换/维修资格 → 生成工单确认单 → 用户确认后落库 |
| 买家 | 转人工 | 政策未覆盖或用户要求时，生成转人工记录并写审计日志 |
| 运营 | 销售分析 | GMV、已付款订单、客单价、退款率、类目占比，附环比与指标口径 |
| 运营 | 库存预警 | 断货/紧急/紧张/滞销分级，按近 7 日销量计算安全库存与补货建议 |

角色决定**工具集**和**系统提示词**：买家无法调用运营工具，订单归属在服务层二次校验。

---

## 2. 快速开始

要求 Python 3.11+。

```bash
# 1. 安装依赖（建议独立虚拟环境）
pip install -r requirements.txt

# 2. 配置密钥：至少填 DEEPSEEK_API_KEY
cp .env.example .env

# 3. 初始化演示数据库（可重复执行）
python scripts/seed_db.py

# 4. 启动
python run.py
```

打开 <http://127.0.0.1:8000>，右上角切换「买家 / 运营」。
接口文档：<http://127.0.0.1:8000/docs>。

**可选配置：**

- `SILICONFLOW_API_KEY`：启用向量检索与 Rerank；不填自动降级为纯 BM25，项目仍可运行。
- `API_KEYS`：启用 `X-API-Key` 鉴权；开发环境留空即跳过。
- `python -m backend.services.ingest`：重建商品/政策向量索引（需 Embedding Key）。

**没有 LLM Key 时：** 页面、健康检查、检索、规则引擎都可正常验证；
调用 `/api/agent` 会返回 503 并提示补齐 `DEEPSEEK_API_KEY`。

### 演示数据说明

仓库里的商品、订单、用户均为**手工构造的脱敏样例**，不包含任何真实用户信息，也不依赖外部电商平台。

- 默认 `python scripts/seed_db.py` 灌入 16 个商品、8 笔订单、5 份政策；
- 8 笔订单不是随机数据，而是按剧本设计，分别覆盖：七天无理由、超期退货、物流停滞、待付款、退款中、跨用户越权、特殊商品已拆封/未拆封；
- 种子日期以 2026-10-29 为基准日，灌库时整体平移到运行当天，所以「最近 30 天」「签收 3 天/19 天」「物流停滞 3 天」等剧本不会随时间失效；
- 需要更大数据量时执行 `python scripts/generate_demo_data.py --count 240`：保留 8 笔剧本订单，额外生成 240 笔订单（固定随机种子、可复现），让运营指标和图表更接近真实规模；
- 生产接入时替换 `data/seed` 与服务层的数据访问即可，工具和 Agent 层不变。

---

## 3. 演示剧本

用默认身份 `u_buyer_001`（买家）或 `u_ops_001`（运营）逐条提问即可。

| # | 问题 | 预期表现 |
|---|---|---|
| S1 | 预算 500 以内，给刚开始跑步的人推荐双跑鞋，有满减吗？ | 返回 P2001/P2002 商品卡；P2001 到手价 ¥339（满 300 减 40 + 新人 20） |
| S2 | 订单 SO20261001003 到哪了？物流怎么不动了？ | 物流时间轴，并提示已停滞超过 48 小时 |
| S3 | 订单 SO20261001001 的耳机拆封了，还能退吗？ | 签收 19 天 + 特殊商品已拆封 → 不支持无理由退货，给出保修维修替代方案 |
| S4 | 订单 SO20261001008 的耳机能退吗？帮我建退货工单 | 未说明拆封 → 按未拆封判定，签收 3 天符合七天无理由 → 返回工单确认卡，**点击确认后才落库** |
| S5 | 查一下订单 SO20261001006 | 该订单属于 `u_buyer_002`，工具返回越权，模型转述“无权查看”且不泄露订单信息 |
| S6 | 最近 30 天的 GMV、客单价和退款率怎么样？ | 指标卡：GMV、订单数、客单价、退款率、类目占比，附环比与口径说明 |
| S7 | 现在有哪些商品库存告急？ | 5 个预警商品：P1003/P2006 断货、P1006/P1004 紧急、P3003 滞销 |

> 默认 8 笔剧本订单时，S6 为 GMV ¥2483、7 单、客单价 ¥354.71、退款率 14.29%。
> 执行 `generate_demo_data.py` 扩大数据量后指标会变化，以工具实时返回为准。

确认单机制可以额外验证：

- 重复点击确认 → 幂等返回同一工单号，不重复落库；
- 换一个 `X-Session-Id` 或用户确认 → 403；
- 超过 5 分钟 → 失效，需重新发起。

---

## 4. 架构

```text
浏览器（原生 HTML/CSS/JS）
  │  POST /api/agent/stream（SSE: tool → tool_result → token → sources → done）
  ▼
FastAPI（请求上下文 / 限流 / 安全头 / 统一错误体）
  │
  ├─ Agent 服务：create_agent + MemorySaver（按 user_id:session_id 隔离记忆）
  │     └─ 每请求按角色装配工具闭包（注入 Identity）
  │
  ├─ 工具层（14 个工具）
  │     ├─ 商品域：混合检索 / 详情 / 库存 / 到手价
  │     ├─ 订单域：订单 / 物流（服务层校验归属）
  │     ├─ 售后域：政策检索 / 资格判定 / 工单确认单 / 转人工
  │     └─ 运营域：销售指标 / 库存预警
  │
  ├─ 业务服务：catalog / orders / promotions / after_sales / analytics
  ├─ 规则引擎（纯函数）：best_price / check_return_eligibility / inventory_status
  ├─ 确认单：token + TTL + 会话绑定 + 幂等 + 审计
  │
  ├─ SQLite（业务唯一事实源）
  └─ ChromaDB（商品/政策双 collection，可选；缺失时 BM25 降级）
```

### 工具矩阵

| 工具 | 买家 | 运营 | 说明 |
|---|:---:|:---:|---|
| `search_products` | ✓ | ✓ | 结构化过滤 + BM25/向量 + RRF + Rerank |
| `get_product_detail` | ✓ | ✓ | 商品参数与库存 |
| `check_stock` | ✓ | ✓ | 库存分级与补货建议 |
| `calc_best_price` | ✓ | ✓ | 枚举优惠组合，取最低实付 |
| `get_order` | ✓ | | 订单归属校验 + PII 脱敏 |
| `track_logistics` | ✓ | | 物流轨迹 + 停滞判断 |
| `search_after_sales_policy` | ✓ | | 政策库检索，回答必须引用来源 |
| `check_return_eligibility` | ✓ | | 7 天无理由 / 15 天质量问题 / 365 天保修 |
| `create_after_sales_ticket` | ✓ | | 只生成确认单，确认后才写库 |
| `handoff_to_human` | ✓ | | 转人工 + 审计 |
| `get_sales_overview` | | ✓ | 销售指标与环比 |
| `get_inventory_alerts` | | ✓ | 库存预警 |
| `calculator` | ✓ | ✓ | 安全表达式计算 |
| `get_current_time` | ✓ | ✓ | 相对时间换算基准 |

---

## 5. 关键设计

### 5.1 写操作确认单

模型不能直接创建工单。`create_after_sales_ticket` 先校验业务前提，再签发一次性 token：

```text
工具 → issue(token, ttl=300s, 绑定 user_id + session_id)
     → 前端确认卡（倒计时）
     → POST /api/actions/{token}/confirm
     → 再次校验身份/归属 → 执行器写 tickets + audit_logs（同一事务）
```

重复确认返回同一结果（幂等）；换用户/换会话返回 403；过期返回 400。

### 5.2 规则交给代码，表达交给模型

到手价、退换资格、库存预警都是可复现的纯函数，LLM 只负责理解意图和组织语言。
例如退换判定同时考虑：订单状态、签收天数、是否质量问题、是否特殊商品、是否已拆封。

### 5.3 权限不在提示词里

- 工具按角色装配，买家工具列表里没有运营工具；
- 订单归属在 `orders.get_order` 校验，工具参数不接收 `user_id`，由闭包注入；
- PII（姓名/手机号/地址）在服务层脱敏后再交给模型和前端；
- 越权、订单不存在等**可预期业务异常**会包装成 `ToolMessage` 交还模型，由模型如实解释，不会中断整条 SSE 流。

### 5.4 检索降级

有 `SILICONFLOW_API_KEY` 时走「SQL 硬过滤 → BM25 + 向量 → RRF → Rerank」；
没有 Key 时只用 BM25，并通过最低分比例过滤掉弱相关商品。

### 5.5 SSE 事件协议

`tool`（开始调用）→ `tool_result`（富卡片 artifact）→ 可能需要 `reset`（工具轮次的中间文本）
→ `token`（最终回答增量）→ `sources`（引用来源）→ `done`。
前端用 `fetch + ReadableStream` 解析，原生 JS，无构建步骤，零 `innerHTML`。

---

## 6. API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/agent` | 非流式问答 |
| POST | `/api/agent/stream` | SSE 流式问答 |
| DELETE | `/api/agent/session/{session_id}` | 清空会话记忆 |
| POST | `/api/actions/{token}/confirm` | 确认并执行写操作 |
| POST | `/api/actions/{token}/cancel` | 取消确认单 |
| POST | `/api/ingest` | 重建向量索引（需 Embedding Key） |
| GET | `/api/stats` | 索引与数据统计 |
| GET | `/api/meta` | 可安全暴露的配置摘要 |
| GET | `/healthz` / `/readyz` | 存活 / 就绪探针 |

身份头（演示用）：`X-User-Role`、`X-User-Id`、`X-Session-Id`；鉴权头：`X-API-Key`。
生产环境应关闭 `DEMO_ROLE_HEADER_ENABLED` 并接入 JWT。

---

## 7. 测试与质量

```bash
pytest -q          # 42 项，全部离线，不需要真实 Key
ruff check .       # 静态检查
```

覆盖范围：

- Agent 编排：脚本化假模型验证「工具调用 → 富卡片 → 回答」链路与角色工具隔离；
- 规则引擎：优惠券门槛/互斥/叠加、退换资格分支、库存分级；
- 确认单：归属校验、TTL、幂等、取消、未知 token；
- 服务层：PII 脱敏、越权拦截、优惠试算、BM25 检索、政策召回、运营指标；
- 数据生成：模拟订单的状态、时间、物流轨迹一致性，固定种子可复现；
- 接口层：健康检查、统一错误体、静态页面、确认/取消流程、会话校验。

---

## 8. 目录结构

```text
backend/
  api/          # 路由：agent / actions / admin / health / SSE
  core/         # 配置、错误、日志、中间件、限流、脱敏
  services/     # 业务服务、规则引擎、检索、Agent、确认单
  tools/        # 按角色装配的 LangChain 工具
frontend/       # 原生前端：app.js / cards.js / index.html / styles.css
data/
  seed/         # 商品、订单、物流、优惠券固定种子数据
  policies/     # 5 份平台政策 Markdown
scripts/seed_db.py
scripts/generate_demo_data.py  # 可选：生成 200+ 笔模拟订单
tests/          # pytest 离线测试
docs/           # 完整版规划：大纲、功能清单、路线图
```

---

## 9. 与完整规划的关系 / 已知限制

`docs/OUTLINE.md`、`docs/FEATURES.md`、`docs/ROADMAP.md` 是最初的**完整版规划**
（24 商品、12 订单、19 工具、运营看板等）。当前仓库按「速通版」实现：

- 保留：买家业务闭环、写操作确认制、角色工具隔离、混合检索、流式 + 富卡片、离线测试；
- 暂缓：运营看板页面、商品对比/推荐、Docker/CI、多租户、JWT、会话摘要、评测脚本。

已知限制：

- Agent 记忆和确认单 token 都在进程内，因此服务以**单 worker**运行，重启后丢失；
- 演示身份使用请求头，仅用于本地展示，不能直接用于生产；
- 未实现真实支付/退款、真实物流接口，全部基于种子数据。

后续可优化方向（按性价比排序）：
运营看板 → Agent 评测集 → Docker/CI → JWT 登录 → 会话摘要与长期记忆。

---

## 10. 简历亮点

- **不是套壳 RAG**：检索只是工具之一，核心是业务工具编排 + 规则引擎 + 可审计写操作；
- **确认单机制**：TTL + 会话绑定 + 一次性 + 幂等 + 审计，能讲清“为什么不让模型直接退款”；
- **角色级工具隔离**：同一 Agent 按角色装配工具与提示词，服务层再做归属校验；
- **确定性计算与 LLM 分工**：价格、资格、库存用纯函数，LLM 只做意图理解与表达；
- **检索可降级**：向量 + BM25 + RRF + Rerank，无 Embedding Key 时纯 BM25 仍可运行；
- **完整可演示闭环**：16 个商品、8 笔剧本订单（可一键扩展到 248+）、5 份政策，七个剧本从导购走到售后与运营。
