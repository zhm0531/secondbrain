const state = { selectedId: null, items: [] };

const $ = (id) => document.getElementById(id);
const statusLabels = {
  active: "已生效",
  candidate: "候选",
  archived: "已归档",
  rejected: "已拒绝",
};
const scopeLabels = { global: "全局", project: "项目内", session: "会话内", agent: "Agent 内" };
const typeLabels = {
  preference: "偏好",
  fact: "事实",
  decision: "决策",
  instruction: "规则",
  context: "背景",
  open_loop: "待解决问题",
  summary: "摘要",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

function setMessage(message, isError = false) {
  $("detail-message").textContent = message;
  $("detail-message").style.color = isError ? "#c43d48" : "";
}

function fillSelect(selectId, items, valueKey, labelKey) {
  const select = $(selectId);
  const first = select.options[0];
  select.innerHTML = "";
  select.appendChild(first);
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item[valueKey];
    option.textContent = item[labelKey];
    select.appendChild(option);
  }
}

async function loadFilters() {
  const [agents, projects] = await Promise.all([api("/api/agents"), api("/api/projects")]);
  fillSelect("agent-select", agents.items, "agent_id", "display_name");
  fillSelect("project-select", projects.items, "project_id", "name");
  fillSelect("new-agent-select", agents.items, "agent_id", "display_name");
  fillSelect("new-project-select", projects.items, "project_id", "name");
}

function makeMeta(label, value) {
  const item = document.createElement("div");
  item.className = "meta-item";
  const caption = document.createElement("span");
  caption.textContent = label;
  const strong = document.createElement("strong");
  strong.textContent = value || "—";
  item.append(caption, strong);
  return item;
}

function conflictReason(item) {
  if (item.reason) return item.reason;
  const overlap = Number.isFinite(Number(item.overlap)) ? `${Math.round(Number(item.overlap) * 100)}%` : "较高比例";
  return `同一生效范围和记忆类型，正文词语重叠约 ${overlap}`;
}

function closeConflictDialog() {
  $("conflict-dialog").classList.add("hidden");
  $("conflict-list").replaceChildren();
}

function renderConflictDialog(record, conflicts) {
  $("conflict-dialog-title").textContent = `记忆 ${record.memory_number || record.memory_id} 的冲突`;
  $("conflict-dialog-intro").textContent = conflicts.length
    ? `检测到 ${conflicts.length} 条可能冲突的记忆。以下编号和理由仅用于辅助审核。`
    : "未发现潜在冲突。";
  const list = $("conflict-list");
  list.replaceChildren();
  if (!conflicts.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "这条记忆目前没有匹配到潜在冲突。";
    list.appendChild(empty);
  }
  for (const conflict of conflicts) {
    const item = document.createElement("article");
    item.className = "conflict-item";
    const header = document.createElement("div");
    header.className = "conflict-item-header";
    const number = document.createElement("strong");
    number.textContent = conflict.memory_number || conflict.memory_id;
    const view = document.createElement("button");
    view.type = "button";
    view.className = "button secondary conflict-view-button";
    view.textContent = "查看记忆";
    view.addEventListener("click", async () => {
      closeConflictDialog();
      await selectMemory(conflict.memory_id);
    });
    header.append(number, view);
    const content = document.createElement("p");
    const text = conflict.content || "（无正文）";
    content.textContent = text.length > 180 ? `${text.slice(0, 180)}…` : text;
    const reason = document.createElement("p");
    reason.className = "conflict-reason";
    reason.textContent = `理由：${conflictReason(conflict)}`;
    item.append(header, content, reason);
    list.appendChild(item);
  }
  $("conflict-dialog").classList.remove("hidden");
}

async function showConflicts(memory) {
  try {
    const params = new URLSearchParams({
      content: memory.content || "",
      scope: memory.scope || "",
      memory_type: memory.memory_type || "",
    });
    const data = await api(`/api/memories/conflicts?${params.toString()}`);
    renderConflictDialog(memory, data.items || []);
  } catch (error) {
    setMessage(error.message, true);
  }
}

function renderList(items) {
  state.items = items;
  const list = $("memory-list");
  list.replaceChildren();
  $("result-count").textContent = `${items.length} 条`;
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state panel";
    empty.textContent = "没有找到匹配的记忆。";
    list.appendChild(empty);
    return;
  }
  for (const item of items) {
    const card = document.createElement("article");
    card.className = `memory-card ${item.memory_id === state.selectedId ? "selected" : ""}`;
    card.addEventListener("click", () => selectMemory(item.memory_id));
    const badge = document.createElement("span");
    badge.className = `badge ${item.status}`;
    badge.textContent = statusLabels[item.status] || item.status;
    const title = document.createElement("h3");
    const content = item.content || "（无正文）";
    title.textContent = content.length > 100 ? `${content.slice(0, 100)}…` : content;
    const summary = document.createElement("p");
    summary.textContent = `${typeLabels[item.memory_type] || item.memory_type} · ${scopeLabels[item.scope] || item.scope}`;
    if (item.has_conflicts) summary.style.color = "#b45309";
    if (item.has_conflicts) {
      const warning = document.createElement("button");
      warning.type = "button";
      warning.className = "conflict-link";
      warning.textContent = `⚠ 可能冲突（${item.conflict_count}）`;
      warning.setAttribute("aria-label", `查看 ${item.conflict_count} 条可能冲突记忆`);
      warning.addEventListener("click", (event) => {
        event.stopPropagation();
        showConflicts(item);
      });
      summary.append(document.createTextNode(" · "), warning);
    }
    card.append(badge, title, summary);
    list.appendChild(card);
  }
}

async function searchMemories() {
  try {
    const params = new URLSearchParams();
    const query = $("search-input").value.trim();
    if (query) params.set("q", query);
    const scope = $("scope-select").value;
    if (scope) params.set("scope", scope);
    if ($( "agent-select").value) params.set("agent_id", $("agent-select").value);
    if ($( "project-select").value) params.set("project_id", $("project-select").value);
    params.set("include_candidates", $("include-candidates").checked ? "true" : "false");
    const data = await api(`/api/memories/search?${params.toString()}`);
    renderList(data.items);
    $("service-status").textContent = "已连接";
  } catch (error) {
    $("service-status").textContent = "连接失败";
    renderList([]);
    console.error(error);
  }
}

async function selectMemory(memoryId) {
  try {
    let record = await api(`/api/memories/${encodeURIComponent(memoryId)}`);
    if (record.requires_confirmation && record.memory) {
      const proceed = window.confirm("这条记忆不在当前 Agent 的默认访问范围内，是否继续读取？");
      if (!proceed) {
        setMessage("已取消读取该记忆。", true);
        return;
      }
      record = await api(`/api/memories/${encodeURIComponent(memoryId)}?confirmed=true`);
    }
    if (!record || !record.content) {
      throw new Error("记忆内容不可用");
    }
    state.selectedId = memoryId;
    $("empty-detail").classList.add("hidden");
    $("memory-detail").classList.remove("hidden");
    const badge = $("detail-status");
    badge.className = `badge ${record.status}`;
    badge.textContent = statusLabels[record.status] || record.status;
    $("detail-title").textContent = record.content.length > 70 ? `${record.content.slice(0, 70)}…` : record.content;
    $("detail-content").value = record.content;
    $("detail-meta").replaceChildren(
      makeMeta("类型", typeLabels[record.memory_type] || record.memory_type),
      makeMeta("编号", record.memory_number),
      makeMeta("生效范围", scopeLabels[record.scope] || record.scope),
      makeMeta("来源会话", record.source_session_id),
      makeMeta("来源 Agent", record.agent_id),
      makeMeta("可信度", String(record.confidence)),
      makeMeta("更新时间", record.updated_at),
    );
    $("approve-button").disabled = record.status !== "candidate";
    $("reject-button").disabled = record.status !== "candidate";
    $("archive-button").disabled = record.status === "archived" || record.status === "rejected";
    setMessage("");
    renderList(state.items);
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function transitionMemory(action) {
  if (!state.selectedId) return;
  try {
    await api(`/api/memories/${encodeURIComponent(state.selectedId)}/${action}`, { method: "POST", body: "{}" });
    await searchMemories();
    await selectMemory(state.selectedId);
    setMessage("已更新");
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function saveMemory() {
  if (!state.selectedId) return;
  try {
    await api(`/api/memories/${encodeURIComponent(state.selectedId)}`, {
      method: "PATCH",
      body: JSON.stringify({ content: $("detail-content").value }),
    });
    await searchMemories();
    await selectMemory(state.selectedId);
    setMessage("修改已保存");
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function createMemory(event) {
  event.preventDefault();
  try {
    const record = await api("/api/memories", {
      method: "POST",
      body: JSON.stringify({
        content: $("new-content").value,
        memory_type: $("new-type").value,
        scope: $("new-scope").value,
        status: "candidate",
        agent_id: $("new-agent-select").value || null,
        project_id: $("new-project-select").value || null,
      }),
    });
    $("create-form").reset();
    $("include-candidates").checked = true;
    await searchMemories();
    await selectMemory(record.memory_id);
    if (record.requires_confirmation) {
      setMessage(`发现 ${record.conflicts.length} 条可能冲突的记忆，请在确认替换前查看详情。`, true);
    }
  } catch (error) {
    alert(error.message);
  }
}

$("search-button").addEventListener("click", searchMemories);
$("refresh-button").addEventListener("click", async () => { await loadFilters(); await searchMemories(); });
$("include-candidates").addEventListener("change", searchMemories);
$("search-input").addEventListener("keydown", (event) => { if (event.key === "Enter") searchMemories(); });
$("close-detail").addEventListener("click", () => { state.selectedId = null; $("memory-detail").classList.add("hidden"); $("empty-detail").classList.remove("hidden"); renderList(state.items); });
$("save-button").addEventListener("click", saveMemory);
$("approve-button").addEventListener("click", () => transitionMemory("approve"));
$("reject-button").addEventListener("click", () => transitionMemory("reject"));
$("archive-button").addEventListener("click", () => transitionMemory("archive"));
$("create-form").addEventListener("submit", createMemory);
$("close-conflict-dialog").addEventListener("click", closeConflictDialog);
$("conflict-dialog").addEventListener("click", (event) => {
  if (event.target === $("conflict-dialog")) closeConflictDialog();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeConflictDialog();
});
document.querySelectorAll(".help-button").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    const target = $(button.dataset.help);
    document.querySelectorAll(".help-popover").forEach((popover) => {
      if (popover !== target) popover.classList.add("hidden");
    });
    target.classList.toggle("hidden");
  });
});
document.addEventListener("click", () => {
  document.querySelectorAll(".help-popover").forEach((popover) => popover.classList.add("hidden"));
});

(async function init() {
  try {
    await loadFilters();
    await searchMemories();
  } catch (error) {
    $("service-status").textContent = "连接失败";
    console.error(error);
  }
})();
