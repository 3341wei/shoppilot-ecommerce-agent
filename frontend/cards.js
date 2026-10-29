// 富卡片渲染。全部使用 DOM API + textContent，不允许 innerHTML，避免 XSS。

export function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = String(text);
  return node;
}

const money = (value) => `¥${Number(value || 0).toFixed(2)}`;

function badge(text, tone = "") {
  return el("span", `badge ${tone}`.trim(), text);
}

function kv(label, value) {
  const row = el("div", "kv");
  row.append(el("span", "kv-label", label), el("span", "kv-value", value));
  return row;
}

function productCard(product) {
  const card = el("article", "card product-card");
  card.append(el("div", "product-emoji", product.image || "🛍️"));

  const body = el("div", "product-body");
  body.append(el("div", "product-title", product.title));
  body.append(el("div", "product-meta", `${product.category} · ${product.brand || "自营"}`));

  const price = el("div", "product-price");
  price.append(el("strong", "", money(product.price)));
  if (Number(product.original_price) > Number(product.price)) {
    price.append(el("s", "", money(product.original_price)));
  }
  body.append(price);

  const tags = el("div", "product-tags");
  (product.tags || []).slice(0, 4).forEach((tag) => tags.append(el("span", "tag", tag)));
  body.append(tags);

  const foot = el("div", "product-foot");
  foot.append(el("span", "muted", `⭐ ${product.rating} · 已售 ${product.sales_total}`));
  foot.append(
    badge(
      product.in_stock ? `有货 ${product.stock}` : "缺货",
      product.in_stock ? "ok" : "danger"
    )
  );
  body.append(foot);
  card.append(body);
  return card;
}

function renderProducts(data, title = "商品推荐") {
  const card = el("div", "card");
  card.append(el("div", "card-title", `${title}（${(data.products || []).length}）`));
  if (!data.products || !data.products.length) {
    card.append(el("p", "muted", "没有找到符合条件的商品。"));
    return card;
  }
  const grid = el("div", "product-grid");
  data.products.forEach((product) => grid.append(productCard(product)));
  card.append(grid);
  return card;
}

function renderProduct(data) {
  const product = data.product || {};
  const card = renderProducts({ products: [product] }, "商品详情");
  const attrs = product.attributes || {};
  const list = el("div", "attr-list");
  Object.entries(attrs).forEach(([key, value]) =>
    list.append(kv(key, String(value)))
  );
  if (Object.keys(attrs).length) card.append(list);
  if (product.sku_summary) card.append(kv("规格", product.sku_summary));
  return card;
}

function renderStock(data) {
  const product = data.product || {};
  const inventory = data.inventory || {};
  const card = el("div", "card");
  card.append(el("div", "card-title", "库存查询"));
  const row = el("div", "stock-row");
  row.append(el("span", "product-emoji small", product.image || "📦"));
  const info = el("div", "stock-info");
  info.append(el("div", "product-title", product.title));
  info.append(
    el(
      "div",
      "muted",
      `当前库存 ${inventory.stock} 件 · 近 7 日销量 ${inventory.sales_7d} · 安全库存 ${inventory.safety_stock}`
    )
  );
  row.append(info);
  row.append(
    badge(
      inventory.label || "—",
      ["out", "critical"].includes(inventory.level) ? "danger" : inventory.level === "warning" ? "warn" : ""
    )
  );
  card.append(row);
  if (inventory.suggested_replenish) {
    card.append(el("p", "hint-line", `建议补货约 ${inventory.suggested_replenish} 件（覆盖两周销量）。`));
  }
  return card;
}

function renderPrice(data) {
  const card = el("div", "card price-card");
  card.append(el("div", "card-title", `到手价试算 · ${data.title || ""}`));
  card.append(kv(`商品小计 × ${data.qty || 1}`, money(data.subtotal)));
  (data.applied || []).forEach((item) => {
    const row = kv(item.name, `−${money(item.amount)}`);
    row.classList.add("discount");
    card.append(row);
  });
  const total = el("div", "price-total");
  total.append(el("span", "", "到手价"), el("strong", "", money(data.best_price)));
  card.append(total);
  if (Number(data.total_discount) > 0) {
    card.append(el("div", "muted", `已省 ${money(data.total_discount)}`));
  }
  if (data.unavailable && data.unavailable.length) {
    card.append(
      el(
        "div",
        "muted tiny",
        "未使用：" + data.unavailable.map((c) => `${c.name}（${c.reason}）`).join("；")
      )
    );
  }
  return card;
}

const STATUS_TONE = {
  pending_payment: "warn",
  paid: "",
  shipped: "",
  signed: "ok",
  completed: "ok",
  refunding: "warn",
  cancelled: "danger",
};

function renderOrder(data) {
  const order = data.order || {};
  const card = el("div", "card order-card");
  const head = el("div", "card-head");
  head.append(el("div", "card-title", `订单 ${order.order_id}`));
  head.append(badge(order.status_label || order.status, STATUS_TONE[order.status] || ""));
  card.append(head);

  const items = el("div", "order-items");
  (order.items || []).forEach((item) => {
    const row = el("div", "order-item");
    row.append(el("span", "", `${item.title} × ${item.qty}`));
    row.append(el("span", "muted", money(item.price)));
    items.append(row);
  });
  card.append(items);

  card.append(kv("实付金额", money(order.amount)));
  card.append(kv("收货人", `${order.receiver} · ${order.phone}`));
  card.append(kv("收货地址", order.address));
  card.append(kv("下单时间", order.created_at));
  if (order.signed_at) card.append(kv("签收时间", order.signed_at));
  if (order.advice) card.append(el("p", "hint-line", order.advice));
  return card;
}

function renderLogistics(data) {
  const card = el("div", "card");
  const head = el("div", "card-head");
  head.append(el("div", "card-title", "物流轨迹"));
  if (data.company) head.append(badge(`${data.company} ${data.tracking_no || ""}`, ""));
  card.append(head);

  if (data.is_stalled) {
    card.append(
      el(
        "div",
        "alert danger",
        `物流已停滞约 ${Math.round(data.stalled_hours)} 小时（超过 48 小时），建议联系承运商核实。`
      )
    );
  }

  const timeline = el("ol", "timeline");
  (data.events || []).forEach((event, index) => {
    const item = el("li", index === 0 ? "timeline-item active" : "timeline-item");
    item.append(el("span", "timeline-dot"));
    const body = el("div", "timeline-body");
    body.append(el("div", "timeline-title", event.status));
    body.append(el("div", "timeline-desc", event.description));
    body.append(el("div", "timeline-time", event.time));
    item.append(body);
    timeline.append(item);
  });
  if (!data.events || !data.events.length) {
    timeline.append(el("li", "muted", "暂无物流记录"));
  }
  card.append(timeline);
  return card;
}

function renderEligibility(data) {
  const card = el("div", "card");
  const banner = el("div", `alert ${data.eligible ? "ok" : "danger"}`);
  banner.textContent = `${data.eligible ? "可以申请" : "暂不支持"}：${data.type || "—"}`;
  card.append(banner);
  if (data.product_title) {
    card.append(el("div", "card-title", `${data.product_title} · 签收 ${data.days_since_signed} 天`));
  }
  const reasons = el("ul", "reason-list");
  (data.reasons || []).forEach((reason) => reasons.append(el("li", "", reason)));
  card.append(reasons);
  if (data.alternatives && data.alternatives.length) {
    card.append(el("div", "sub-title", "替代方案"));
    const alts = el("ul", "reason-list muted");
    data.alternatives.forEach((item) => alts.append(el("li", "", item)));
    card.append(alts);
  }
  if (data.policy_refs && data.policy_refs.length) {
    card.append(el("div", "policy-refs", `政策依据：${data.policy_refs.join("；")}`));
  }
  return card;
}

function renderSourcesCard(data) {
  const card = el("div", "card sources-card");
  card.append(el("div", "card-title", "参考来源"));
  const items = data.items || [];
  if (!items.length) {
    card.append(el("p", "muted", "政策库未覆盖该问题。"));
    return card;
  }
  items.forEach((item) => {
    const details = el("details", "source-item");
    details.append(el("summary", "", item.title || item.source || "来源"));
    details.append(el("p", "", item.snippet || ""));
    card.append(details);
  });
  return card;
}

function renderPending(data, ctx) {
  const card = el("div", "card confirm-card");
  card.append(el("div", "confirm-title", "⚠️ 需要你确认"));
  card.append(el("p", "confirm-summary", data.summary || "确认执行该操作？"));

  const meta = el("div", "confirm-meta");
  if (data.order_id) meta.append(el("span", "", `订单 ${data.order_id}`));
  if (data.ticket_type) meta.append(el("span", "", `类型 ${data.ticket_type}`));
  if (data.expires_at) {
    const seconds = Math.max(0, Math.floor(data.expires_at - Date.now() / 1000));
    const countdown = el("span", "countdown", `${seconds} 秒后失效`);
    meta.append(countdown);
    const timer = setInterval(() => {
      const left = Math.max(0, Math.floor(data.expires_at - Date.now() / 1000));
      countdown.textContent = left > 0 ? `${left} 秒后失效` : "已失效";
      if (left <= 0) {
        clearInterval(timer);
        card.querySelectorAll("button").forEach((button) => (button.disabled = true));
      }
    }, 1000);
  }
  card.append(meta);

  const actions = el("div", "confirm-actions");
  const confirm = el("button", "btn primary", "确认创建");
  const cancel = el("button", "btn ghost", "取消");
  actions.append(confirm, cancel);
  card.append(actions);

  confirm.addEventListener("click", async () => {
    confirm.disabled = true;
    cancel.disabled = true;
    confirm.textContent = "处理中…";
    try {
      const result = await ctx.confirmAction(data.token);
      actions.remove();
      card.querySelector(".confirm-title").textContent = "✅ 工单已创建";
      card.append(
        el("p", "confirm-summary", result.message || `工单号：${result.ticket_id}`)
      );
      card.append(el("div", "confirm-meta", `工单号 ${result.ticket_id} · 状态 ${result.state}`));
    } catch (error) {
      confirm.disabled = false;
      cancel.disabled = false;
      confirm.textContent = "确认创建";
      card.append(el("div", "alert danger", error.message || "确认失败，请重试"));
    }
  });

  cancel.addEventListener("click", async () => {
    confirm.disabled = true;
    cancel.disabled = true;
    try {
      await ctx.cancelAction(data.token);
      actions.remove();
      card.querySelector(".confirm-title").textContent = "已取消";
      card.append(el("p", "muted", "该确认单已作废，未产生业务数据。"));
    } catch (error) {
      card.append(el("div", "alert danger", error.message || "取消失败"));
    }
  });

  return card;
}

function renderHandoff(data) {
  const card = el("div", "card");
  card.append(el("div", "card-title", "已转人工客服"));
  card.append(el("p", "", data.message || ""));
  card.append(el("div", "muted tiny", `工单号：${data.handoff_id || "—"}`));
  return card;
}

function renderMetrics(data) {
  const card = el("div", "card");
  card.append(
    el("div", "card-title", `销售总览 · ${data.start} ~ ${data.end}`)
  );
  const tiles = el("div", "metric-grid");
  const changes = data.changes || {};
  const items = [
    ["GMV", money(data.gmv), changes.gmv_pct],
    ["已付款订单", data.paid_orders, changes.orders_pct],
    ["客单价", money(data.aov), changes.aov_pct],
    ["退款率", `${Number(data.refund_rate).toFixed(2)}%`, changes.refund_rate_pp, "pp"],
  ];
  items.forEach(([label, value, change, unit]) => {
    const tile = el("div", "metric-tile");
    tile.append(el("span", "metric-label", label));
    tile.append(el("strong", "metric-value", value));
    if (change !== undefined && change !== null) {
      const suffix = unit === "pp" ? "pp" : "%";
      // 退款率上升是负面信号，颜色需要与其他指标相反
      const isGood = unit === "pp" ? Number(change) <= 0 : Number(change) >= 0;
      tile.append(
        el(
          "span",
          `metric-change ${isGood ? "up" : "down"}`,
          `${Number(change) > 0 ? "+" : ""}${change}${suffix}`
        )
      );
    }
    tiles.append(tile);
  });
  card.append(tiles);

  if (data.categories && data.categories.length) {
    card.append(el("div", "sub-title", "类目销售占比（按商品金额）"));
    data.categories.forEach((category) => {
      const row = el("div", "bar-row");
      row.append(el("span", "bar-label", category.category));
      const track = el("div", "bar-track");
      const fill = el("div", "bar-fill");
      fill.style.width = `${Math.max(2, category.share)}%`;
      track.append(fill);
      row.append(track);
      row.append(el("span", "bar-value", `${category.share}%`));
      card.append(row);
    });
  }
  card.append(el("p", "muted tiny", data.note || ""));
  return card;
}

function renderInventory(data) {
  const card = el("div", "card");
  card.append(el("div", "card-title", `库存预警 · ${data.alert_count} 个商品`));
  if (!data.alerts || !data.alerts.length) {
    card.append(el("p", "ok-text", "全部商品库存正常。"));
    return card;
  }
  const table = el("div", "inventory-list");
  data.alerts.forEach((item) => {
    const row = el("div", "inventory-row");
    const main = el("div", "inventory-main");
    main.append(el("span", "inventory-name", `${item.product_id} ${item.title}`));
    main.append(
      el(
        "span",
        "muted tiny",
        `库存 ${item.stock} · 周销 ${item.sales_7d} · 安全库存 ${item.safety_stock}`
      )
    );
    row.append(main);
    row.append(
      badge(
        item.label,
        ["out", "critical"].includes(item.level) ? "danger" : item.level === "warning" ? "warn" : ""
      )
    );
    if (item.suggested_replenish) {
      row.append(el("span", "replenish", `补 ${item.suggested_replenish}`));
    }
    table.append(row);
  });
  card.append(table);
  card.append(el("p", "muted tiny", data.note || ""));
  return card;
}

export function renderArtifact(container, artifact, ctx) {
  if (!artifact || !artifact.card_type) return;
  const data = artifact.data || {};
  let node = null;
  switch (artifact.card_type) {
    case "products":
      node = renderProducts(data);
      break;
    case "product":
      node = renderProduct(data);
      break;
    case "stock":
      node = renderStock(data);
      break;
    case "price":
      node = renderPrice(data);
      break;
    case "order":
      node = renderOrder(data);
      break;
    case "logistics":
      node = renderLogistics(data);
      break;
    case "eligibility":
      node = renderEligibility(data);
      break;
    case "sources":
      node = renderSourcesCard(data);
      break;
    case "pending_action":
      node = renderPending(data, ctx);
      break;
    case "handoff":
      node = renderHandoff(data);
      break;
    case "metrics":
      node = renderMetrics(data);
      break;
    case "inventory":
      node = renderInventory(data);
      break;
    default:
      return;
  }
  if (node) container.append(node);
}

export function renderSources(container, sources) {
  if (!sources || !sources.length) return;
  const box = el("div", "answer-sources");
  box.append(el("span", "sources-label", "来源"));
  const list = el("div", "source-chips");
  const seen = new Set();
  sources.forEach((source) => {
    const key = `${source.source}|${source.title}`;
    if (seen.has(key)) return;
    seen.add(key);
    const chip = el("span", "source-chip", source.title || source.source || "来源");
    chip.title = source.snippet || "";
    list.append(chip);
  });
  box.append(list);
  container.append(box);
}
