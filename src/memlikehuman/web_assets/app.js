"use strict";
const $ = (id) => document.getElementById(id);
const labels = {
  persona: [
    "核心人格",
    "◈",
    "人格在所有项目间共享。编辑会创建新版本，可随时回退。",
  ],
  events: ["原始经历", "▤", "保存原话和出处。可添加修订副本，不覆盖历史原文。"],
  fact: ["事实", "◇", "查看当前与历史事实；修订保留来源与原有可信度类型。"],
  preference: ["偏好", "♡", "保留喜欢、不喜欢，以及偏好发生的变化。"],
  agreement: ["共同约定", "⌁", "一起确认过的约定，始终可以追溯来源。"],
  growth: ["成长记忆", "↗", "随经历积累的习惯和关系变化，不覆盖核心人格。"],
  episode: ["共同经历", "◷", "旧经历可以渐渐模糊，原文始终可查。"],
  observation: [
    "观察与推测",
    "◎",
    "保持不确定性的标记，不将推测升级为已确认事实。",
  ],
  emotion: [
    "情绪表达",
    "◌",
    "角色表达的状态，随时间回归基线；不表示真实主观感受。",
  ],
  checkpoints: [
    "工作交接",
    "☑",
    "目标、完成项、待办与下一步。编辑保存为新的交接记录。",
  ],
};
const basis = {
  user_statement: "用户陈述",
  assistant_expression: "助手表达",
  inference: "推测",
  user: "用户",
  assistant: "助手",
  tool: "工具",
  system: "系统",
  active: "有效",
  superseded: "历史",
  revoked: "已撤销",
  pending: "待提炼",
  done: "已处理",
};
let state = {
  library: "main",
  persona: "default",
  project: "default",
  layer: "events",
  page: 0,
  q: "",
};
let generation = 0,
  current = null,
  saving = false;
const params = new URLSearchParams(location.hash.slice(1));
if (params.has("token")) {
  sessionStorage.setItem("mlh-token", params.get("token"));
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("mlh-token") || "";
function node(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function toast(text) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("toast").hidden = true), 6500);
}
async function api(path, extra = {}, body, raw = false) {
  const query = new URLSearchParams({ ...state, ...extra });
  const response = await fetch(path + "?" + query, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "X-MemLikeHuman-Token": token,
      ...(raw ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
  });
  if (!response.ok) {
    let error;
    try {
      error = await response.json();
    } catch {}
    throw new Error(error?.error || "请求未完成，请刷新重试。");
  }
  return response;
}
async function json(path, extra = {}, body) {
  return (await api(path, extra, body)).json();
}
const safely =
  (fn) =>
  (...args) =>
    Promise.resolve()
      .then(() => fn(...args))
      .catch((e) => toast(e.message));
function option(select, value, text) {
  const el = node("option", text);
  el.value = value;
  select.append(el);
}
async function overview() {
  const data = await json("/api/overview");
  $("library").replaceChildren();
  for (const item of data.libraries) option($("library"), item.id, item.name);
  $("library").value = state.library;
  $("library-path").textContent =
    data.libraries.find((x) => x.id === state.library)?.path || "";
  $("scope").replaceChildren();
  for (const item of data.scopes)
    option(
      $("scope"),
      JSON.stringify([item.persona_id, item.project_id]),
      item.persona_id + " / " + item.project_id,
    );
  const selected = JSON.stringify([state.persona, state.project]);
  if ([...$("scope").options].some((x) => x.value === selected))
    $("scope").value = selected;
  else [state.persona, state.project] = JSON.parse($("scope").value);
}
function renderNav(counts = {}) {
  $("layers").replaceChildren();
  for (const [key, [title, icon]] of Object.entries(labels)) {
    const b = node("button");
    b.type = "button";
    b.className = key === state.layer ? "active" : "";
    b.setAttribute("aria-current", key === state.layer ? "page" : "false");
    b.append(
      node("span", icon),
      node("span", title),
      node("span", counts[key] ?? "", "count"),
    );
    b.onclick = safely(async () => {
      state.layer = key;
      state.page = 0;
      state.q = "";
      $("search").value = "";
      await load();
    });
    $("layers").append(b);
  }
}
function date(value) {
  return value
    ? new Date(value).toLocaleString("zh-CN", { hour12: false })
    : "";
}
async function load() {
  const ticket = ++generation;
  const data = await json("/api/list");
  if (ticket !== generation) return;
  renderNav(data.counts);
  $("crumb").textContent = $("layer-title").textContent =
    labels[state.layer][0];
  $("layer-description").textContent = labels[state.layer][2];
  $("stat-events").textContent = data.counts.events ?? 0;
  $("stat-facts").textContent =
    (data.counts.fact ?? 0) + (data.counts.preference ?? 0);
  $("stat-growth").textContent =
    (data.counts.agreement ?? 0) + (data.counts.growth ?? 0);
  $("stat-work").textContent = data.counts.checkpoints ?? 0;
  $("result-count").textContent = data.total + " 条记录";
  $("search").disabled = state.layer === "persona";
  $("new-record").textContent =
    state.layer === "persona"
      ? "＋ 编辑人格"
      : state.layer === "checkpoints"
        ? "＋ 新建交接"
        : "＋ 新增原始记录";
  $("list").replaceChildren();
  if (!data.items.length) {
    const empty = node("div", undefined, "empty");
    empty.append(
      node("div", "◌", "empty-symbol"),
      node("strong", state.q ? "没有匹配的记忆" : "这一层，还留着空白"),
      node(
        "div",
        state.q
          ? "试试其他关键词，或切换记忆分层。"
          : "导入已有记忆包，或从一段新的原始经历开始。",
      ),
    );
    $("list").append(empty);
  }
  for (const item of data.items) {
    const b = node("button", undefined, "record");
    const top = node("div", undefined, "record-top");
    top.append(
      node(
        "span",
        state.layer === "persona"
          ? "版本 " + item.version
          : basis[item.role || item.basis] || "任务状态",
        "badge",
      ),
      node("span", date(item.occurred_at || item.valid_at || item.created_at)),
    );
    if (item.status)
      top.append(node("span", basis[item.status] || item.status));
    const text =
      state.layer === "persona"
        ? item.content.name + " · " + item.content.traits.join(" · ")
        : item.preview;
    b.append(
      top,
      node("div", text, "record-text"),
      node("div", item.id || "人格版本 " + item.version, "record-id"),
    );
    b.onclick = safely(() => openRecord(item.id ?? String(item.version)));
    $("list").append(b);
  }
  $("page-label").textContent = `第 ${state.page + 1} 页 · 每页 20 条`;
  $("previous").disabled = state.page === 0;
  $("next").disabled = (state.page + 1) * 20 >= data.total;
}
function field(
  key,
  title,
  value = "",
  { type = "text", rows = 0, hint = "", min, max, step } = {},
) {
  const wrap = node("label", undefined, "field");
  wrap.append(node("span", title));
  const input = node(rows ? "textarea" : "input");
  input.name = key;
  input.value = value ?? "";
  if (!rows) input.type = type;
  else input.rows = rows;
  for (const [k, v] of Object.entries({ min, max, step }))
    if (v !== undefined) input[k] = v;
  if (hint) wrap.append(node("small", hint));
  wrap.append(input);
  $("fields").append(wrap);
  return input;
}
function note(text) {
  $("fields").append(node("p", text, "note"));
}
function details(title, content) {
  const d = node("details");
  d.append(
    node("summary", title),
    node(
      "pre",
      typeof content === "string" ? content : JSON.stringify(content, null, 2),
    ),
  );
  $("source-area").append(d);
}
function personaFields(
  content = { name: "知伴", traits: [], values: [], style: [], boundaries: [] },
) {
  field("name", "名称", content.name);
  for (const [key, title] of Object.entries({
    traits: "性格特征",
    values: "价值取向",
    style: "表达习惯",
    boundaries: "人格边界",
  }))
    field(key, title, content[key].join("\n"), { rows: 3, hint: "每行一条" });
}
function taskFields(row = { state: {} }) {
  field("session_id", "会话 ID", row.session_id || "default");
  field("covered_event_id", "覆盖到的原始事件 ID", row.covered_event_id || "", {
    hint: "必须属于当前人格、项目及该会话",
  });
  for (const [key, title] of Object.entries({
    goal: "目标",
    completed: "已完成",
    pending: "待办",
    constraints: "约束",
    next_step: "下一步",
  }))
    field(
      key,
      title,
      Array.isArray(row.state[key])
        ? row.state[key].join("\n")
        : row.state[key] || "",
      {
        rows: 3,
        hint: ["completed", "pending", "constraints"].includes(key)
          ? "每行一项"
          : "",
      },
    );
}
function editorStart(title) {
  $("fields").replaceChildren();
  $("source-area").replaceChildren();
  $("editor-title").textContent = title;
  $("delete-record").hidden = true;
  $("save-record").hidden = false;
  $("save-record").textContent = "保存新版本";
}
async function openRecord(id) {
  const row = await json("/api/detail", { id });
  current = { layer: state.layer, id, row, scope: { ...state } };
  editorStart(labels[state.layer][0] + " · 详情");
  if (state.layer === "persona") {
    personaFields(row.content);
    note("保存会新增人格版本，所有项目共享这份人格。");
    const rollback = node("button", "将此版本恢复为当前人格");
    rollback.type = "button";
    rollback.onclick = safely(async () => {
      await edit("rollback", { version: row.version });
    });
    $("source-area").append(rollback);
  } else if (state.layer === "events") {
    field("text", "原始内容 / 修订内容", row.text, { rows: 12 });
    note(
      "原始记录保持不变。保存会新增一份标明来源的参考修订，不会冒充历史对话，也不会自动改变已有提炼记忆。",
    );
    details("原始记录元数据", { ...row, text: undefined });
    if (row.category === "conversation") {
      const derive = node("button", "从这段原文新增提炼记忆");
      derive.type = "button";
      derive.onclick = () => deriveForm(row);
      $("source-area").append(derive);
    }
    $("save-record").textContent = "保存修订副本";
    $("delete-record").hidden = false;
  } else if (state.layer === "checkpoints") {
    taskFields(row);
    note("原交接记录保留，保存后新增一份当前交接。");
  } else {
    field("content", "记忆内容", row.content, { rows: 5 });
    field("gist", "模糊记忆 / 概览", row.gist || "", {
      rows: 2,
      hint: "可留空，最多 160 字",
    });
    field("confidence", "置信度", row.confidence, {
      type: "number",
      min: 0,
      max: 1,
      step: 0.05,
    });
    if (state.layer === "emotion") {
      field("valence", "情绪方向（−1 到 1）", row.valence, {
        type: "number",
        min: -1,
        max: 1,
        step: 0.1,
      });
      field("arousal", "情绪强度（0 到 1）", row.arousal, {
        type: "number",
        min: 0,
        max: 1,
        step: 0.1,
      });
    }
    note(
      "保存会撤销旧版本并保留历史，不更改来源、记忆类别或陈述类型。当前分区的旧工作交接将失效，请核对后重建。",
    );
    details("来源原文 · " + (basis[row.basis] || row.basis), row.source.text);
    details("来源与有效期", {
      event_id: row.event_id,
      source: row.source.source,
      source_quote: row.source_quote,
      valid_at: row.valid_at,
      invalid_at: row.invalid_at,
    });
    details("同来源的版本与记忆", row.history);
    $("delete-record").hidden = false;
  }
  $("editor").showModal();
}
function deriveForm(row) {
  current = { layer: "derive", id: row.id, row, scope: { ...state } };
  editorStart("从原文提炼记忆");
  const kindLabel = node("label", undefined, "field");
  kindLabel.append(node("span", "记忆类别"));
  const kind = node("select");
  kind.name = "kind";
  for (const k of [
    "fact",
    "preference",
    "agreement",
    "growth",
    "episode",
    "observation",
    "emotion",
  ])
    option(kind, k, labels[k][0]);
  kindLabel.append(kind);
  $("fields").append(kindLabel);
  field("content", "提炼内容", "", { rows: 4 });
  field("source_quote", "来源原话", "", {
    rows: 3,
    hint: "必须逐字存在于原文中",
  });
  const bLabel = node("label", undefined, "field");
  bLabel.append(node("span", "陈述类型"));
  const b = node("select");
  b.name = "basis";
  option(b, "inference", "推测（保留不确定性）");
  if (row.role === "user") option(b, "user_statement", "用户陈述");
  if (row.role === "assistant") option(b, "assistant_expression", "助手表达");
  bLabel.append(b);
  $("fields").append(bLabel);
  field("confidence", "置信度", 0.7, {
    type: "number",
    min: 0,
    max: 1,
    step: 0.05,
  });
  field("valence", "情绪方向（仅情绪记录）", 0, {
    type: "number",
    min: -1,
    max: 1,
    step: 0.1,
  });
  field("arousal", "情绪强度（仅情绪记录）", 0, {
    type: "number",
    min: 0,
    max: 1,
    step: 0.1,
  });
  details("来源原文", row.text);
  note(
    "这是人工提炼，不调用模型 API。情绪必须来自助手表达，成长记录不能仅基于推测；保存后该原文标记为已人工处理。",
  );
}
async function edit(action, payload) {
  if (saving) return;
  saving = true;
  $("save-record").disabled = true;
  try {
    await json("/api/edit", current.scope, { action, payload });
    $("editor").close();
    await overview();
    await load();
    toast("已保存到本地记忆库。");
  } finally {
    saving = false;
    $("save-record").disabled = false;
  }
}
$("edit-form").onsubmit = safely(async (event) => {
  event.preventDefault();
  const form = new FormData($("edit-form"));
  const val = (k) => String(form.get(k) || "");
  const lines = (k) =>
    val(k)
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
  if (current.layer === "persona") {
    const content = { name: val("name") };
    for (const k of ["traits", "values", "style", "boundaries"])
      content[k] = lines(k);
    await edit("persona", { content });
  } else if (current.layer === "derive") {
    const memory = {
      kind: val("kind"),
      content: val("content"),
      source_quote: val("source_quote"),
      basis: val("basis"),
      confidence: Number(val("confidence")),
    };
    if (memory.kind === "emotion") {
      memory.valence = Number(val("valence"));
      memory.arousal = Number(val("arousal"));
    }
    await edit("derive", { event_id: current.id, memory });
  } else if (current.layer === "new-event") {
    await edit("event", {
      event_id: crypto.randomUUID(),
      text: val("text"),
      role: val("role"),
      source: val("source"),
      session_id: val("session_id"),
      occurred_at: new Date(val("occurred_at")).toISOString(),
    });
  } else if (current.layer === "events") {
    await edit("revision", { id: current.id, text: val("text") });
  } else if (current.layer === "checkpoints") {
    await edit("checkpoint", {
      session_id: val("session_id"),
      covered_event_id: val("covered_event_id"),
      state: {
        goal: val("goal"),
        completed: lines("completed"),
        pending: lines("pending"),
        constraints: lines("constraints"),
        next_step: val("next_step"),
      },
    });
  } else {
    const edits = {
      content: val("content"),
      gist: val("gist") || null,
      confidence: Number(val("confidence")),
    };
    if (current.layer === "emotion")
      for (const key of ["valence", "arousal"])
        edits[key] = val(key) === "" ? null : Number(val(key));
    await edit("memory", { id: current.id, edits });
  }
});
// Prevent the browser's native form navigation before the asynchronous wrapper runs.
$("edit-form").addEventListener("submit", (event) => event.preventDefault());
$("delete-record").onclick = safely(async () => {
  if (
    !confirm(
      "将删除来源原文、同来源的全部派生记忆及纠错链，并清除当前分区的工作交接。独立修订副本和已有备份不受影响。确定删除？",
    )
  )
    return;
  await edit("forget", { id: current.id });
});
$("new-record").onclick = safely(async () => {
  current = {
    layer:
      state.layer === "persona"
        ? "persona"
        : state.layer === "checkpoints"
          ? "checkpoints"
          : "new-event",
    scope: { ...state },
  };
  editorStart(
    current.layer === "new-event"
      ? "新增原始经历"
      : current.layer === "persona"
        ? "编辑核心人格"
        : "新建工作交接",
  );
  if (current.layer === "persona") {
    const result = await json("/api/list", { layer: "persona", page: 0 });
    personaFields(result.items[0]?.content);
  } else if (current.layer === "checkpoints") taskFields();
  else {
    field("text", "原文内容", "", { rows: 8 });
    const wrap = node("label", undefined, "field");
    wrap.append(node("span", "说话者"));
    const select = node("select");
    select.name = "role";
    option(select, "user", "用户");
    option(select, "assistant", "助手");
    wrap.append(select);
    $("fields").append(wrap);
    field("source", "来源", "manual-entry");
    field("session_id", "会话 ID", "default");
    field("occurred_at", "发生时间（含时区）", new Date().toISOString());
    note("请填写真实说话者与时间。保存仅持久化原文，不调用云端提炼。");
  }
  $("editor").showModal();
});
$("close-editor").onclick = () => $("editor").close();
$("close-transfer").onclick = () => $("transfer").close();
$("library").onchange = safely(async () => {
  state.library = $("library").value;
  state.page = 0;
  await overview();
  await load();
});
$("scope").onchange = safely(async () => {
  [state.persona, state.project] = JSON.parse($("scope").value);
  state.page = 0;
  await load();
});
$("refresh").onclick = safely(async () => {
  await overview();
  await load();
});
$("previous").onclick = safely(async () => {
  state.page--;
  await load();
});
$("next").onclick = safely(async () => {
  state.page++;
  await load();
});
let debounce;
$("search").oninput = () => {
  clearTimeout(debounce);
  debounce = setTimeout(
    safely(async () => {
      state.q = $("search").value;
      state.page = 0;
      await load();
    }),
    250,
  );
};
$("import-open").onclick = () => {
  $("transfer-title").textContent = "导入为独立记忆库";
  const box = $("transfer-content");
  box.replaceChildren(
    node(
      "p",
      "支持 MemLikeHuman JSON / JSONL 记忆包和 SQLite 备份，单文件不超过 64 MiB。不会覆盖当前记忆库；原始聊天导出需先转换。",
      "note",
    ),
  );
  const nameLabel = node("label", undefined, "field");
  nameLabel.append(node("span", "记忆库名称"));
  const name = node("input");
  name.value = "导入的记忆库";
  nameLabel.append(name);
  const file = node("input");
  file.type = "file";
  file.accept = ".json,.jsonl,.sqlite3,.db,.sqlite";
  file.setAttribute("aria-label", "选择记忆文件");
  const submit = node("button", "导入并打开", "dark");
  submit.onclick = safely(async () => {
    if (!file.files.length) throw new Error("请先选择记忆文件。");
    if (file.files[0].size > 64 * 1024 * 1024)
      throw new Error("超过 64 MiB，请用 CLI 导入。");
    submit.disabled = true;
    try {
      const result = await (
        await api(
          "/api/import",
          { name: name.value },
          await file.files[0].arrayBuffer(),
          true,
        )
      ).json();
      state.library = result.library;
      state.page = 0;
      $("transfer").close();
      await overview();
      await load();
      toast("已导入独立记忆库，当前库未被覆盖。");
    } finally {
      submit.disabled = false;
    }
  });
  box.append(
    nameLabel,
    file,
    node(
      "p",
      "导入文件保留所有人格与项目分区。密钥配置不随记忆包导入。",
      "muted",
    ),
    submit,
  );
  $("transfer").showModal();
};
$("export-open").onclick = () => {
  $("transfer-title").textContent = "导出与备份";
  const box = $("transfer-content");
  box.replaceChildren(
    node(
      "p",
      "导出当前选中的整个记忆库，包含全部人格和项目，不只是当前筛选。对话原文可能含私人信息。",
      "note",
    ),
  );
  for (const [fmt, title, description] of [
    ["json", "JSON 记忆包", "完整、可读，适合查看和迁移"],
    ["jsonl", "JSONL 记忆包", "逐行档案，适合批量处理"],
    ["sqlite3", "SQLite 备份", "数据库一致性快照，适合本地备份"],
  ]) {
    const b = node("button", title, "transfer-choice");
    b.append(node("small", description));
    b.onclick = safely(async () => {
      b.disabled = true;
      try {
        const response = await api("/api/export", { format: fmt });
        const url = URL.createObjectURL(await response.blob());
        const a = node("a");
        a.href = url;
        a.download = "memlikehuman." + fmt;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        toast("记忆文件已导出。");
      } finally {
        b.disabled = false;
      }
    });
    box.append(b);
  }
  $("transfer").showModal();
};
safely(async () => {
  if (!token)
    throw new Error("请用终端中 memlikehuman web 打印的完整链接打开面板。");
  await overview();
  await load();
})();
