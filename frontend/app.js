const terminalStates = new Set(["success", "failed", "needs_review", "cancelled"]);
let mode = "prompt";
let currentTaskId = "";
let pollTimer = null;
let currentConversationId = "";
let convPollTimer = null;
const warlockTemplateKey = "afsim.warlock.launchTemplate";

const $ = (id) => document.getElementById(id);

function pretty(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

function notice(message) {
  const target = $("actionStatus") || $("resultBox");
  if (target) target.textContent = message;
}

function setBadge(state) {
  const badge = $("stateBadge");
  badge.textContent = state || "idle";
  badge.className = `badge ${state || ""}`;
}

function setTask(status) {
  currentTaskId = status.task_id || currentTaskId;
  $("taskId").textContent = currentTaskId || "-";
  $("taskLookup").value = currentTaskId || $("taskLookup").value;
  $("createdAt").textContent = status.created_at || "-";
  $("resultBox").textContent = pretty(status.result);
  if (status.result && status.result.script_text) {
    $("scriptBox").textContent = status.result.script_text;
  }
  setBadge(status.state);
  renderFlow(status);
  renderRetries(status.retries || []);
  renderSteps(status);
  if (terminalStates.has(status.state)) {
    loadLog();
  }
}

function renderFlow(status) {
  const state = status.state || "idle";
  const retries = status.retries || [];
  const hasScript = Boolean(
    (status.result && status.result.script_text) ||
      ($("scriptBox").textContent && !["暂无脚本", "未找到 scenario.txt 内容"].includes($("scriptBox").textContent))
  );
  const flow = [
    { key: "submit", hint: currentTaskId ? "已提交" : "等待任务" },
    { key: "generate", hint: hasScript ? "已有脚本" : currentTaskId ? "生成中" : "等待" },
    { key: "execute", hint: currentTaskId ? "执行/排队" : "等待" },
    { key: "fix", hint: retries.length ? `${retries.length} 次重试` : "无重试" },
    { key: "done", hint: terminalStates.has(state) ? state : "等待终态" },
  ];
  let activeIndex = 0;
  if (currentTaskId) activeIndex = 1;
  if (state === "running") activeIndex = hasScript ? 2 : 1;
  if (retries.length) activeIndex = 3;
  if (terminalStates.has(state)) activeIndex = 4;
  const isError = ["failed", "needs_review", "cancelled"].includes(state);

  flow.forEach((step, index) => {
    const el = document.querySelector(`.flow-step[data-step="${step.key}"]`);
    if (!el) return;
    const hint = el.querySelector("em");
    hint.textContent = step.hint;
    el.classList.remove("waiting", "active", "done", "error");
    if (index < activeIndex) {
      el.classList.add("done");
    } else if (index === activeIndex) {
      el.classList.add(isError && terminalStates.has(state) ? "error" : "active");
    } else {
      el.classList.add("waiting");
    }
  });
}

function renderRetries(retries) {
  if (!$("retryCount") || !$("retriesList")) return;
  $("retryCount").textContent = String(retries.length);
  const box = $("retriesList");
  if (!retries.length) {
    box.className = "list empty";
    box.textContent = "暂无记录";
    return;
  }
  box.className = "list";
  box.innerHTML = retries
    .map((r) => {
      const stdout = (r.stdout || "").slice(0, 1200);
      const stderr = (r.stderr || "").slice(0, 1200);
      const diff = r.diff ? `<pre>${escapeHtml(r.diff)}</pre>` : "";
      return `<div class="item"><strong>attempt ${r.attempt} / ${escapeHtml(r.matched_rule || "-")}</strong><div>rc=${r.rc}</div><pre>${escapeHtml(stdout || stderr)}</pre>${diff}</div>`;
    })
    .join("");
}

function renderSteps(status) {
  const retries = status.retries || [];
  const steps = [
    {
      title: "1. 接收任务",
      body: status.task_id ? `task_id=${status.task_id}` : "等待提交任务",
    },
    {
      title: "2. 生成或写入脚本",
      body: currentTaskId ? "scenario.txt 已进入任务工作目录" : "等待任务创建",
    },
  ];
  retries.forEach((r, index) => {
    steps.push({
      title: `${index + 3}. 执行 mission 并匹配错误`,
      body: `attempt=${r.attempt}, rc=${r.rc}, matched_rule=${r.matched_rule || "-"}`,
      extra: r.stdout || r.stderr || "",
    });
    steps.push({
      title: `${index + 3}. 修复结果`,
      body: r.diff || "未产生 diff，可能由 LLM 覆盖脚本或未应用修复",
    });
  });
  steps.push({
    title: `${steps.length + 1}. 当前终态`,
    body: `state=${status.state || "idle"}\n${pretty(status.result)}`,
  });
  $("stepCount").textContent = String(steps.length);
  const box = $("stepsList");
  box.className = "list";
  box.innerHTML = steps
    .map((s) => {
      const extra = s.extra ? `<pre>${escapeHtml(s.extra.slice(0, 1200))}</pre>` : "";
      return `<div class="item"><strong>${escapeHtml(s.title)}</strong><div>${escapeHtml(s.body)}</div>${extra}</div>`;
    })
    .join("");
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || `${resp.status} ${resp.statusText}`);
  }
  return data;
}

async function checkHealth() {
  try {
    const data = await api("/healthz");
    $("healthText").textContent = data.status === "ok" ? "service ok" : "service unknown";
  } catch (err) {
    $("healthText").textContent = `service error: ${err.message}`;
  }
}

function switchMode(nextMode) {
  mode = nextMode;
  $("promptTab").classList.toggle("active", mode === "prompt");
  $("scriptTab").classList.toggle("active", mode === "script");
  $("inputLabel").textContent = mode === "prompt" ? "任务需求" : "脚本内容";
  $("promptInput").value =
    mode === "prompt"
      ? "生成一个带雷达和空空导弹的空战场景"
      : "end_time 7200 sec\n";
}

function switchPanel(next) {
  $("promptTab").classList.toggle("active", next === "single-prompt");
  $("scriptTab").classList.toggle("active", next === "single-script");
  $("convTab").classList.toggle("active", next === "conversation");
  $("taskForm").closest(".submit-panel").style.display = next === "conversation" ? "none" : "";
  $("convPanel").style.display = next === "conversation" ? "" : "none";
  if (next === "single-prompt") switchMode("prompt");
  if (next === "single-script") switchMode("script");
  if (next === "conversation") loadConversations();
}

function parseConvOptions() {
  return $("convCreateOptions")
    .value.split(/\s+/)
    .map((x) => x.trim())
    .filter(Boolean);
}

async function createConversation() {
  const text = $("convCreateInput").value;
  const payload = { options: parseConvOptions() };
  if ($("convScriptMode").checked) {
    payload.script = text;
  } else {
    payload.prompt = text;
  }
  try {
    const data = await api("/api/conversations", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    currentConversationId = data.conversation_id;
    await loadConversations();
    await loadConversationDetail(data.conversation_id);
    pollConversationTurn(data.task_id);
  } catch (err) {
    $("convThread").className = "list empty";
    $("convThread").textContent = err.message;
  }
}

async function loadConversations() {
  try {
    const data = await api("/api/conversations");
    const items = data.conversations || [];
    const box = $("convList");
    if (!items.length) {
      box.className = "list empty";
      box.textContent = "暂无会话";
      return;
    }
    box.className = "list";
    box.innerHTML = items
      .map((c) => {
        const title = (c.initial_prompt || "(script)").slice(0, 60);
        return `<button class="history-item" type="button" data-conv="${escapeHtml(c.conversation_id)}"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(c.created_at)} / ${escapeHtml(c.state)} / ${c.turn_count} 轮</span></button>`;
      })
      .join("");
    box.querySelectorAll(".history-item").forEach((btn) => {
      btn.addEventListener("click", () => loadConversationDetail(btn.dataset.conv));
    });
  } catch (err) {
    $("convList").className = "list empty";
    $("convList").textContent = err.message;
  }
}

function renderConvThread(turns) {
  const box = $("convThread");
  if (!turns.length) {
    box.className = "list empty";
    box.textContent = "暂无轮次";
    return;
  }
  box.className = "list";
  box.innerHTML = turns
    .map((t) => {
      const label = t.instruction ? `第${t.round}轮: ${t.instruction}` : `第${t.round}轮: 初始脚本`;
      const summary = t.result
        ? t.result.message || t.result.error || t.result.unknown_error || ""
        : "";
      return `<button class="history-item" type="button" data-task="${escapeHtml(t.task_id)}"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(t.state || "-")} ${escapeHtml(summary)}</span></button>`;
    })
    .join("");
  box.querySelectorAll(".history-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      loadTask(btn.dataset.task);
    });
  });
}

async function loadConversationDetail(conversationId) {
  try {
    const data = await api(`/api/conversations/${encodeURIComponent(conversationId)}`);
    currentConversationId = data.conversation_id;
    $("convState").textContent = data.state;
    $("convState").className = `badge ${data.state}`;
    renderConvThread(data.turns || []);
    if (data.current_task_id) {
      const status = await api(`/api/tasks/${data.current_task_id}`);
      setTask(status);
    }
  } catch (err) {
    $("convThread").className = "list empty";
    $("convThread").textContent = err.message;
  }
}

function pollConversationTurn(taskId) {
  clearInterval(pollTimer);
  clearInterval(convPollTimer);
  convPollTimer = setInterval(async () => {
    try {
      const status = await api(`/api/tasks/${taskId}`);
      if (terminalStates.has(status.state)) {
        clearInterval(convPollTimer);
        setTask(status);
        if (currentConversationId) loadConversationDetail(currentConversationId);
      }
    } catch (err) {
      clearInterval(convPollTimer);
      notice(err.message);
    }
  }, 1200);
}

async function submitTurn() {
  const instruction = $("convInstruction").value.trim();
  if (!currentConversationId || !instruction) {
    notice("请先创建或选择会话，并输入修改指令");
    return;
  }
  try {
    const data = await api(`/api/conversations/${encodeURIComponent(currentConversationId)}/tasks`, {
      method: "POST",
      body: JSON.stringify({ instruction, options: parseConvOptions() }),
    });
    $("convInstruction").value = "";
    await loadConversationDetail(currentConversationId);
    pollConversationTurn(data.task_id);
  } catch (err) {
    notice(err.message);
  }
}

async function finishConv() {
  if (!currentConversationId) return;
  try {
    await api(`/api/conversations/${encodeURIComponent(currentConversationId)}/finish`, {
      method: "POST",
    });
    await loadConversationDetail(currentConversationId);
    await loadConversations();
  } catch (err) {
    notice(err.message);
  }
}

function parseOptions() {
  return $("optionsInput")
    .value.split(/\s+/)
    .map((x) => x.trim())
    .filter(Boolean);
}

async function submitTask(evt) {
  evt.preventDefault();
  const text = $("promptInput").value;
  const payload = { options: parseOptions() };
  if (mode === "prompt") {
    payload.prompt = text;
  } else {
    payload.script = text;
  }
  try {
    const status = await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setTask(status);
    loadPromptHistory();
    startPolling(status.task_id);
  } catch (err) {
    $("resultBox").textContent = pretty({ error: err.message });
    setBadge("failed");
  }
}

async function loadPromptHistory() {
  try {
    const data = await api("/api/prompt-history?limit=30");
    const items = data.history || [];
    $("historyTotal").textContent = `${items.length}`;
    const box = $("historyBox");
    if (!items.length) {
      box.className = "list empty";
      box.textContent = "暂无记录";
      return;
    }
    box.className = "list";
    box.innerHTML = items
      .map((item) => {
        const options = (item.options || []).join(" ");
        return `<button class="history-item" type="button" data-task="${escapeHtml(item.task_id)}" data-prompt="${escapeHtml(item.prompt)}" data-options="${escapeHtml(options)}"><strong>${escapeHtml(item.prompt)}</strong><span>${escapeHtml(item.created_at)} / ${escapeHtml(item.state || "-")}</span></button>`;
      })
      .join("");
    box.querySelectorAll(".history-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        switchMode("prompt");
        $("promptInput").value = btn.dataset.prompt || "";
        $("optionsInput").value = btn.dataset.options || "-es";
        $("taskLookup").value = btn.dataset.task || "";
        if (btn.dataset.task) {
          loadTask(btn.dataset.task);
        }
      });
    });
  } catch (err) {
    $("historyBox").className = "list empty";
    $("historyBox").textContent = err.message;
  }
}

async function loadTask(taskId = $("taskLookup").value.trim()) {
  if (!taskId) return;
  try {
    const status = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
    setTask(status);
    if (!terminalStates.has(status.state)) {
      startPolling(status.task_id);
    }
  } catch (err) {
    $("resultBox").textContent = pretty({ error: err.message });
  }
}

function startPolling(taskId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const status = await api(`/api/tasks/${taskId}`);
      setTask(status);
      if (terminalStates.has(status.state)) {
        clearInterval(pollTimer);
      }
    } catch (err) {
      clearInterval(pollTimer);
      $("resultBox").textContent = pretty({ error: err.message });
    }
  }, 1200);
}

async function cancelCurrent() {
  const taskId = currentTaskId || $("taskLookup").value.trim();
  if (!taskId) return;
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
    await loadTask(taskId);
  } catch (err) {
    $("resultBox").textContent = pretty({ error: err.message });
  }
}

async function loadLog() {
  const taskId = currentTaskId || $("taskLookup").value.trim();
  if (!taskId) return;
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(taskId)}/log`);
    notice(pretty(data));
    $("scriptBox").textContent = data.scenario_text || "未找到 scenario.txt 内容";
  } catch (err) {
    notice(err.message);
    if (!$("scriptBox").textContent || $("scriptBox").textContent === "暂无脚本") {
      $("scriptBox").textContent = err.message;
    }
  }
}

async function copyScript() {
  const text = $("scriptBox").textContent || "";
  if (!text || ["暂无脚本", "未找到 scenario.txt 内容"].includes(text)) {
    notice("暂无可复制脚本");
    return;
  }
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.focus();
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
    }
    notice("脚本已复制");
  } catch (err) {
    notice(`复制失败: ${err.message}`);
  }
}

function loadWarlockConfig() {
  $("warlockTemplate").value = localStorage.getItem(warlockTemplateKey) || "";
}

function saveWarlockConfig() {
  localStorage.setItem(warlockTemplateKey, $("warlockTemplate").value.trim());
  notice("Warlock 配置已保存");
}

function runWarlock() {
  const taskId = currentTaskId || $("taskLookup").value.trim();
  if (!taskId) {
    notice("请先选择或查询一个任务");
    return;
  }
  const template = ($("warlockTemplate").value || "").trim();
  if (!template) {
    notice("请先配置 Warlock 启动 URL 模板，例如 warlock://open?script={script_url}");
    return;
  }
  const scriptUrl = new URL(`/api/tasks/${encodeURIComponent(taskId)}/scenario.txt`, window.location.href).href;
  const launchUrl = template
    .replaceAll("{script_url}", encodeURIComponent(scriptUrl))
    .replaceAll("{task_id}", encodeURIComponent(taskId));
  window.location.href = launchUrl;
  notice(`已请求启动 Warlock: ${launchUrl}`);
}

async function loadLessons() {
  if (!$("lessonTotal") || !$("lessonsBox")) return;
  try {
    const data = await api("/api/lessons");
    const entries = Object.entries(data).filter(([, count]) => count > 0);
    $("lessonTotal").textContent = `${entries.length}`;
    const box = $("lessonsBox");
    if (!entries.length) {
      box.className = "list empty";
      box.textContent = "暂无数据";
      return;
    }
    box.className = "list";
    box.innerHTML = entries
      .map(([id, count]) => `<div class="item"><strong>${escapeHtml(id)}</strong><div>${count}</div></div>`)
      .join("");
  } catch (err) {
    $("lessonsBox").className = "list empty";
    $("lessonsBox").textContent = err.message;
  }
}

async function loadPending() {
  if (!$("pendingTotal") || !$("pendingBox")) return;
  try {
    const data = await api("/api/pending");
    const items = data.pending || [];
    $("pendingTotal").textContent = `${items.length}`;
    const box = $("pendingBox");
    if (!items.length) {
      box.className = "list empty";
      box.textContent = "暂无数据";
      return;
    }
    box.className = "list";
    box.innerHTML = items
      .map((item) => `<div class="item"><strong>${escapeHtml(item.file)}</strong><div>${escapeHtml(item.summary)}</div></div>`)
      .join("");
  } catch (err) {
    $("pendingBox").className = "list empty";
    $("pendingBox").textContent = err.message;
  }
}

$("promptTab").addEventListener("click", () => switchPanel("single-prompt"));
$("scriptTab").addEventListener("click", () => switchPanel("single-script"));
$("convTab").addEventListener("click", () => switchPanel("conversation"));
$("createConv").addEventListener("click", createConversation);
$("submitTurn").addEventListener("click", submitTurn);
$("finishConv").addEventListener("click", finishConv);
$("refreshConvs").addEventListener("click", loadConversations);
$("taskForm").addEventListener("submit", submitTask);
$("lookupTask").addEventListener("click", () => loadTask());
$("cancelTask").addEventListener("click", cancelCurrent);
$("loadScript").addEventListener("click", loadLog);
$("copyScript").addEventListener("click", copyScript);
$("runWarlock").addEventListener("click", runWarlock);
$("saveWarlockConfig").addEventListener("click", saveWarlockConfig);
$("refreshHistory").addEventListener("click", loadPromptHistory);

checkHealth();
loadWarlockConfig();
loadPromptHistory();
