/*
 * اسکریپتِ تزریق‌شده داخلِ web.telegram.org (نسخه‌ی K یا A).
 *
 * ⚠️ نکته‌ی مهم: این فایل با «خوندنِ ساختارِ HTML صفحه‌ی تلگرام‌وب» کار
 * می‌کنه (DOM scraping)، نه یک API رسمی. تلگرام هر چند وقت یک‌بار ساختارِ
 * صفحه رو عوض می‌کنه و ممکنه سلکتورهای زیر از کار بیفتن. اگه یه روز دیدی
 * چیزی گزارش نمیشه، اول با کنسولِ مرورگر (F12) چک کن ببین سلکتورها هنوز
 * درستن یا نه (جدولِ SELECTORS پایین).
 *
 * منطق کلی:
 *   ۱. هر تبی که یک چت باز داره، یک "ref" داره = خودِ location.hash صفحه
 *      (که تلگرام‌وب برای هر چت یکتا نگه می‌داره).
 *   ۲. هر چند ثانیه، تب‌های بازِ فعلی به بک‌گراند گزارش میشن (تا از تو ربات
 *      لیستشون دیده و فعال/غیرفعال بشه).
 *   ۳. با MutationObserver، پیام‌های جدیدِ چتِ بازِ فعلی رصد میشن؛ اگه اون
 *      چت فعال شده باشه، متن + مدیای هر پیامِ جدید به بک‌گراند فرستاده میشه.
 */

(() => {
  "use strict";

  // اگه این اسکریپت به هر دلیلی دوبار تزریق بشه (مثلاً reload اکستنشن)، از
  // ثبتِ دوبارهٔ observer/interval جلوگیری می‌کنه.
  if (window.__UG_CONTENT_LOADED__) return;
  window.__UG_CONTENT_LOADED__ = true;

  const SELECTORS = {
    bubblesContainer: ".bubbles, .bubbles-inner, #column-center .scrollable",
    bubble: ".bubble[data-mid], .bubble",
    bubbleTextInner: ".message, .text-content, .translatable-message",
    bubblePhoto: ".attachment img, .media-photo img, img.thumbnail, picture img",
    bubbleVideo: ".attachment video, .media-video video, video",
    chatTitleCandidates: [
      "#column-center .sidebar-header .user-title",
      "#column-center .sidebar-header .peer-title",
      ".chat-info .peer-title",
      ".sidebar-header__title",
    ],
    viewerImage: ".media-viewer-movers img, .media-viewer img.thumbnail, .MediaViewer img",
    viewerVideo: ".media-viewer-movers video, .media-viewer video, .MediaViewer video",
    viewerAny: ".media-viewer, .MediaViewer, .media-viewer-whole",
  };

  const VIEWER_OPEN_TIMEOUT_MS = 4000;
  const IMAGE_LOAD_TIMEOUT_MS = 5000;
  const VIDEO_BUFFER_TIMEOUT_MS = 20000; // ویدیوهای حجیم ممکنه بیشتر طول بکشه
  const REPORT_INTERVAL_MS = 6000;
  const PROCESSED_KEY_PREFIX = "ug_seen_mids::"; // توی chrome.storage.local
  const MUTATION_DEBOUNCE_MS = 800;

  let fullQualityMode = true; // از storage خونده میشه، پیش‌فرض روشن

  chrome.storage.local.get("ug_full_quality_mode").then((res) => {
    if (typeof res.ug_full_quality_mode === "boolean") {
      fullQualityMode = res.ug_full_quality_mode;
    }
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.ug_full_quality_mode) {
      fullQualityMode = !!changes.ug_full_quality_mode.newValue;
    }
  });

  function currentPeerRef() {
    const h = (location.hash || "").trim();
    if (!h || h === "#") return null;
    return h;
  }

  function currentChatTitle() {
    for (const sel of SELECTORS.chatTitleCandidates) {
      const el = document.querySelector(sel);
      if (el && el.textContent && el.textContent.trim()) {
        return el.textContent.trim();
      }
    }
    const t = (document.title || "").replace(/^Telegram( Web)?\s*[-|]?\s*/i, "").trim();
    return t || "چت بدون‌نام";
  }

  function findBubbleContainer() {
    for (const sel of SELECTORS.bubblesContainer.split(",")) {
      const el = document.querySelector(sel.trim());
      if (el) return el;
    }
    return document.body;
  }

  async function blobUrlToBase64(url) {
    try {
      const resp = await fetch(url);
      const blob = await resp.blob();
      return await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result); // data:...;base64,XXXX
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    } catch (e) {
      console.warn("[UploadGram] خطا در خوندنِ blob:", e);
      return null;
    }
  }

  function extractText(bubbleEl) {
    let inner = null;
    for (const sel of SELECTORS.bubbleTextInner.split(",")) {
      inner = bubbleEl.querySelector(sel.trim());
      if (inner) break;
    }
    const node = inner || bubbleEl;
    return (node.innerHTML || node.textContent || "").trim();
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function waitForSelector(selectorList, timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      for (const sel of selectorList.split(",")) {
        const el = document.querySelector(sel.trim());
        if (el) return el;
      }
      await sleep(120);
    }
    return null;
  }

  async function waitForLoadedImage(imgEl, timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const src = imgEl.currentSrc || imgEl.src;
      if (src && src.startsWith("blob:") && imgEl.complete && imgEl.naturalWidth > 0) return src;
      await sleep(150);
    }
    return imgEl.currentSrc || imgEl.src || null;
  }

  async function waitForBufferedVideo(videoEl, timeoutMs) {
    const start = Date.now();
    try { await videoEl.play().catch(() => {}); } catch (e) { /* بی‌اثر */ }
    while (Date.now() - start < timeoutMs) {
      if (videoEl.duration && videoEl.buffered && videoEl.buffered.length > 0) {
        const bufferedEnd = videoEl.buffered.end(videoEl.buffered.length - 1);
        if (bufferedEnd >= videoEl.duration - 0.5) break;
      }
      await sleep(300);
    }
    try { videoEl.pause(); } catch (e) { /* بی‌اثر */ }
    return videoEl.currentSrc || videoEl.src || null;
  }

  async function closeMediaViewer() {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, bubbles: true }));
    await sleep(200);
  }

  /** با کلیک روی تامبنیل، ویوئرِ بزرگِ مدیا رو باز می‌کنه تا نسخه‌ی باکیفیت
   * رو بگیره؛ در صورتِ شکست/تایم‌اوت، null برمی‌گردونه (فراخوان fallback
   * می‌کنه به نسخه‌ی فشرده‌ی داخلِ خودِ حباب). */
  async function extractFullQualityMedia(thumbEl, kind) {
    try {
      thumbEl.click();
      const viewer = await waitForSelector(SELECTORS.viewerAny, VIEWER_OPEN_TIMEOUT_MS);
      if (!viewer) return null;

      let src = null;
      if (kind === "photo") {
        const img = await waitForSelector(SELECTORS.viewerImage, VIEWER_OPEN_TIMEOUT_MS);
        if (img) src = await waitForLoadedImage(img, IMAGE_LOAD_TIMEOUT_MS);
      } else {
        const vid = await waitForSelector(SELECTORS.viewerVideo, VIEWER_OPEN_TIMEOUT_MS);
        if (vid) src = await waitForBufferedVideo(vid, VIDEO_BUFFER_TIMEOUT_MS);
      }

      await closeMediaViewer();
      if (src && src.startsWith("blob:")) {
        return await blobUrlToBase64(src);
      }
      return null;
    } catch (e) {
      console.warn("[UploadGram] گرفتنِ نسخه‌ی باکیفیت شکست خورد، از نسخه‌ی فشرده استفاده میشه:", e);
      await closeMediaViewer();
      return null;
    }
  }

  async function extractMedia(bubbleEl) {
    const items = [];

    const imgs = bubbleEl.querySelectorAll(SELECTORS.bubblePhoto);
    for (const img of imgs) {
      let b64 = fullQualityMode ? await extractFullQualityMedia(img, "photo") : null;
      if (!b64) {
        const src = img.currentSrc || img.src;
        if (src && src.startsWith("blob:")) b64 = await blobUrlToBase64(src);
      }
      if (b64) items.push({ kind: "photo", dataUrl: b64 });
    }

    const vids = bubbleEl.querySelectorAll(SELECTORS.bubbleVideo);
    for (const vid of vids) {
      let b64 = fullQualityMode ? await extractFullQualityMedia(vid, "video") : null;
      if (!b64) {
        const src = vid.currentSrc || vid.src;
        if (src && src.startsWith("blob:")) b64 = await blobUrlToBase64(src);
      }
      if (b64) items.push({ kind: "video", dataUrl: b64 });
    }

    return items;
  }

  async function getSeenSet(ref) {
    const key = PROCESSED_KEY_PREFIX + ref;
    const res = await chrome.storage.local.get(key);
    return new Set(res[key] || []);
  }

  async function markSeen(ref, mid) {
    const key = PROCESSED_KEY_PREFIX + ref;
    const seen = await getSeenSet(ref);
    seen.add(mid);
    const trimmed = Array.from(seen).slice(-500); // جلوگیری از بادکردنِ storage
    await chrome.storage.local.set({ [key]: trimmed });
  }

  let processing = false;

  async function processNewBubbles() {
    if (processing) return;
    processing = true;
    try {
      const ref = currentPeerRef();
      if (!ref) return;

      const enabledRefs = await chrome.runtime.sendMessage({ type: "UG_GET_ENABLED_REFS" }).catch(() => null);
      if (!enabledRefs || !enabledRefs.includes(ref)) return; // ادمین هنوز این چت رو فعال نکرده

      const container = findBubbleContainer();
      const bubbles = container.querySelectorAll(SELECTORS.bubble);
      const seen = await getSeenSet(ref);

      for (const bubble of bubbles) {
        const mid = bubble.getAttribute("data-mid") || bubble.dataset.mid;
        if (!mid || seen.has(mid)) continue;

        const text = extractText(bubble);
        const media = await extractMedia(bubble);
        if (!text && media.length === 0) continue;

        await chrome.runtime.sendMessage({ type: "UG_NEW_POST", ref, text, media })
          .catch((e) => console.warn("[UploadGram] ارسال به بک‌گراند شکست خورد:", e));

        await markSeen(ref, mid);
      }
    } finally {
      processing = false;
    }
  }

  async function reportOpenTab() {
    const ref = currentPeerRef();
    if (!ref) return;
    const title = currentChatTitle();
    await chrome.runtime.sendMessage({ type: "UG_TAB_OPEN", ref, title }).catch(() => {});
  }

  // ---------------- راه‌اندازی ----------------
  let mutationTimer = null;
  const observer = new MutationObserver(() => {
    clearTimeout(mutationTimer);
    mutationTimer = setTimeout(processNewBubbles, MUTATION_DEBOUNCE_MS);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  setInterval(reportOpenTab, REPORT_INTERVAL_MS);
  window.addEventListener("hashchange", reportOpenTab);
  reportOpenTab();
  processNewBubbles();
})();
