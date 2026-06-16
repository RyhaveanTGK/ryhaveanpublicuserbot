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
  sendCodeBtn: document.getElementById("sendCodeBtn"),
  verifyCodeBtn: document.getElementById("verifyCodeBtn"),
  statusText: document.getElementById("statusText"),
  logList: document.getElementById("logList"),
  serviceUrlWrap: document.getElementById("serviceUrlWrap"),
  profileBadge: document.getElementById("profileBadge"),
  serviceName: document.getElementById("serviceName"),
  phoneNumber: document.getElementById("phoneNumber"),
  phoneCode: document.getElementById("phoneCode"),
  passwordWrap: document.getElementById("passwordWrap"),
  twoFactorPassword: document.getElementById("twoFactorPassword"),
  sessionString: document.getElementById("sessionString"),
  sessionStatus: document.getElementById("sessionStatus"),
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
    const error = new Error(data.detail || data.message || "Server xətası");
    error.status = res.status;
    error.data = data;
    throw error;
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

function updateSessionStatus(message, ready = false) {
  els.sessionStatus.textContent = message;
  els.sessionStatus.style.color = ready ? "#22c55e" : "";
}

function normalizePhoneCode(value = "") {
  return value.replace(/\D/g, "").slice(0, 6);
}

function formatPhoneCode(value = "") {
  return normalizePhoneCode(value).split("").join(" ");
}

function bindPhoneCodeFormatter() {
  const input = els.phoneCode;
  if (!input) return;

  input.addEventListener("beforeinput", (event) => {
    const raw = input.value;
    const normalized = normalizePhoneCode(raw);
    const hasSelection = input.selectionStart !== input.selectionEnd;

    if (event.inputType === "deleteContentBackward" && !hasSelection) {
      const cursor = input.selectionStart ?? raw.length;
      if (cursor > 0 && raw[cursor - 1] === " ") {
        const newDigits = normalized.slice(0, -1);
        input.value = formatPhoneCode(newDigits);
        const pos = input.value.length;
        input.setSelectionRange(pos, pos);
        event.preventDefault();
      }
    }
  });

  input.addEventListener("input", () => {
    const formatted = formatPhoneCode(input.value);
    input.value = formatted;
    const pos = formatted.length;
    input.setSelectionRange(pos, pos);
  });

  input.addEventListener("paste", (event) => {
    event.preventDefault();
    const pasted = event.clipboardData?.getData("text") || "";
    const formatted = formatPhoneCode(pasted);
    input.value = formatted;
    const pos = formatted.length;
    input.setSelectionRange(pos, pos);
  });
}

function currentApiCredentials() {
  const form = new FormData(els.form);
  return {
    api_id: Number(form.get("api_id")),
    api_hash: form.get("api_hash")?.toString().trim(),
  };
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

els.sendCodeBtn.addEventListener("click", async () => {
  try {
    const creds = currentApiCredentials();
    if (!creds.api_id || !creds.api_hash) {
      throw new Error("Əvvəlcə API ID və API Hash doldur");
    }
    await api("/api/telegram/send-code", {
      init_data: state.initData,
      api_id: creds.api_id,
      api_hash: creds.api_hash,
      phone_number: els.phoneNumber.value,
    });
    els.passwordWrap.style.display = "none";
    els.twoFactorPassword.value = "";
    updateSessionStatus("Kod göndərildi. İndi Telegram kodunu daxil et.");
    notify("Telegram kodu göndərildi");
  } catch (error) {
    notify(error.message, true);
  }
});

els.verifyCodeBtn.addEventListener("click", async () => {
  try {
    if (!els.phoneCode.value.trim()) {
      throw new Error("Telegram kodunu daxil et");
    }
    const normalizedCode = normalizePhoneCode(els.phoneCode.value);
    if (!normalizedCode) {
      throw new Error("Telegram kodunu daxil et");
    }
    const data = await api("/api/telegram/verify-code", {
      init_data: state.initData,
      code: normalizedCode,
      password: els.twoFactorPassword.value.trim() || null,
    });
    els.sessionString.value = data.session_string || "";
    els.passwordWrap.style.display = "none";
    els.twoFactorPassword.value = "";
    updateSessionStatus(`Hazırdır: ${data.account?.phone || "StringSession yaradıldı"}`, true);
    notify("StringSession uğurla yaradıldı");
  } catch (error) {
    if (error.data?.password_required) {
      els.passwordWrap.style.display = "block";
      updateSessionStatus("2FA aktivdir. Telegram Cloud Password daxil et.");
    }
    notify(error.message, true);
  }
});

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const form = new FormData(els.form);
    if (!els.sessionString.value.trim()) {
      throw new Error("Əvvəlcə telefon kodunu təsdiqləyib StringSession yarat");
    }
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

bindPhoneCodeFormatter();

loadProfile().catch((error) => {
  notify(error.message, true);
});
