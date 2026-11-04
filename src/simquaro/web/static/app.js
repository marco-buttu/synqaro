"use strict";

const $ = (id) => document.getElementById(id);
const pretty = (value) => JSON.stringify(value, null, 2);
const text = (id, value) => { $(id).textContent = value; };
let targets = [], config = null, current = null, session = null, cursor = 0;
let wire = [], jobId = null, working = false, polling = false, monitoring = false;
let faultCatalog = [];

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
  working = true;
  for (const control of document.querySelectorAll("button,select,input,textarea")) control.disabled = true;
  $("notice").hidden = true;
  try { await operation(); }
  catch (error) { notice(error); }
  finally {
    working = false;
    for (const control of document.querySelectorAll("button,select,input,textarea")) control.disabled = false;
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
  selectOptions($("target"), targets.map(t => [t.name, `${t.name} · ${t.kind}`]));
  if (!targets.length) throw new Error("No targets configured. Add an instance to the configuration file, then Reload inventory.");
  $("target").value = targets.some(t => t.name === preferred) ? preferred : targets[0].name;
  await showTarget();
}

async function showTarget() {
  current = targets.find(t => t.name === $("target").value);
  wire = []; cursor = 0;
  text("wire-log", "No TCP connection for " + current.name + ".");
  text("response", "No request sent to " + current.name + ".");
  jobId = null; $("monitor").checked = false;
  renderTargetHeader();
  $("simulator-controls").hidden = current.kind !== "simulator";
  $("fault-controls").hidden = current.kind !== "simulator";
  $("apply-config").hidden = current.kind !== "simulator";
  $("receiver-controls").hidden = current.model !== "fictitious_receiver";
  selectOptions($("fault"), []); faultCatalog = [];
  text("fault-state", "Not inspected. Refresh explicitly.");
  text("job-state", "No job submitted in this tab for this target");
  text("test-report", "Read-only by default. Inspect recent jobs to find a previous run.");
  renderConfig();
  await refreshAdmin();
}

function renderTargetHeader() {
  text("target-description", `${current.kind === "simulator" ? "Simulator" : "Physical hardware"} / ${current.model}`);
  text("target-endpoint", `Saved endpoint (editor snapshot): ${current.host}:${current.port} · expected identity: ${current.receiver?.hardware_id || "model-defined"}`);
}

function renderConfig() {
  const saved = config.instances.find(t => t.name === current.name);
  if (!saved) throw new Error("Target removed from saved configuration; reload inventory.");
  current = {...current, ...saved};
  renderTargetHeader();
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
  $("monitor").checked = false;
  if (!session) { text("connection-state", "disconnected"); return; }
  const previous = session;
  const final = await api("/sessions/" + previous.id, "DELETE", {});
  consume(final); session = null; cursor = 0;
  text("connection-state", "disconnected — hardware procedures were not cancelled");
  text("session-revision", "");
}
function updateMode() {
  const mode = $("mode").value;
  $("literal-controls").hidden = mode === "managed";
  text("mode-help", mode === "managed" ? "Connect sends configuration/status probes; IDs and recovery are handled by the shared client." :
    mode === "raw" ? "Connect sends zero bytes. Send decodes escapes without adding LF. No probes, IDs, polling or recovery." :
    "Connect sends zero bytes. Send appends LF to literal ASCII text. No probes, IDs, polling or recovery.");
}
function consume(history) {
  if (history.gap) addWire("[history gap: older events were dropped]");
  for (const event of history.events) {
    if (event.cursor <= cursor) continue;
    const detail = event.data || event.message || (event.result ? pretty(event.result) : pretty(event));
    addWire(`${event.observed_at || "local"} [${event.kind}] ${detail}`);
    if (event.kind === "response") text("response", pretty(event.result));
  }
  cursor = history.newest;
  text("connection-state", history.state + " · " + history.mode);
  text("session-revision", `TCP ${history.host}:${history.port} · expected identity: ${history.expected_hardware_id || "not supplied"} ` +
    `(${history.identity_verified ? "verified by managed bootstrap" : "not verified"}) · pinned revision: ${history.revision}. ` +
    (config.revision !== history.revision ? "Newer saved settings are loaded. This connection is not retargeted; reconnect explicitly." : "Save never retargets this connection."));
}
async function connect() {
  if (session) await disconnect();
  const history = await api("/sessions", "POST", {target:current.name, mode:$("mode").value});
  session = {id:history.id, target:current.name, revision:history.revision, mode:history.mode}; cursor = 0;
  consume(history);
}
async function request(verb, fields = {}) {
  if (!session || session.mode !== "managed") throw new Error("Connect in Guided mode to use receiver operations.");
  const response = await api("/sessions/" + session.id + "/requests", "POST", {verb, fields});
  text("response", pretty(response));
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
  if (session) throw new Error("Disconnect this target's GUI connections before running checks.");
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
          session = null; $("monitor").checked = false; text("connection-state", "expired/disconnected — reconnect explicitly");
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
    if ($("monitor").checked && session?.mode === "managed" && !working && !monitoring) {
      monitoring = true;
      try { await request("status", {name:$("procedure").value}); }
      catch (error) { $("monitor").checked = false; notice(error); }
      finally { monitoring = false; }
    }
  } catch (error) { notice(error); }
  finally { polling = false; }
}

button("connect", connect); button("disconnect", disconnect);
button("start", () => lifecycle("start")); button("stop", () => lifecycle("stop")); button("restart", () => lifecycle("restart"));
button("refresh-admin", refreshAdmin);
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
button("reload", async () => { if (session) await disconnect(); await loadInventory(current?.name); });
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
  try { await disconnect(); await showTarget(); }
  catch (error) { if (current) $("target").value = current.name; throw error; }
}));
$("monitor").addEventListener("change", () => {
  if ($("monitor").checked && (!session || session.mode !== "managed")) {
    $("monitor").checked = false; notice(new Error("Connect in Guided mode before enabling monitoring."));
  }
});
window.addEventListener("pagehide", () => {
  if (session) fetch("/api/sessions/" + session.id, {method:"DELETE", keepalive:true,
    headers:{"Content-Type":"application/json", "X-Simquaro-Client":"1"}, body:"{}"}).catch(() => {});
});
setInterval(poll, 500);
setInterval(() => {
  if (session) api("/sessions/" + session.id + "/heartbeat", "POST", {}).catch(notice);
}, 10000);
action(() => loadInventory());
