"use strict";

const $ = (id) => document.getElementById(id);
const pretty = (value) => JSON.stringify(value, null, 2);
const text = (id, value) => { $(id).textContent = value; };
let targets = [], config = null, current = null, session = null, cursor = 0;
let wire = [], jobId = null, working = false, polling = false, monitoring = false;
let faultCatalog = [];
let observations = [], observing = false;
let workspace = "";
let operationsSession = null;
let observationRevision = 0;
const submissionErrors = new Map();

async function api(path, method = "GET", body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const options = {method, signal:controller.signal, headers:{"X-Simquaro-Client":"1"}};
    if (method !== "GET") {
      options.headers["Content-Type"] = "application/json";
      options.body = pretty(body ?? {});
    }
    const response = await fetch("/api" + path, options);
    const envelope = await response.json();
    if (!envelope.ok) {
      const error = new Error(`${envelope.error.code}: ${envelope.error.message}\n${(envelope.error.actions || []).join("\n")}`);
      error.code = envelope.error.code;
      throw error;
    }
    return envelope.result;
  } catch (error) {
    if (!error.code) error.message = "Server unavailable or HTTP response lost. " +
      (method === "GET" ? "Check the server terminal and reload observations." :
       "Submission outcome is UNKNOWN. Do not repeat a modification automatically; inspect recent jobs or query hardware state.");
    throw error;
  } finally { clearTimeout(timeout); }
}

function notice(error) { $("notice").hidden = false; text("notice", error.message || String(error)); }
async function action(operation) {
  if (working) return;
  observationRevision++;
  working = true;
  for (const control of document.querySelectorAll("button,select,input,textarea")) control.disabled = true;
  $("notice").hidden = true;
  try { await operation(); }
  catch (error) { notice(error); }
  finally {
    working = false;
    for (const control of document.querySelectorAll("button,select,input,textarea")) control.disabled = false;
    availability();
  }
}
function button(id, operation) { $(id).addEventListener("click", () => action(operation)); }
function path() { return "/targets/" + encodeURIComponent(current.name); }
function number(id) { return {number:$(id).value.trim()}; }
function selectOptions(element, items) {
  element.replaceChildren();
  for (const [value, label] of items) {
    const option = document.createElement("option"); option.value = value; option.textContent = label;
    element.append(option);
  }
}
function addWire(message) {
  wire.push(message); if (wire.length > 256) wire.shift();
  // The browser display is bounded separately from the server event history.
  while (wire.join("\n").length > 1048576) wire.shift();
  text("wire-log", wire.join("\n"));
  $("wire-log").scrollTop = $("wire-log").scrollHeight;
}

async function loadInventory(preferred) {
  const [inventory, saved] = await Promise.all([api("/targets"), api("/config")]);
  targets = inventory.targets; config = saved;
  const filtered = targets.filter(t => t.kind === $("target-kind").value);
  selectOptions($("target"), [...filtered.map(t => [t.name, t.name]), ["all", "All"]]);
  $("target").value = filtered.some(t => t.name === preferred) || preferred === "all" ? preferred : (filtered[0]?.name || "all");
  await refreshManagement();
  // An explicit inventory reload must refresh the editor and its revision together.
  if (current) renderConfig();
}

async function showTarget() {
  current = targets.find(t => t.name === $("tool-target").value) || null;
  session = null; operationsSession = null;
  wire = []; cursor = 0;
  if (!current) { renderPanels(); return; }
  text("wire-log", "No TCP connection for " + current.name + ".");
  text("response", "No request sent to " + current.name + ".");
  jobId = null; $("monitor").checked = false;
  $("fault-controls").hidden = current.kind !== "simulator";
  $("apply-config").hidden = current.kind !== "simulator";
  $("receiver-controls").hidden = current.model !== "fictitious_receiver";
  selectOptions($("fault"), []); faultCatalog = [];
  text("fault-state", "Not inspected. Refresh explicitly.");
  text("job-state", "No job submitted in this tab for this target");
  text("test-report", "Read-only by default. Inspect recent jobs to find a previous run.");
  renderConfig();
  await refreshAdmin();
  await restoreSession();
  renderPanels();
}

function kindTargets() { return targets.filter(t => t.kind === $("target-kind").value); }
function selectedTargets() {
  return kindTargets().filter(t => $("target").value === "all" || t.name === $("target").value);
}
function availability() {
  const none = !selectedTargets().length;
  for (const id of ["start", "stop", "restart"]) $(id).disabled = working || none;
  for (const id of ["set-frequency", "get-frequency", "general-status", "calibrate", "reboot", "scan", "procedure-status", "cancel", "monitor"])
    $(id).disabled = working || !current || !!session?.exclusive ||
      !!(operationsSession && operationsSession.state !== "connected");
  $("operations-disconnect").disabled = working || !operationsSession;
  $("operations-reconnect").disabled = working || !current || !!session?.exclusive;
  $("connect").disabled = working || !current;
  $("disconnect").disabled = working || !session;
  $("exclusive").disabled = working || !!session;
  $("send-literal").disabled = working || !session || session.state !== "connected";
}
function renderPanels() {
  const panel = workspace;
  for (const button of document.querySelectorAll('[data-workspace]'))
    button.setAttribute('aria-pressed', String(button.dataset.workspace === panel));
  for (const id of ["console-communication", "control", "tests", "configuration"])
    $(id).hidden = !current || (panel === "communication" ? !["console-communication", "control"].includes(id) : panel !== id);
  $("tool-target-group").hidden = !panel;
  text("tool-target-label", panel === "communication" ? "Communication target" : "Target");
  $("workspace-empty").hidden = !panel || !!current;
  if (panel !== "communication") $("monitor").checked = false;
  availability();
}
async function syncTools(preferred) {
  let choices = kindTargets();
  if (workspace === "communication") choices = choices.filter(t => observations.some(r =>
    r.name === t.name && (r.kind === "simulator" ? r.state === "running" :
      r.state === "connected" || t.name === current?.name)));
  const wanted = preferred || current?.name || $("target").value;
  selectOptions($("tool-target"), choices.map(t => [t.name,
    workspace === "communication" && t.kind === "hardware" &&
      observations.find(r => r.name === t.name)?.state !== "connected" ? `${t.name} (disconnected)` : t.name]));
  $("tool-target").value = choices.some(t => t.name === wanted) ? wanted : (choices[0]?.name || "");
  if (current?.name !== ($("tool-target").value || undefined)) await showTarget();
  else { await restoreSession(); renderPanels(); }
}
async function restoreSession() {
  if (!current) return;
  const targetName = current.name;
  const sessions = observations.find(r => r.name === targetName)?.sessions || [];
  operationsSession = sessions.find(s => s.mode === "managed") || null;
  const observed = sessions.find(s => s.mode !== "managed");
  if (!observed) {
    session = null; text("connection-state", "disconnected"); text("session-revision", "");
    renderOperationsState();
    return;
  }
  if (session?.id !== observed.id) {
    session = observed; cursor = 0; wire = [];
    $("mode").value = observed.mode; $("exclusive").checked = observed.exclusive; updateMode();
    const history = await api("/sessions/" + observed.id + "/events");
    if (current?.name !== targetName || session?.id !== observed.id) return;
    consume(history);
  } else session.state = observed.state;
  renderOperationsState();
}
function renderOperationsState() {
  text("operations-state", session?.exclusive ? "Suspended — disconnect the exclusive console to resume operations" :
    operationsSession ? operationsSession.state + " · automatic library connection" :
      "disconnected — connects automatically on your next operation");
  if (session?.exclusive || (operationsSession && operationsSession.state !== "connected")) $("monitor").checked = false;
}
function rememberSession(history) {
  observationRevision++;
  const row = observations.find(r => r.name === history.target);
  if (row) row.sessions = history.exclusive ? [history] :
    [...row.sessions.filter(s => (s.mode === "managed") !== (history.mode === "managed")), history];
}
function renderManagement() {
  const simulator = $("target-kind").value === "simulator";
  text("management-title", simulator ? "Simulator management" : "Connection");
  text("target-label", simulator ? "Target simulator" : "Target hardware");
  for (const [id, caption] of [["start", simulator ? "Start" : "Connect"], ["stop", simulator ? "Stop" : "Disconnect"], ["restart", simulator ? "Restart" : "Reconnect"]]) text(id, caption);
  const names = selectedTargets().map(t => t.name);
  const rows = observations.filter(r => names.includes(r.name));
  const relevantJob = r => r.job && ["start", "stop", "restart", "apply", "connect", "disconnect", "reconnect"].includes(r.job.kind) ? r.job : null;
  function detail(r) {
    const job = relevantJob(r);
    const error = submissionErrors.get(r.name) || r.error || (job?.state === "failed" ? job.error || job.result : null);
    const running = job?.state === "running";
    const active = ["running", "connected"].includes(r.state);
    const icon = error || r.state === "unknown" ? "✕" : running ? "◌" : active ? "✓" : "○";
    const label = running ? `${job.kind}: running…` : r.state;
    return {error, running, active, icon, summary: `${icon} ${r.name}: ${label}`, message: `${icon} ${r.name} ${simulator ? "simulator" : "hardware"}: ${label}` +
      (r.owner ? ` (${r.owner === "gui" ? "managed by GUI" : "external"})` : "") +
      (error ? ` — ${typeof error === "string" ? error : pretty(error)}` : "")};
  }
  const details = $("management-details"); details.replaceChildren();
  for (const row of rows) {
    const state = detail(row), li = document.createElement("li"); li.textContent = state.message;
    li.className = state.error ? "failure" : state.active ? "success" : ""; details.append(li);
  }
  const failed = rows.filter(r => detail(r).error || r.state === "unknown").length;
  const pending = rows.filter(r => detail(r).running).length;
  const allRows = observations.filter(r => r.kind === $("target-kind").value);
  const gui = allRows.filter(r => r.state === "running" && r.owner === "gui").length;
  const external = allRows.filter(r => r.state === "running" && r.owner === "external").length;
  const connected = allRows.filter(r => r.state === "connected").length;
  const countLabel = count => `${count} simulator${count === 1 ? "" : "s"} running`;
  const summary = simulator ? `${countLabel(gui)}, started by this GUI` +
    (external ? ` · ${countLabel(external)}, started externally` : "") : `${connected}/${allRows.length} connected`;
  text("management-status", (rows.length === 1 && $("target").value !== "all" ? detail(rows[0]).summary + " · " : "") +
    summary + (pending ? ` · ${pending} in progress` : "") + (failed ? ` · ${failed} failed — see Details` : ""));
  $("management-status").classList.toggle("failure", failed > 0);
  $("management-status").classList.toggle("success", failed === 0 && gui + external + connected > 0);
}
async function refreshManagement() {
  const revision = observationRevision;
  const result = await api("/management");
  if (revision !== observationRevision) return;
  observations = result.targets;
  renderManagement(); await syncTools();
}
async function manage(operation) {
  const selected = selectedTargets();
  if (!selected.length) return;
  const simulator = $("target-kind").value === "simulator";
  if (operation === "restart" && !confirm(simulator ? "Restart the selected simulators? Current state and fault schedules will be lost." : "Reconnect the selected hardware? Current TCP connections will close.")) return;
  text("management-status", `◌ ${operation}: 0/${selected.length} submitted…`);
  let submitted = 0;
  for (const target of selected) {
    submissionErrors.delete(target.name);
    const verb = simulator ? operation : ({start:"connect", stop:"disconnect", restart:"reconnect"})[operation];
    try {
      await api("/targets/" + encodeURIComponent(target.name) + (simulator ? "/lifecycle" : "/connection"), "POST", {action:verb});
    } catch (error) { submissionErrors.set(target.name, error.message); }
    text("management-status", `◌ ${verb}: ${++submitted}/${selected.length} submitted…`);
  }
  await refreshManagement();
}

function renderConfig() {
  const saved = config.instances.find(t => t.name === current.name);
  if (!saved) throw new Error("Target removed from saved configuration; reload inventory.");
  current = {...current, ...saved};
  text("config-path", config.path + " · revision " + config.revision);
  text("config-source", config.source === "builtin" ? "Built-in defaults — not saved" : "Saved configuration file");
  text("saved-config", pretty(saved));
  const fields = $("config-fields"); fields.replaceChildren();
  function input(key, labelText, value, setting, numeric) {
    const label = document.createElement("label"), field = document.createElement("input");
    field.id = "config-" + key; field.value = String(value); field.dataset.key = key;
    field.dataset.setting = String(setting); field.dataset.numeric = String(numeric);
    field.maxLength = numeric ? 64 : 256;
    field.disabled = working;
    if (numeric) field.inputMode = "decimal";
    label.htmlFor = field.id; label.append(document.createTextNode(labelText), field); fields.append(label);
  }
  input("host", "Saved host", saved.host, false, false);
  input("port", "Saved TCP port", saved.port, false, true);
  const names = {hardware_id:"Expected hardware identity", firmware_version:"Firmware version (simulator)",
    firmware_build:"Firmware build (simulator)", initial_frequency:"Initial frequency (GHz)", tuning_duration_ms:"Tuning duration (ms)",
    stop_duration_ms:"Stop duration (ms)", calibrate_preparation_ms:"Calibration preparation (ms)",
    calibrate_measurement_ms:"Calibration measurement (ms)", calibrate_finalization_ms:"Calibration finalization (ms)"};
  for (const key of current.editable_settings || []) {
    input(key, names[key] || key, saved.receiver[key], true, typeof saved.receiver[key] === "number");
  }
}

async function refreshAdmin() {
  if (!current) return;
  if (current.kind !== "simulator") {
    text("config-state", "Physical hardware: active simulator settings not applicable"); text("active-config", "Not applicable"); return;
  }
  const state = await api(path() + "/admin");
  text("runtime-state", `Process: ${state.state}. Hardware TCP has not been probed by this observation.`);
  text("active-config", pretty(state.active ?? "Unknown / no running verified process"));
  text("config-state", state.state === "running" ? (state.pending ?
    "Pending — saved settings differ from active startup settings. Connect/Tests use the saved endpoint; Apply when ready." : "In sync — saved and active startup settings agree") :
    state.state === "stopped" ? "Stopped — saved settings will be used on Start" : "Active settings unknown — inspect the runtime error below");
  if (state.runtime && !state.runtime.ok) text("active-config", pretty(state.runtime));
  if (state.revision !== config.revision) {
    text("config-state", $("config-state").textContent + " Editor snapshot is stale; Reload saved configuration before saving.");
  }
}

async function reloadConfig() {
  config = await api("/config"); renderConfig(); await refreshAdmin();
}
async function saveConfig() {
  const record = structuredClone(config.instances.find(t => t.name === current.name));
  for (const field of $("config-fields").querySelectorAll("input")) {
    const key = field.dataset.key, isSetting = field.dataset.setting === "true";
    let value = field.value;
    if (field.dataset.numeric === "true") {
      if (isSetting) value = {number:value.trim()};
      else {
        if (!/^[0-9]+$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error("Saved TCP port must be an integer.");
        value = Number(value);
      }
    }
    if (isSetting) record.receiver[key] = value; else record[key] = value;
  }
  config = await api("/config/" + encodeURIComponent(current.name), "PUT", {revision:config.revision, record});
  renderConfig(); await refreshAdmin();
}

async function disconnect() {
  if (!session) { text("connection-state", "disconnected"); return; }
  const previous = session;
  const final = await api("/sessions/" + previous.id, "DELETE", {});
  consume(final); session = null; cursor = 0;
  const row = observations.find(r => r.name === previous.target);
  if (row) row.sessions = row.sessions.filter(s => s.id !== previous.id);
  text("connection-state", "disconnected — hardware procedures were not cancelled");
  text("session-revision", "");
  renderOperationsState();
}
function updateMode() {
  const mode = $("mode").value;
  text("mode-help", mode === "raw" ? "Connect sends zero bytes. Send decodes escapes without adding LF. No probes, IDs, polling or recovery." :
    "Connect sends zero bytes. Send appends LF to literal ASCII text. No probes, IDs, polling or recovery.");
}
function consume(history) {
  if (session?.id === history.id) session.state = history.state;
  if (history.gap) addWire("[history gap: older events were dropped]");
  for (const event of history.events) {
    if (event.cursor <= cursor) continue;
    const detail = event.data || event.message || (event.result ? pretty(event.result) : pretty(event));
    addWire(`${event.observed_at || "local"} [${event.kind}] ${detail}`);
  }
  cursor = history.newest;
  text("connection-state", history.state + " · " + history.mode);
  text("session-revision", `TCP ${history.host}:${history.port} · expected identity: ${history.expected_hardware_id || "not supplied"} ` +
    `(${history.identity_verified ? "verified by managed bootstrap" : "not verified"}) · pinned revision: ${history.revision}. ` +
    (config.revision !== history.revision ? "Newer saved settings are loaded. This connection is not retargeted; reconnect explicitly." : "Save never retargets this connection."));
}
async function connect() {
  if (!current) throw new Error("Select an active target first.");
  const exclusive = $("exclusive").checked;
  if (exclusive && !confirm("Release this GUI server's existing connections to this target and give the console exclusive access? In-flight commands may have an uncertain outcome. Other applications are not disconnected.")) return;
  const history = await api("/sessions", "POST", {target:current.name, mode:$("mode").value, persistent:true, exclusive});
  session = history; cursor = 0;
  consume(history);
  rememberSession(history);
  if (exclusive) operationsSession = null;
  renderOperationsState();
}
async function connectOperations() {
  if (!current || session?.exclusive) throw new Error("Disconnect the exclusive console before using receiver operations.");
  const target = current;
  const history = await api("/sessions", "POST", {target:target.name, mode:"managed", persistent:true});
  if (current !== target) throw new Error("Target changed while connecting; no operation was sent. The connection remains available on the original target.");
  operationsSession = history; rememberSession(history); renderOperationsState();
  return history;
}
async function disconnectOperations() {
  $("monitor").checked = false;
  if (!operationsSession) return;
  const previous = operationsSession;
  await api("/sessions/" + previous.id, "DELETE", {});
  operationsSession = null;
  const row = observations.find(r => r.name === previous.target);
  if (row) row.sessions = row.sessions.filter(s => s.id !== previous.id);
  renderOperationsState();
}
async function request(verb, fields = {}) {
  const target = current;
  const connection = operationsSession || await connectOperations();
  if (current !== target || connection.target !== target?.name) throw new Error("Target changed; no operation was sent.");
  if (session?.exclusive || connection.state !== "connected") throw new Error("Operations connection is unavailable. Wait for recovery or use Reconnect operations.");
  const response = await api("/sessions/" + connection.id + "/requests", "POST", {verb, fields});
  if (current === target && operationsSession?.id === connection.id) text("response", pretty(response));
  return response;
}

async function lifecycle(operation) {
  if ((operation === "restart" || operation === "apply") &&
      !confirm("Restart this simulator using saved settings? Current state and fault schedules may be lost. Other clients may disconnect.")) return;
  await disconnect();
  const result = await api(path() + "/lifecycle", "POST", {action:operation, ...(operation === "apply" ? {revision:config.revision} : {})});
  jobId = result.id; text("job-state", `${operation}: running (${jobId})`);
}
async function runTests() {
  if (session || operationsSession) throw new Error("Disconnect operations and the manual console in Communication before running checks.");
  const allow = $("allow-changes").checked;
  if (allow && !confirm("Run modifying checks on an isolated target? Frequency, calibration, scan and reboot WILL change hardware state.")) return;
  const result = await api(path() + "/tests", "POST", {allow_changes:allow});
  $("allow-changes").checked = false;
  jobId = result.id; text("job-state", "tests: running (" + jobId + ")"); text("test-report", "Checks started. Polling only reads job progress.");
}
async function refreshFaults() {
  const result = await api(path() + "/faults"); faultCatalog = result.catalog;
  const old = $("fault").value;
  selectOptions($("fault"), faultCatalog.map(f => [f.name, f.name]));
  if (faultCatalog.some(f => f.name === old)) $("fault").value = old;
  showFault(); text("fault-state", pretty(result.state ?? "Simulator stopped"));
}
function showFault() {
  const fault = faultCatalog.find(f => f.name === $("fault").value);
  text("fault-description", fault ? pretty(fault) : "Refresh the catalog first.");
  selectOptions($("fault-when"), (fault?.events || []).map(e => [e, e]));
}
async function fault(actionName) {
  const arguments_ = actionName === "cancel" ? {rule_id:$("rule-id").value} : {name:$("fault").value};
  if (actionName === "schedule") {
    if (!/^[0-9]+$/.test($("fault-times").value)) throw new Error("Occurrences must be an integer.");
    arguments_.when = $("fault-when").value; arguments_.times = Number($("fault-times").value);
    if (arguments_.name === "delay_response") arguments_.parameters = {delay_ms:Number($("fault-delay").value)};
  }
  const result = await api(path() + "/faults", "POST", {action:actionName, arguments:arguments_});
  if (result.rule_id) $("rule-id").value = result.rule_id;
  await refreshFaults();
}

async function poll() {
  if (polling) return; polling = true;
  try {
    const oldSession = session;
    if (oldSession) {
      try {
        const history = await api("/sessions/" + oldSession.id + "/events?after=" + cursor);
        if (session?.id === oldSession.id) {
          consume(history);
        }
      } catch (error) {
        if (error.code === "UNKNOWN_SESSION" && session?.id === oldSession.id) {
          session = null; text("connection-state", "expired/disconnected — reconnect explicitly");
        }
        notice(error);
      }
    }
    if (jobId) {
      const observed = jobId;
      const job = await api("/jobs/" + observed);
      if (jobId !== observed) return;
      text("job-state", `${job.kind}: ${job.state} (${job.id})`);
      if (job.kind === "tests") text("test-report", pretty(job));
      if (job.state !== "running") {
        jobId = null;
        if (job.kind !== "tests") { await refreshAdmin(); if (job.error || job.result?.ok === false) notice(new Error(pretty(job.error || job.result))); }
      }
    }
    if ($("monitor").checked && !session?.exclusive && !working && !monitoring) {
      monitoring = true;
      try { await request("status", {name:$("procedure").value}); }
      catch (error) { $("monitor").checked = false; notice(error); }
      finally { monitoring = false; }
    }
  } catch (error) { notice(error); }
  finally { polling = false; }
}

button("connect", connect); button("disconnect", disconnect);
button("operations-disconnect", disconnectOperations);
button("operations-reconnect", async () => { await disconnectOperations(); await connectOperations(); });
button("start", () => manage("start")); button("stop", () => manage("stop")); button("restart", () => manage("restart"));
button("refresh-admin", async () => { await refreshManagement(); await refreshAdmin(); });
button("set-frequency", () => request("set", {name:"frequency", value:number("frequency"), unit:"GHz"}));
button("get-frequency", () => request("get", {name:"frequency"})); button("general-status", () => request("status"));
button("calibrate", () => { $("procedure").value = "calibrate"; return request("run", {name:"calibrate"}); });
button("scan", () => { $("procedure").value = "scan"; return request("run", {name:"scan", start:number("scan-start"), stop:number("scan-stop"), unit:"GHz", dwell_ms:number("scan-dwell")}); });
button("procedure-status", () => request("status", {name:$("procedure").value})); button("cancel", () => request("cancel", {name:$("procedure").value}));
button("reboot", () => confirm("Reboot hardware? Existing TCP connections will close and running work may be lost.") ? request("reboot") : undefined);
button("send-literal", async () => {
  if (!session || session.mode === "managed") throw new Error("Connect in Line or Raw mode first.");
  await api("/sessions/" + session.id + "/requests", "POST", {text:$("literal").value});
});
button("clear-log", () => { wire = []; text("wire-log", "Display cleared; server evidence is retained within its limits."); });
button("reload", () => loadInventory(current?.name));
button("reload-config", reloadConfig); button("apply-config", () => lifecycle("apply")); button("run-tests", runTests);
button("recent-jobs", async () => { const result = await api(path() + "/jobs"); text("test-report", pretty(result)); });
button("refresh-faults", refreshFaults);
button("activate-fault", () => fault("activate")); button("clear-fault", () => fault("clear"));
button("schedule-fault", () => fault("schedule")); button("cancel-rule", () => fault("cancel"));
$("fault").addEventListener("change", showFault);
$("config-form").addEventListener("submit", event => { event.preventDefault(); action(saveConfig); });
$("mode").addEventListener("change", () => action(async () => {
  try { await disconnect(); updateMode(); }
  catch (error) { if (session) $("mode").value = session.mode; throw error; }
}));
$("target").addEventListener("change", () => action(async () => {
  renderManagement(); await syncTools($("target").value === "all" ? undefined : $("target").value);
}));
$("target-kind").addEventListener("change", () => action(async () => {
  // Selecting a category observes existing resources; it never connects hardware.
  localStorage.setItem("synqaro-target-kind", $("target-kind").value);
  session = null; operationsSession = null; current = null; await loadInventory();
}));
for (const button of document.querySelectorAll('[data-workspace]'))
  button.addEventListener('click', () => action(async () => {
    workspace = button.dataset.workspace;
    await syncTools();
  }));
$("tool-target").addEventListener("change", () => action(showTarget));
$("monitor").addEventListener("change", () => {
  if ($("monitor").checked && session?.exclusive) {
    $("monitor").checked = false; notice(new Error("Disconnect the exclusive console before monitoring operations."));
  }
});
setInterval(poll, 500);
setInterval(() => {
  if (working || observing) return;
  observing = true;
  refreshManagement().catch(error => {
    text("management-status", "State unavailable — check the GUI server and Refresh. Previous observations are not current.");
    notice(error);
  }).finally(() => { observing = false; });
}, 1000);
if (localStorage.getItem("synqaro-target-kind") === "hardware") $("target-kind").value = "hardware";
action(() => loadInventory());
