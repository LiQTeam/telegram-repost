/*
 * ثابت‌ها و توابعِ کمکیِ مشترک بینِ background.js و popup.js/options.js.
 * این فایل import می‌شه (به‌جای کپی‌پیستِ همون کد توی چند فایل) تا نگه‌داری
 * راحت‌تر باشه.
 */

export const STORAGE_KEYS = {
  serverUrl: "ug_server_url",       // مثلاً http://1.2.3.4:8843
  token: "ug_token",
  enabledRefs: "ug_enabled_refs",   // آخرین لیستِ منابعِ فعال (از سرور)
  lastError: "ug_last_error",
  lastSyncAt: "ug_last_sync_at",
  connectionOk: "ug_connection_ok",
  queueCount: "ug_queue_count",     // تعدادِ پست‌هایی که هنوز در صفِ ارسال هستن
  fullQualityMode: "ug_full_quality_mode",
};

export const DEFAULTS = {
  fullQualityMode: true,
};

export const ENDPOINTS = {
  ping: "/api/ext/ping",
  tabs: "/api/ext/tabs",
  post: "/api/ext/post",
  sources: "/api/ext/sources",
};

export function normalizeServerUrl(raw) {
  return (raw || "").trim().replace(/\/+$/, "");
}

export async function getConfig() {
  const res = await chrome.storage.local.get([
    STORAGE_KEYS.serverUrl,
    STORAGE_KEYS.token,
    STORAGE_KEYS.fullQualityMode,
  ]);
  return {
    serverUrl: normalizeServerUrl(res[STORAGE_KEYS.serverUrl]),
    token: res[STORAGE_KEYS.token] || "",
    fullQualityMode: res[STORAGE_KEYS.fullQualityMode] ?? DEFAULTS.fullQualityMode,
  };
}

/** فراخوانیِ fetch با تایم‌اوت (AbortController) - جلوی هنگ‌کردنِ درخواست به
 * سروری که اصلاً جواب نمی‌ده رو می‌گیره. */
export async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}
