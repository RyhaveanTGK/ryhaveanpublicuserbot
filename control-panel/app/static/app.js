const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.("secondary_bg_color");
}

const state = {
  initData: tg?.initData || "",
  profile: null,
  timer: null,
};

const els = {
  form: document.getElementById("credentialForm"),
  deployBtn: document.getElementById("deployBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  statusText: document.getElementById("statusText"),
  logList: document.getElementById("logList"),
  serviceUrlWrap: document.getElementById("serviceUrlWrap"),
  profileBadge: document.getElementById("profileBadge"),
  serviceName: document.getElementById("serviceName"),
};

function notify(message, isError = false) {
  if (tg?.showAlert) tg.showAlert(message);
  else window.alert(message);
  console[isError ? "error" : "log"](message);
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || "Server xətası");
  }
  return data;
}

function renderLogs(items = []) {
  if (!items.length) {
    els.logList.innerHTML = '<div class="log-item"><strong>Hazırdır</strong><div>Hələ log yoxdur.</div></div>';
    return;
  }
  els.logList.innerHTML = items.map(item => {
    const level = item.level || "info";
    const title = level.toUpperCase();
    const time = item.created_at ? new Date(item.created_at).toLocaleString() : "";
    return `<div class="log-item ${level}"><strong>${title}</strong><div>${item.message || ""}</div><small>${time}</small></div>`;
  }).join("");
}

function renderStatus(data) {
  els.statusText.textContent = data.status || "idle";
  if (data.service_url) {
    els.serviceUrlWrap.innerHTML = `<a href="${data.service_url}" target="_blank" rel="noreferrer">${data.service_url}</a>`;
  } else {
    els.serviceUrlWrap.textContent = data.summary || "";
  }
  renderLogs(data.logs || []);
}

async function loadProfile() {
  if (!state.initData) {
    els.profileBadge.textContent = "Telegram içindən aç";
    renderLogs([{ level: "warning", message: "Mini app Telegram daxilindən açılmalıdır.", created_at: new Date().toISOString() }]);
    return;
  }
  const profile = await api("/api/profile", { init_data: state.initData });
  state.profile = profile;
  els.profileBadge.textContent = `@${profile.username || profile.first_name || profile.telegram_id}`;
  els.serviceName.placeholder = profile.service_name || `ryhavean-userbot-${profile.telegram_id}`;
  await refreshStatus();
}

async function refreshStatus() {
  if (!state.initData) return;
  const data = await api("/api/deploy-status", { init_data: state.initData });
  renderStatus(data);
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const form = new FormData(els.form);
    await api("/api/save-credentials", {
      init_data: state.initData,
      render_api_key: form.get("render_api_key"),
      api_id: Number(form.get("api_id")),
      api_hash: form.get("api_hash"),
      session_string: form.get("session_string"),
      mongodb_uri: form.get("mongodb_uri") || null,
      cmd_prefix: form.get("cmd_prefix") || ".",
      app_base_url: form.get("app_base_url") || null,
    });
    notify("Məlumatlar saxlanıldı");
    await refreshStatus();
  } catch (error) {
    notify(error.message, true);
  }
});

els.deployBtn.addEventListener("click", async () => {
  try {
    await api("/api/deploy", {
      init_data: state.initData,
      service_name: els.serviceName.value || null,
    });
    notify("Deploy başladıldı");
    clearInterval(state.timer);
    state.timer = setInterval(refreshStatus, 4000);
    await refreshStatus();
  } catch (error) {
    notify(error.message, true);
  }
});

els.refreshBtn.addEventListener("click", async () => {
  try {
    await refreshStatus();
  } catch (error) {
    notify(error.message, true);
  }
});

loadProfile().catch((error) => {
  notify(error.message, true);
});
