import { STORAGE_KEYS, normalizeServerUrl } from "./common.js";

const $url = document.getElementById("serverUrl");
const $token = document.getElementById("token");
const $toggleToken = document.getElementById("toggleToken");
const $save = document.getElementById("save");
const $testBtn = document.getElementById("testBtn");
const $statusBox = document.getElementById("statusBox");
const $statusDot = document.getElementById("statusDot");
const $fullQuality = document.getElementById("fullQuality");
const $sourcesSection = document.getElementById("sourcesSection");
const $sourcesList = document.getElementById("sourcesList");
const $refreshSources = document.getElementById("refreshSources");

function setDot(state) {
  $statusDot.className = "dot " + (state === "ok" ? "dot-ok" : state === "err" ? "dot-err" : "dot-unknown");
}

function renderStatus({ ok, message, lastSyncAt, queueCount }) {
  const parts = [];
  if (ok === true) {
    parts.push(`<span class="ok">✅ متصل</span>`);
    setDot("ok");
  } else if (ok === false) {
    parts.push(`<span class="err">⚠️ ${message || "خطا"}</span>`);
    setDot("err");
  } else {
    parts.push(`<span class="muted">وضعیت نامشخص - تستِ اتصال رو بزن</span>`);
    setDot("unknown");
  }
  if (queueCount) {
    parts.push(`<span class="muted">📦 ${queueCount} پست در صفِ ارسال</span>`);
  }
  if (lastSyncAt) {
    const d = new Date(lastSyncAt);
    parts.push(`<span class="muted">آخرین به‌روزرسانی: ${d.toLocaleTimeString("fa-IR")}</span>`);
  }
  $statusBox.innerHTML = parts.join("<br>");
}

function renderSources(sources) {
  if (!sources || sources.length === 0) {
    $sourcesSection.classList.remove("hidden");
    $sourcesList.innerHTML = `<div class="empty-hint">هنوز گروهی شناسایی نشده - یک تبِ تلگرام‌وب باز نگه‌دار.</div>`;
    return;
  }
  $sourcesSection.classList.remove("hidden");
  $sourcesList.innerHTML = sources.map((s) => {
    const dotClass = s.active ? "active" : "pending";
    const tag = s.active ? "فعال" : "در انتظارِ تایید";
    return `<li><span class="src-dot ${dotClass}"></span><span class="src-title">${escapeHtml(s.title || s.ref)}</span><span class="src-tag">${tag}</span></li>`;
  }).join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function loadSources() {
  const res = await chrome.runtime.sendMessage({ type: "UG_FETCH_SOURCES" }).catch(() => null);
  if (res && res.ok) renderSources(res.sources);
}

async function load() {
  const res = await chrome.storage.local.get([
    STORAGE_KEYS.serverUrl,
    STORAGE_KEYS.token,
    STORAGE_KEYS.connectionOk,
    STORAGE_KEYS.lastError,
    STORAGE_KEYS.lastSyncAt,
    STORAGE_KEYS.queueCount,
    STORAGE_KEYS.fullQualityMode,
  ]);
  $url.value = res[STORAGE_KEYS.serverUrl] || "";
  $token.value = res[STORAGE_KEYS.token] || "";
  $fullQuality.checked = res[STORAGE_KEYS.fullQualityMode] ?? true;

  const ok = res[STORAGE_KEYS.connectionOk];
  renderStatus({
    ok: ok === undefined ? null : ok,
    message: res[STORAGE_KEYS.lastError],
    lastSyncAt: res[STORAGE_KEYS.lastSyncAt],
    queueCount: res[STORAGE_KEYS.queueCount],
  });

  if (res[STORAGE_KEYS.serverUrl] && res[STORAGE_KEYS.token]) {
    loadSources();
  }
}

$toggleToken.addEventListener("click", () => {
  $token.type = $token.type === "password" ? "text" : "password";
});

$save.addEventListener("click", async () => {
  const serverUrl = normalizeServerUrl($url.value);
  const token = $token.value.trim();
  await chrome.storage.local.set({
    [STORAGE_KEYS.serverUrl]: serverUrl,
    [STORAGE_KEYS.token]: token,
  });
  $statusBox.innerHTML = `<span class="ok">✅ ذخیره شد</span>`;
  setDot("unknown");
});

$testBtn.addEventListener("click", async () => {
  $testBtn.disabled = true;
  $testBtn.textContent = "در حالِ تست...";
  // مقادیرِ فرم رو قبل از تست ذخیره کن تا همون‌چیزی که کاربر تایپ کرده تست بشه
  await chrome.storage.local.set({
    [STORAGE_KEYS.serverUrl]: normalizeServerUrl($url.value),
    [STORAGE_KEYS.token]: $token.value.trim(),
  });
  const result = await chrome.runtime.sendMessage({ type: "UG_TEST_CONNECTION" }).catch((e) => ({
    ok: false, message: "ارتباط با اکستنشن برقرار نشد",
  }));
  renderStatus({ ok: result.ok, message: result.message, lastSyncAt: Date.now() });
  $testBtn.disabled = false;
  $testBtn.textContent = "تستِ اتصال";
  if (result.ok) loadSources();
});

$fullQuality.addEventListener("change", async () => {
  await chrome.storage.local.set({ [STORAGE_KEYS.fullQualityMode]: $fullQuality.checked });
});

$refreshSources.addEventListener("click", loadSources);

load();
