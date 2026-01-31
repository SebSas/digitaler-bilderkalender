import { els, setOverlay } from "./dom.js";
import { renderDebug, setDebug } from "./debug.js";
import { fetchJson } from "./api.js";
import { schedulePeriodicRefresh, startSlideshow, nextImage, showImage, preloadFirstImage } from "./slideshow.js";
import { hashStringToInt, shuffleInPlace } from "./shuffle.js";
import { updateClock } from "./time.js";
import { setLastError, state } from "./state.js";

async function boot() {
  try {
    setOverlay(true, "Checking API…", "Ich prüfe, ob der Bilderdienst erreichbar ist…");
    await fetchJson("/api/health");
    els.subtitle.textContent = "Digitaler Bilderkalender";

    setOverlay(true, "Loading images…", "Ich lade die Bilderliste…");
    const list = await fetchJson("/api/images");
    if (!Array.isArray(list) || list.length === 0) {
      throw new Error("No images returned from /api/images");
    }

    state.images = list;

    // Daily stable shuffle (changes each day)
    const dayKey = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
    shuffleInPlace(state.images, hashStringToInt(dayKey));

    state.index = 0;

    setOverlay(true, "Warming up…", "Ich lade das erste Bild…");
    await preloadFirstImage();

    setOverlay(false);
    showImage(state.images[0]);
    startSlideshow();
    schedulePeriodicRefresh();
    renderDebug("ready");
  } catch (e) {
    const msg = String(e?.message || e);
    setLastError(msg);
    setOverlay(true, "Oops…", msg + " (Retry in 10s)");
    renderDebug(`error: ${msg}`);
    setTimeout(() => boot(), 10000);
  }
}

// Secret debug toggle: 5 taps in top-right zone
els.secretTapZone.addEventListener("click", () => {
  const t = Date.now();
  if (t - state.tap.last > 900) state.tap.count = 0;
  state.tap.last = t;
  state.tap.count += 1;
  if (state.tap.count >= 5) {
    setDebug(!state.debugEnabled);
    state.tap.count = 0;
  }
});

// Swipe navigation
let touch = { x0: null, y0: null };
window.addEventListener("touchstart", (ev) => {
  if (!ev.touches?.length) return;
  touch.x0 = ev.touches[0].clientX;
  touch.y0 = ev.touches[0].clientY;
}, { passive: true });

window.addEventListener("touchend", (ev) => {
  if (touch.x0 == null) return;
  const x1 = ev.changedTouches[0].clientX;
  const y1 = ev.changedTouches[0].clientY;
  const dx = x1 - touch.x0;
  const dy = y1 - touch.y0;
  touch.x0 = null;
  touch.y0 = null;

  if (Math.abs(dx) > 60 && Math.abs(dy) < 80) {
    // Swipe left -> next, swipe right -> prev
    nextImage(dx < 0 ? 1 : -1);
    startSlideshow();
  }
}, { passive: true });

updateClock(els);
setInterval(() => updateClock(els), 1000);
boot();
