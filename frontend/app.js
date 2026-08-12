const terminalStates = new Set(["success", "failed", "needs_review", "cancelled"]);
let currentTaskId = "";
let currentConversationId = "";
let pollTimer = null;
let conversationBusy = false;

const $ = (id) => document.getElementById(id);

function pretty(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

function notice(message) {
  $("resultBox").textContent = typeof message === "string" ? message : pretty(message);
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `${response.status} ${response.statusText}`);
  return data;
}

function setConversationBusy(busy) {
  conversationBusy = busy;
  ["createConv", "submitTurn", "finishConv", "refreshHistory"].forEach((id) => {
    if ($(id)) $(id).disabled = busy;
  });
  ["convCreateInput", "convCreateOptions", "convScriptMode", "convInstruction"].forEach((id) => {
    if ($(id)) $(id).disabled = busy;
  });
  if (busy) $("conversationInfo").textContent = "当前任务执行中，请等待完成。";
}

function setBadge(state) {
  $("stateBadge").textContent = state || "idle";
  $("stateBadge").className = `badge ${state || ""}`;
}

function setTurnComposerVisible(visible) {
  $("turnComposer").hidden = !visible;
}

function setTask(status) {
  currentTaskId = status.task_id || currentTaskId;
  $("taskId").textContent = currentTaskId || "-";
  $("createdAt").textContent = status.created_at || "-";
  $("resultBox").textContent = pretty(status.result);
  if (status.result && status.result.script_text) $("scriptBox").textContent = status.result.script_text;
  setBadge(status.state);
  renderFlow(status);
}

function setCurrentRequest(text) {
  $("currentRequest").textContent = text && text.trim() ? text : "暂无请求";
}

function renderFlow(status) {
  const state = status.state || "idle";
  const retries = status.retries || [];
  const hasScript = Boolean(status.result && status.result.script_text && status.result.script_text.trim());
  const steps = [
    ["submit", currentTaskId ? "已提交" : "等待任务"],
    ["generate", hasScript ? "已有脚本" : currentTaskId ? "生成中" : "等待"],
    ["execute", currentTaskId ? "执行/排队" : "等待"],
    ["fix", retries.length ? `${retries.length} 次重试` : "无重试"],
    ["done", terminalStates.has(state) ? state : "等待终态"],
  ];
  let active = currentTaskId ? 1 : 0;
  if (state === "running") active = hasScript ? 2 : 1;
  if (retries.length) active = 3;
  if (terminalStates.has(state)) active = 4;
  steps.forEach(([key, hint], index) => {
    const element = document.querySelector(`.flow-step[data-step="${key}"]`);
    if (!element) return;
    element.querySelector("em").textContent = hint;
    element.classList.remove("waiting", "active", "done", "error");
    if (index < active) element.classList.add("done");
    else if (index === active) element.classList.add(["failed", "needs_review", "cancelled"].includes(state) ? "error" : "active");
    else element.classList.add("waiting");
  });
}

function renderSteps(status) {
  return status;
}

function parseOptions() {
  return $("convCreateOptions").value.split(/\s+/).filter(Boolean);
}

async function createConversation() {
  const text = $("convCreateInput").value.trim();
  if (!text) return notice("请输入初始需求或已有脚本。");
  const payload = { options: parseOptions() };
  if ($("convScriptMode").checked) payload.script = text;
  else payload.prompt = text;
  try {
    setCurrentRequest(text);
    setConversationBusy(true);
    const data = await api("/api/conversations", { method: "POST", body: JSON.stringify(payload) });
    currentConversationId = data.conversation_id;
    currentTaskId = data.task_id || "";
    $("conversationId").textContent = currentConversationId;
    await loadConversationDetail(currentConversationId);
    if (data.task_id) pollTask(data.task_id);
  } catch (error) {
    setConversationBusy(false);
    notice(error.message);
  }
}

async function loadConversationDetail(conversationId) {
  try {
    const data = await api(`/api/conversations/${encodeURIComponent(conversationId)}`);
    currentConversationId = data.conversation_id;
    $("conversationId").textContent = data.conversation_id;
    $("convState").textContent = data.state;
    $("convState").className = `badge ${data.state}`;
    $("conversationMeta").textContent = data.current_task_id ? `当前任务 ${data.current_task_id}` : "暂无当前脚本";
    const lastTurn = (data.turns || []).at(-1);
    const requestText = lastTurn && lastTurn.instruction
      ? `第 ${lastTurn.round} 轮修改：\n${lastTurn.instruction}`
      : (data.initial_prompt || "已有脚本");
    setCurrentRequest(requestText);
    const taskId = data.current_task_id || (lastTurn && lastTurn.task_id);
    if (!taskId) {
      setTurnComposerVisible(false);
      setConversationBusy(false);
      return;
    }
    const status = await api(`/api/tasks/${taskId}`);
    setTask(status);
    const ready = status.state === "success" && data.state === "active";
    setTurnComposerVisible(ready);
    setConversationBusy(!terminalStates.has(status.state));
    if (!terminalStates.has(status.state)) pollTask(taskId);
    else if (ready) $("conversationInfo").textContent = "当前脚本已生成，可以提交下一轮修改。";
  } catch (error) {
    setConversationBusy(false);
    notice(error.message);
  }
}

function pollTask(taskId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const status = await api(`/api/tasks/${taskId}`);
      setTask(status);
      if (terminalStates.has(status.state)) {
        clearInterval(pollTimer);
        setConversationBusy(false);
        await loadConversationDetail(currentConversationId);
        await loadHistory();
      }
    } catch (error) {
      clearInterval(pollTimer);
      setConversationBusy(false);
      notice(error.message);
    }
  }, 1200);
}

async function submitTurn() {
  const instruction = $("convInstruction").value.trim();
  if (conversationBusy) return notice("当前任务执行中，请等待完成。");
  if (!currentConversationId) return notice("请先创建会话。");
  if (!instruction) return notice("请输入下一轮修改内容。");
  try {
    setCurrentRequest(`下一轮修改：\n${instruction}`);
    setConversationBusy(true);
    const data = await api(`/api/conversations/${encodeURIComponent(currentConversationId)}/tasks`, {
      method: "POST",
      body: JSON.stringify({ instruction, options: parseOptions() }),
    });
    $("convInstruction").value = "";
    currentTaskId = data.task_id || "";
    setTurnComposerVisible(false);
    pollTask(data.task_id);
  } catch (error) {
    setConversationBusy(false);
    notice(error.message);
  }
}

async function finishConversation() {
  if (!currentConversationId) return notice("请先创建会话。");
  try {
    await api(`/api/conversations/${encodeURIComponent(currentConversationId)}/finish`, { method: "POST" });
    setTurnComposerVisible(false);
    await loadConversationDetail(currentConversationId);
    await loadHistory();
  } catch (error) {
    notice(error.message);
  }
}

async function loadHistory() {
  try {
    const data = await api("/api/conversations?limit=50");
    const items = data.conversations || [];
    $("historyTotal").textContent = String(items.length);
    const box = $("historyBox");
    if (!items.length) {
      box.className = "list empty";
      box.textContent = "暂无记录";
      return;
    }
    box.className = "list";
    box.innerHTML = items.map((item) => {
      const title = (item.initial_prompt || "已有脚本").slice(0, 100);
      return `<button class="history-item" type="button" data-conv="${escapeHtml(item.conversation_id)}"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(item.created_at)} · ${escapeHtml(item.state)} · ${item.turn_count} 轮</span></button>`;
    }).join("");
    box.querySelectorAll("[data-conv]").forEach((button) => {
      button.addEventListener("click", () => loadConversationDetail(button.dataset.conv));
    });
  } catch (error) {
    $("historyBox").textContent = error.message;
  }
}

function copyTextFallback(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }
  return copied;
}

function selectScriptForManualCopy() {
  const script = $("scriptBox");
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(script);
  selection.removeAllRanges();
  selection.addRange(range);
  script.scrollIntoView({ block: "nearest" });
}

async function copyScript() {
  const text = $("scriptBox").textContent || "";
  if (!text || text === "暂无脚本") return notice("暂无可复制脚本。");
  try {
    let copied = false;
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        copied = true;
      } catch (error) {
        copied = false;
      }
    }
    if (!copied) copied = copyTextFallback(text);
    if (copied) {
      notice("脚本已复制。");
    } else {
      selectScriptForManualCopy();
      notice("浏览器拒绝自动复制，脚本文本已选中，请按 Ctrl+C 复制。");
    }
  } catch (error) {
    selectScriptForManualCopy();
    notice(`自动复制失败，脚本文本已选中，请按 Ctrl+C 复制。`);
  }
}

async function cancelCurrent() {
  if (!currentTaskId) return;
  try {
    await api(`/api/tasks/${encodeURIComponent(currentTaskId)}/cancel`, { method: "POST" });
    await loadConversationDetail(currentConversationId);
  } catch (error) {
    notice(error.message);
  }
}

async function checkHealth() {
  try {
    const data = await api("/healthz");
    $("healthText").textContent = data.status === "ok" ? "service ok" : "service unknown";
  } catch (error) {
    $("healthText").textContent = `service error: ${error.message}`;
  }
}

$("createConv").addEventListener("click", createConversation);
$("submitTurn").addEventListener("click", submitTurn);
$("finishConv").addEventListener("click", finishConversation);
$("cancelTask").addEventListener("click", cancelCurrent);
$("copyScript").addEventListener("click", copyScript);
$("refreshHistory").addEventListener("click", loadHistory);

setTurnComposerVisible(false);
checkHealth();
loadHistory();
