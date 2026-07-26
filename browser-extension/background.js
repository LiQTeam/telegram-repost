/*
 * Service Worker (Manifest V3).
 *
 * چرا همه‌ی درخواست‌های شبکه از اینجا می‌رن (نه از content.js)؟
 * چون سرورِ ربات فقط IP داره (بدونِ گواهیِ SSL) و درخواست‌های شبکه‌ای از
 * داخلِ خودِ صفحه‌ی https://web.telegram.org ممکنه توسطِ مرورگر به‌عنوانِ
 * mixed content بلاک بشن؛ درخواست‌هایی که از سرویس‌ورکر می‌رن این محدودیت
 * رو ندارن.
 *
 * ویژگی‌های این نسخه نسبت به نسخه‌ی قبل:
 *   - صفِ پایدار (persisted queue) برای پست‌هایی که موقعِ ارسال، سرور در
 *     دسترس نبوده - به‌جای از دست رفتن، بعداً خودکار دوباره امتحان می‌شن.
 *   - backoff نمایی برای تلاشِ مجدد (به‌جای اسپم‌کردنِ سرور در قطعیِ شبکه).
 *   - وضعیتِ اتصال (badge رنگی + پیام) که پاپ‌آپ می‌تونه لحظه‌ای بخونه.
 *   - تابعِ تستِ اتصال (ping) که هم زنده‌بودنِ سرور و هم صحتِ توکن رو چک می‌کنه.
 */

import { STORAGE_KEYS, ENDPOINTS, getConfig, fetchWithTimeout } from "./common.js";

const QUEUE_KEY = "ug_upload_queue";      // آرایه‌ای از پست‌های در انتظار
const QUEUE_ALARM = "ug_flush_queue";
const TABS_ALARM = "ug_flush_tabs";
const MAX_QUEUE_ITEMS = 200;              // جلوگیری از پرشدنِ بی‌حدِ storage
const MAX_RETRY_BACKOFF_MIN = 10;

let _tabReportQueue = new Map(); // ref -> title
let _tabsFlushTimer = null;
let _queueRetryCount = 0;

// ---------------- وضعیت/نشانگر ----------------

async function setStatus({ ok, message }) {
  await chrome.storage.local.set({
    [STORAGE_KEYS.connectionOk]: !!ok,
    [STORAGE_KEYS.lastError]: ok ? "" : (message || "خطای نامشخص"),
    [STORAGE_KEYS.lastSyncAt]: Date.now(),
  });
  await chrome.action.setBadgeText({ text: ok ? "" : "!" });
  await chrome.action.setBadgeBackgroundColor({ color: ok ? "#3a3" : "#d33" });
}

async function setQueueCount(n) {
  await chrome.storage.local.set({ [STORAGE_KEYS.queueCount]: n });
}

// ---------------- صفِ آپلودِ پایدار ----------------

async function readQueue() {
  const res = await chrome.storage.local.get(QUEUE_KEY);
  return res[QUEUE_KEY] || [];
}

async function writeQueue(items) {
  const trimmed = items.slice(-MAX_QUEUE_ITEMS);
  await chrome.storage.local.set({ [QUEUE_KEY]: trimmed });
  await setQueueCount(trimmed.length);
}

async function enqueuePost(item) {
  const queue = await readQueue();
  queue.push({ ...item, queuedAt: Date.now(), attempts: 0 });
  await writeQueue(queue);
}

function dataUrlToBlob(dataUrl) {
  const [meta, b64] = dataUrl.split(",");
  const mimeMatch = /data:(.*?);base64/.exec(meta);
  const mime = mimeMatch ? mimeMatch[1] : "application/octet-stream";
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

async function sendPostToServer(serverUrl, token, item) {
  const form = new FormData();
  form.append("ref", item.ref);
  form.append("text", item.text || "");
  let idx = 0;
  for (const media of item.media || []) {
    const blob = dataUrlToBlob(media.dataUrl);
    const ext = media.kind === "video" ? "mp4" : "jpg";
    form.append("files", blob, `media_${idx++}.${ext}`);
  }
  const resp = await fetchWithTimeout(
    `${serverUrl}${ENDPOINTS.post}`,
    { method: "POST", headers: { "X-Ext-Token": token }, body: form },
    30000,
  );
  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new Error(`سرور خطا داد (${resp.status}): ${body.slice(0, 150)}`);
  }
  return resp.json().catch(() => ({}));
}

/** یک پست رو فوری امتحان می‌کنه؛ اگه شکست خورد، توی صفِ پایدار می‌ذاره تا
 * alarm بعدی دوباره امتحانش کنه (به‌جای از دست رفتنِ کامل). */
async function uploadPost(ref, text, media) {
  const { serverUrl, token } = await getConfig();
  if (!serverUrl || !token) {
    await setStatus({ ok: false, message: "سرور/توکن تنظیم نشده - از پاپ‌آپ تنظیم کن" });
    return;
  }
  try {
    await sendPostToServer(serverUrl, token, { ref, text, media });
    await setStatus({ ok: true });
  } catch (e) {
    console.warn("[UploadGram] ارسالِ فوریِ پست شکست خورد، به صف اضافه شد:", e);
    await enqueuePost({ ref, text, media });
    await setStatus({ ok: false, message: "اتصال برقرار نشد؛ پست در صفِ ارسالِ مجدد قرار گرفت" });
    scheduleQueueRetry();
  }
}

async function flushUploadQueue() {
  const queue = await readQueue();
  if (queue.length === 0) {
    _queueRetryCount = 0;
    return;
  }
  const { serverUrl, token } = await getConfig();
  if (!serverUrl || !token) return;

  const remaining = [];
  let anyFailed = false;
  for (const item of queue) {
    try {
      await sendPostToServer(serverUrl, token, item);
    } catch (e) {
      item.attempts = (item.attempts || 0) + 1;
      // بعد از ۲۰ تلاشِ ناموفق (چند ساعت با backoff)، از صف حذف میشه تا برای
      // همیشه بلاک نکنه - ولی توی status هشدار داده میشه.
      if (item.attempts < 20) {
        remaining.push(item);
      }
      anyFailed = true;
    }
  }
  await writeQueue(remaining);
  if (anyFailed) {
    await setStatus({ ok: false, message: `${remaining.length} پست هنوز در صفِ ارسال هستن` });
    scheduleQueueRetry();
  } else {
    await setStatus({ ok: true });
    _queueRetryCount = 0;
  }
}

function scheduleQueueRetry() {
  _queueRetryCount = Math.min(_queueRetryCount + 1, 10);
  const delayMin = Math.min(2 ** _queueRetryCount * 0.25, MAX_RETRY_BACKOFF_MIN);
  chrome.alarms.create(QUEUE_ALARM, { delayInMinutes: delayMin });
}

// ---------------- گزارشِ تب‌های باز ----------------

async function flushTabReports() {
  const queue = _tabReportQueue;
  _tabReportQueue = new Map();
  _tabsFlushTimer = null;
  if (queue.size === 0) return;

  const { serverUrl, token } = await getConfig();
  if (!serverUrl || !token) return;

  const peers = Array.from(queue.entries()).map(([ref, title]) => ({ ref, title }));
  try {
    const resp = await fetchWithTimeout(
      `${serverUrl}${ENDPOINTS.tabs}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Ext-Token": token },
        body: JSON.stringify({ peers }),
      },
      8000,
    );
    if (!resp.ok) {
      await setStatus({ ok: false, message: `سرور خطا داد (${resp.status}) موقعِ گزارشِ تب‌ها` });
      return;
    }
    const data = await resp.json();
    const current = new Set();
    for (const s of data.sources || []) {
      if (s.active) current.add(s.ref);
    }
    await chrome.storage.local.set({ [STORAGE_KEYS.enabledRefs]: Array.from(current) });
    await setStatus({ ok: true });
  } catch (e) {
    await setStatus({ ok: false, message: "اتصال به سرور برقرار نشد (IP/پورت رو چک کن)" });
  }
}

function queueTabReport(ref, title) {
  _tabReportQueue.set(ref, title);
  if (!_tabsFlushTimer) {
    _tabsFlushTimer = setTimeout(flushTabReports, 1200);
  }
}

// ---------------- تستِ اتصال (برای پاپ‌آپ) ----------------

async function testConnection() {
  const { serverUrl, token } = await getConfig();
  if (!serverUrl) return { ok: false, message: "آدرسِ سرور خالیه" };
  if (!token) return { ok: false, message: "توکن خالیه" };
  try {
    const resp = await fetchWithTimeout(
      `${serverUrl}${ENDPOINTS.ping}`,
      { headers: { "X-Ext-Token": token } },
      6000,
    );
    if (!resp.ok) return { ok: false, message: `سرور در دسترسه ولی خطا داد (${resp.status})` };
    const data = await resp.json();
    if (!data.authenticated) return { ok: false, message: "سرور در دسترسه ولی توکن اشتباهه" };
    await setStatus({ ok: true });
    return { ok: true, message: "اتصال برقراره و توکن معتبره ✅" };
  } catch (e) {
    const message = "سرور در دسترس نیست (IP/پورت/فایروال رو چک کن)";
    await setStatus({ ok: false, message });
    return { ok: false, message };
  }
}

async function fetchSources() {
  const { serverUrl, token } = await getConfig();
  if (!serverUrl || !token) return { ok: false, sources: [] };
  try {
    const resp = await fetchWithTimeout(
      `${serverUrl}${ENDPOINTS.sources}`,
      { headers: { "X-Ext-Token": token } },
      6000,
    );
    if (!resp.ok) return { ok: false, sources: [] };
    const data = await resp.json();
    return { ok: true, sources: data.sources || [] };
  } catch (e) {
    return { ok: false, sources: [] };
  }
}

// ---------------- روترِ پیام‌ها ----------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return false;

  switch (msg.type) {
    case "UG_TAB_OPEN":
      queueTabReport(msg.ref, msg.title || "");
      sendResponse({ ok: true });
      return true;

    case "UG_GET_ENABLED_REFS":
      chrome.storage.local.get(STORAGE_KEYS.enabledRefs).then((res) => {
        sendResponse(res[STORAGE_KEYS.enabledRefs] || []);
      });
      return true;

    case "UG_NEW_POST":
      uploadPost(msg.ref, msg.text, msg.media).then(() => sendResponse({ ok: true }));
      return true;

    case "UG_TEST_CONNECTION":
      testConnection().then(sendResponse);
      return true;

    case "UG_FETCH_SOURCES":
      fetchSources().then(sendResponse);
      return true;

    default:
      return false;
  }
});

// ---------------- alarmها (زنده می‌مونن حتی وقتی سرویس‌ورکر خوابیده) ----------------

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === QUEUE_ALARM) flushUploadQueue();
  if (alarm.name === TABS_ALARM) flushTabReports();
});

// هر ۲ دقیقه یک تلاشِ منظم برای خالی‌کردنِ صفِ باقی‌مانده (علاوه بر backoff)
chrome.alarms.create(QUEUE_ALARM, { periodInMinutes: 2 });

chrome.runtime.onInstalled.addListener(() => {
  setQueueCount(0);
});
