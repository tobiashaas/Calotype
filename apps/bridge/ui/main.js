// Status window. Talks to the Rust side via Tauri commands (no network access here).
const { invoke } = window.__TAURI__.core;

const $ = (id) => document.getElementById(id);
const LABELS = {
  pending: "waiting",
  uploaded: "uploaded",
  waiting_for_photos: "waiting for photos",
  queued: "queued",
  running: "running",
  completed: "done",
  failed: "failed",
};

let urlEdited = false;

function renderCounts(el, pairs) {
  el.replaceChildren();
  if (!pairs.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "nothing yet";
    el.append(li);
    return;
  }
  for (const [status, count] of pairs) {
    const li = document.createElement("li");
    li.dataset.status = status;
    const name = document.createElement("span");
    name.textContent = LABELS[status] ?? status;
    const num = document.createElement("strong");
    num.textContent = count;
    li.append(name, num);
    el.append(li);
  }
}

async function refresh() {
  try {
    const s = await invoke("bridge_status");
    $("bridge").textContent = `running on 127.0.0.1:${s.port}`;
    $("api-dot").dataset.ok = s.api_reachable;
    $("api-state").textContent = s.api_reachable ? "reachable" : "not reachable — requests wait in the queue";
    if (!urlEdited) $("api-url").value = s.api_base_url;
    renderCounts($("photos"), s.photos);
    renderCounts($("jobs"), s.jobs);
    $("version").textContent = `v${s.version}`;
    $("data-dir").textContent = s.data_dir;
  } catch (err) {
    $("bridge").textContent = `error: ${err}`;
  }
}

$("api-url").addEventListener("input", () => (urlEdited = true));

$("api-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("api-msg");
  try {
    await invoke("set_api_base_url", { url: $("api-url").value });
    urlEdited = false;
    msg.dataset.kind = "ok";
    msg.textContent = "Saved.";
    refresh();
  } catch (err) {
    msg.dataset.kind = "error";
    msg.textContent = String(err);
  }
});

$("retry").addEventListener("click", async () => {
  await invoke("retry_now");
  refresh();
});

refresh();
setInterval(refresh, 2000);
