// ShopPilot 前端：会话管理、SSE 流式、富卡片、写操作确认。
import { renderArtifact, renderSources, el } from "./cards.js";

const $ = (id) => document.getElementById(id);

const chat = $("chat");
const input = $("question");
const sendBtn = $("sendBtn");
const stopBtn = $("stopBtn");
const statusText = $("statusText");
const statusDot = $("statusDot");

const TOOL_LABELS = {
  search_products: "搜索商品",
  get_product_detail: "查看商品",
  check_stock: "查询库存",
  calc_best_price: "试算到手价",
  get_order: "查询订单",
  track_logistics: "查询物流",
  search_after_sales_policy: "检索售后政策",
  check_return_eligibility: "判定售后资格",
  create_after_sales_ticket: "生成工单确认单",
  handoff_to_human: "转人工",
  get_sales_overview: "查询销售指标",
  get_inventory_alerts: "查询库存预警",
  calculator: "计算",
  get_current_time: "获取当前时间",
};

const SUGGESTIONS = {
  buyer: [
    "预算 500 以内，给刚开始跑步的人推荐双跑鞋，有满减吗？",
    "订单 SO20261001003 到哪了？物流怎么不动了？",
    "两周前买的降噪耳机拆封了，还能退吗？",
    "订单 SO20261001002 的跑鞋能退吗？",
  ],
  operator: [
    "最近 30 天的 GMV、客单价和退款率怎么样？",
    "上周退款率为什么涨了？哪个类目拖后腿？",
    "现在有哪些商品库存告急？需要补多少？",
    "给我看看各品类的销售占比。",
  ],
};

const DEFAULT_USERS = { buyer: "u_buyer_001", operator: "u_ops_001" };

const state = {
  apiKey: sessionStorage.getItem("shop_api_key") || "",
  role: sessionStorage.getItem("shop_role") || "buyer",
  userId: sessionStorage.getItem("shop_user_id") || "",
  sessionId: newSessionId(),
  controller: null,
  streaming: false,
};

function newSessionId() {
  return `s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function currentUserId() {
  return state.userId || DEFAULT_USERS[state.role] || DEFAULT_USERS.buyer;
}

function headers(extra = {}) {
  const result = {
    "X-User-Role": state.role,
    "X-User-Id": currentUserId(),
    "X-Session-Id": state.sessionId,
    ...extra,
  };
  if (state.apiKey) result["X-API-Key"] = state.apiKey;
  return result;
}

function errorMessage(payload, fallback = "请求失败") {
  return payload?.error?.message || fallback;
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: headers(options.headers || {}),
  });
  if (!response.ok) {
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      // 非 JSON 错误体
    }
    throw new Error(errorMessage(payload, `请求失败（${response.status}）`));
  }
  return response;
}

// ---------------- 消息渲染 ----------------

function scrollToBottom(force = false) {
  const nearBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 160;
  if (force || nearBottom) chat.scrollTop = chat.scrollHeight;
}

function appendUserMessage(text) {
  const row = el("div", "msg user");
  const bubble = el("div", "bubble");
  bubble.append(el("p", "answer", text));
  row.append(bubble);
  chat.append(row);
  scrollToBottom(true);
}

function createAssistantMessage() {
  const row = el("div", "msg assistant");
  const avatar = el("div", "avatar", "🤖");
  const bubble = el("div", "bubble");

  const trace = el("div", "tool-trace hidden");
  const traceLabel = el("span", "trace-label", "工具调用");
  const chips = el("div", "trace-chips");
  trace.append(traceLabel, chips);

  const answer = el("div", "answer");
  const cards = el("div", "cards");
  const sources = el("div", "sources");
  const typing = el("div", "typing", "正在思考…");

  bubble.append(trace, answer, cards, sources, typing);
  row.append(avatar, bubble);
  chat.append(row);
  scrollToBottom(true);

  const chipMap = new Map();

  return {
    node: row,
    answer,
    cards,
    sources,
    addTool(name) {
      trace.classList.remove("hidden");
      let chip = chipMap.get(name);
      if (!chip) {
        chip = el("span", "trace-chip running", `⏳ ${TOOL_LABELS[name] || name}`);
        chipMap.set(name, chip);
        chips.append(chip);
      }
      scrollToBottom();
    },
    finishTool(name) {
      const chip = chipMap.get(name);
      if (chip) {
        chip.classList.remove("running");
        chip.textContent = `✓ ${TOOL_LABELS[name] || name}`;
      }
    },
    reset() {
      answer.textContent = "";
      // 新一轮工具调用期间恢复“思考中”提示
      if (!bubble.contains(typing)) bubble.append(typing);
    },
    appendToken(text) {
      typing.remove();
      answer.textContent += text;
      scrollToBottom();
    },
    addCard(artifact) {
      typing.remove();
      renderArtifact(cards, artifact, { confirmAction, cancelAction });
      scrollToBottom();
    },
    addSources(list) {
      renderSources(sources, list);
      scrollToBottom();
    },
    finish(finalText = "") {
      typing.remove();
      if (finalText && !answer.textContent.trim()) answer.textContent = finalText;
      if (!answer.textContent.trim() && !cards.children.length) {
        answer.textContent = "（本轮没有生成内容，请重试或换个问法）";
      }
      scrollToBottom();
    },
    error(message) {
      typing.remove();
      bubble.append(el("div", "alert danger", message));
      scrollToBottom();
    },
    stopped() {
      typing.remove();
      if (!answer.textContent.trim()) answer.textContent = "（已停止生成）";
      else answer.textContent += "\n（已停止生成）";
    },
  };
}

// ---------------- SSE ----------------

function parseSSEBlock(block) {
  let event = "message";
  const dataLines = [];
  block.split("\n").forEach((line) => {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  });
  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

async function streamAgent(question, assistant) {
  state.controller = new AbortController();
  const response = await apiFetch("/api/agent/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: state.sessionId }),
    signal: state.controller.signal,
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalText = "";
  let failed = false;

  const handle = ({ event, data }) => {
    if (event === "tool") assistant.addTool(data.name);
    else if (event === "tool_result") {
      assistant.finishTool(data.name);
      assistant.addCard(data);
    } else if (event === "reset") assistant.reset();
    else if (event === "token") assistant.appendToken(data.text || "");
    else if (event === "sources") assistant.addSources(data.sources || []);
    else if (event === "done") finalText = data.answer || "";
    else if (event === "error") {
      failed = true;
      assistant.error(data.message || "生成失败");
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const parsed = parseSSEBlock(block);
      if (parsed) handle(parsed);
    }
  }
  if (buffer.trim()) {
    const parsed = parseSSEBlock(buffer);
    if (parsed) handle(parsed);
  }
  if (!failed) assistant.finish(finalText);
}

// ---------------- 发送 / 停止 ----------------

function setStreaming(value) {
  state.streaming = value;
  sendBtn.disabled = value;
  stopBtn.classList.toggle("hidden", !value);
  input.disabled = value;
  if (!value) input.focus();
}

async function sendQuestion(text) {
  const question = (text ?? input.value).trim();
  if (!question || state.streaming) return;

  hideWelcome();
  appendUserMessage(question);
  input.value = "";
  input.style.height = "auto";
  setStreaming(true);
  const assistant = createAssistantMessage();

  try {
    await streamAgent(question, assistant);
  } catch (error) {
    if (error.name === "AbortError") assistant.stopped();
    else assistant.error(error.message || "网络错误，请稍后重试");
  } finally {
    state.controller = null;
    setStreaming(false);
  }
}

function stopGeneration() {
  if (state.controller) state.controller.abort();
}

// ---------------- 确认操作 ----------------

async function confirmAction(token) {
  const response = await apiFetch(`/api/actions/${token}/confirm`, { method: "POST" });
  return response.json();
}

async function cancelAction(token) {
  const response = await apiFetch(`/api/actions/${token}/cancel`, { method: "POST" });
  return response.json();
}

// ---------------- 欢迎页 ----------------

function hideWelcome() {
  const welcome = $("welcome");
  if (welcome) welcome.remove();
}

function renderWelcome() {
  hideWelcome();
  const welcome = el("div", "welcome");
  welcome.id = "welcome";
  welcome.append(el("div", "welcome-icon", "🛍️"));
  welcome.append(el("h2", "", state.role === "buyer" ? "今天想买点什么？" : "先看哪组数据？"));
  welcome.append(
    el(
      "p",
      "muted",
      state.role === "buyer"
        ? "找商品、查订单、看物流、判断能不能退——都可以直接问。"
        : "销售指标、退款率、库存预警——结论和数据一起给。"
    )
  );
  const chips = el("div", "suggestion-list");
  SUGGESTIONS[state.role].forEach((suggestion) => {
    const button = el("button", "suggestion", suggestion);
    button.type = "button";
    button.addEventListener("click", () => sendQuestion(suggestion));
    chips.append(button);
  });
  welcome.append(chips);
  chat.append(welcome);
}

// ---------------- 状态 / 会话 ----------------

async function refreshStatus() {
  statusText.textContent = "检查服务状态…";
  statusDot.className = "status-dot";
  try {
    const response = await fetch("/readyz");
    const data = await response.json();
    if (response.ok) {
      const index = data.checks?.index || {};
      const mode = index.embedding_enabled
        ? `向量 + BM25 · 商品 ${index.shop_products || 0} · 政策 ${index.shop_policies || 0}`
        : `BM25（未建向量索引）· 政策切片 ${index.policy_chunks || 0} 条`;
      statusDot.classList.add("ok");
      statusText.textContent = `服务就绪 · ${mode} · 身份 ${currentUserId()}`;
    } else {
      statusDot.classList.add("error");
      statusText.textContent = data.hint || "服务未就绪";
    }
  } catch {
    statusDot.classList.add("error");
    statusText.textContent = "无法连接服务，请确认后端已启动";
  }
}

async function startNewSession() {
  const oldSession = state.sessionId;
  if (oldSession) {
    fetch(`/api/agent/session/${oldSession}`, {
      method: "DELETE",
      headers: headers(),
    }).catch(() => {});
  }
  state.sessionId = newSessionId();
  chat.textContent = "";
  renderWelcome();
  refreshStatus();
}

function setRole(role) {
  if (!["buyer", "operator"].includes(role)) return;
  if (state.role === role) return;
  state.role = role;
  state.userId = DEFAULT_USERS[role];
  sessionStorage.setItem("shop_role", role);
  sessionStorage.setItem("shop_user_id", state.userId);
  document.querySelectorAll(".role-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.role === role);
  });
  input.placeholder =
    role === "buyer"
      ? "例如：500 以内有什么跑鞋？订单 SO20261001003 到哪了？"
      : "例如：最近 30 天 GMV 和退款率怎么样？";
  startNewSession();
}

// ---------------- 设置 ----------------

function openSettings() {
  $("apiKeyInput").value = state.apiKey;
  $("userIdInput").value = currentUserId();
  $("settingsDialog").showModal();
}

function saveSettings() {
  state.apiKey = $("apiKeyInput").value.trim();
  const userId = $("userIdInput").value.trim();
  sessionStorage.setItem("shop_api_key", state.apiKey);
  if (userId && userId !== currentUserId()) {
    state.userId = userId;
    sessionStorage.setItem("shop_user_id", userId);
    startNewSession();
  }
  refreshStatus();
}

// ---------------- 事件绑定 ----------------

sendBtn.addEventListener("click", () => sendQuestion());
stopBtn.addEventListener("click", stopGeneration);
input.addEventListener("keydown", (event) => {
  // 中文输入法选词时按 Enter 不发送
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendQuestion();
  }
});
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});

$("newSessionBtn").addEventListener("click", startNewSession);
$("settingsBtn").addEventListener("click", openSettings);
$("saveSettingsBtn").addEventListener("click", (event) => {
  event.preventDefault();
  saveSettings();
  $("settingsDialog").close();
});
$("closeSettingsBtn").addEventListener("click", (event) => {
  event.preventDefault();
  $("settingsDialog").close();
});
$("clearKeyBtn").addEventListener("click", (event) => {
  event.preventDefault();
  $("apiKeyInput").value = "";
});

document.querySelectorAll(".role-btn").forEach((button) => {
  button.addEventListener("click", () => setRole(button.dataset.role));
});

// 初始化
document.querySelectorAll(".role-btn").forEach((button) => {
  button.classList.toggle("active", button.dataset.role === state.role);
});
if (!state.userId) state.userId = DEFAULT_USERS[state.role];
input.placeholder =
  state.role === "buyer"
    ? "例如：500 以内有什么跑鞋？订单 SO20261001003 到哪了？"
    : "例如：最近 30 天 GMV 和退款率怎么样？";
renderWelcome();
refreshStatus();
