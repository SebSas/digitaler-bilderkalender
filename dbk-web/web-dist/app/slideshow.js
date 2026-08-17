import { els } from "./dom.js";
import { renderDebug } from "./debug.js";
import { fetchJson } from "./api.js";
import { imageUrl, preload } from "./media.js";
import { hashStringToInt, shuffleInPlace } from "./shuffle.js";
import { setLastError, state } from "./state.js";

let swapId = 0;
const fadeMs = 900;
const manualFadeMs = 250; // swipe navigation: fast fade for perceptible response

// --- Queue scheduling (see vault note konzept-bild-queues) ------------------
// Dwell is uniform for all images; queues only control how often they supply
// a slot. Mid/long have guaranteed frequencies, short takes all remaining
// slots and therefore adapts automatically to the amount of new images.
const dwellMs = 90 * 1000;          // display time per image (target: 1-2 min)
const midEveryMs = 10 * 60 * 1000;  // guaranteed midterm slot
const longEveryMs = 60 * 60 * 1000; // guaranteed longterm slot

let lastMidAt = 0;
let lastLongAt = 0;
const queueCursors = { short: 0, mid: 0, long: 0 };
const shownHistory = [];
let historyPos = -1;
const historyMax = 50;

// The boot image is shown via showImage() directly, bypassing nextImage() —
// without seeding it here, manual back-swipes silently do nothing until the
// second automatic advance and then lag one step behind.
export function seedHistory(img) {
  shownHistory.push(img);
  historyPos = shownHistory.length - 1;
}

function imagesByQueue() {
  // Images without a queue label (older backend) fall back to midterm.
  const queues = { short: [], mid: [], long: [] };
  for (const img of state.images) {
    (queues[img.queue] || queues.mid).push(img);
  }
  return queues;
}

function pickFromQueues(commit) {
  const queues = imagesByQueue();
  const now = Date.now();
  let name = null;
  if (queues.long.length && now - lastLongAt >= longEveryMs) {
    name = "long";
  } else if (queues.mid.length && now - lastMidAt >= midEveryMs) {
    name = "mid";
  } else if (queues.short.length) {
    name = "short";
  } else if (queues.mid.length) {
    name = "mid";
  } else if (queues.long.length) {
    name = "long";
  } else {
    return null;
  }

  const list = queues[name];
  const img = list[queueCursors[name] % list.length];
  if (commit) {
    queueCursors[name] = (queueCursors[name] + 1) % list.length;
    if (name === "mid") lastMidAt = now;
    if (name === "long") lastLongAt = now;
    renderDebug(`queue: ${name} (s/m/l ${queues.short.length}/${queues.mid.length}/${queues.long.length})`);
  }
  return img;
}

// Ken Burns (4% Zoom über 22s, per JS in 8 Schritten/s) am 2026-08-16 entfernt:
// Sebi bemerkte den Effekt im Betrieb nicht und sah keinen Mehrwert. Er kostete
// dafür acht Neuzeichnungen pro Sekunde, dauerhaft.

function waitForImage(img) {
  if (img.decode) {
    return img.decode().catch(() => {});
  }
  return new Promise((resolve) => {
    const done = () => {
      img.onload = null;
      img.onerror = null;
      resolve();
    };
    img.onload = done;
    img.onerror = done;
  });
}

export async function refreshImagesList() {
  try {
    const list = await fetchJson("/api/images");
    if (Array.isArray(list) && list.length > 0) {
      state.images = list;

      // Keep daily shuffle after refresh (order within each queue follows it)
      const dayKey = new Date().toISOString().slice(0, 10);
      shuffleInPlace(state.images, hashStringToInt(dayKey));

      // Keep index in range
      state.index = Math.min(state.index, state.images.length - 1);

      renderDebug("images list refreshed");
    }
  } catch (e) {
    const msg = `refresh failed: ${String(e?.message || e)}`;
    setLastError(msg);
    renderDebug(msg);
  }
}

export function schedulePeriodicRefresh() {
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(refreshImagesList, 10 * 60 * 1000); // every 10 minutes
}

export function showImage(obj, manual = false) {
  const url = imageUrl(obj.id);
  const effFadeMs = manual ? manualFadeMs : fadeMs;
  document.body.classList.toggle("manual-nav", manual);

  const incoming = state.showingA ? els.imgA : els.imgB;
  const outgoing = state.showingA ? els.imgB : els.imgA;
  const incomingBg = state.showingA ? els.imgA_bg : els.imgB_bg;
  const incomingSlot = state.showingA ? els.slotA : els.slotB;
  const outgoingSlot = state.showingA ? els.slotB : els.slotA;
  const thisSwap = ++swapId;

  incomingSlot.classList.remove("show", "portrait");

  incoming.src = url;
  incoming.alt = obj.name || "";
  incomingBg.src = url;

  waitForImage(incoming).then(() => {
    if (thisSwap !== swapId) return;
    const isPortrait = incoming.naturalHeight > incoming.naturalWidth;
    incomingSlot.classList.toggle("portrait", isPortrait);
    incomingSlot.classList.add("show");
    outgoingSlot.classList.remove("show");
    const cleanupId = thisSwap;
    setTimeout(() => {
      if (cleanupId !== swapId) return;
      outgoingSlot.classList.remove("portrait");
    }, effFadeMs + 50);
  });

  els.filePill.style.display = "none";
  els.filePill.textContent = "";

  state.showingA = !state.showingA;

  // Preload the predicted next image (peek does not advance the scheduler)
  const next = pickFromQueues(false);
  if (next?.id && next.id !== obj.id) {
    preload(next.id).then((ok) => renderDebug(`preload next: ${ok}`));
  }

  // Preload the manual-back neighbour so backward swipes hit a decoded image
  const prev = historyPos > 0 ? shownHistory[historyPos - 1] : null;
  if (prev?.id && prev.id !== obj.id && prev.id !== next?.id) {
    preload(prev.id);
  }
}

export function nextImage(step, manual = false) {
  if (!state.images.length) return;

  let img = null;
  if (step < 0) {
    // Manual back: walk the history of actually shown images. Am Anfang
    // angekommen, springt es ans Ende statt stehen zu bleiben — Ringpuffer.
    // Vorwaerts braucht kein Gegenstueck: dort erzeugt der Planer bei Bedarf
    // ein neues Bild, es gibt also keine Sackgasse.
    if (shownHistory.length < 2) return;
    historyPos = historyPos > 0 ? historyPos - 1 : shownHistory.length - 1;
    img = shownHistory[historyPos];
  } else if (historyPos < shownHistory.length - 1) {
    // Manual forward after going back: replay history first
    historyPos += 1;
    img = shownHistory[historyPos];
  } else {
    img = pickFromQueues(true);
    if (!img) return;
    shownHistory.push(img);
    if (shownHistory.length > historyMax) shownHistory.shift();
    historyPos = shownHistory.length - 1;
  }

  const idx = state.images.findIndex((x) => x.id === img.id);
  if (idx >= 0) state.index = idx;
  showImage(img, manual);
  renderDebug(`step: ${step}`);
}

export function startSlideshow() {
  if (state.timer) clearInterval(state.timer);
  // Do not open the show with the guaranteed mid/long slots
  const now = Date.now();
  if (!lastMidAt) lastMidAt = now;
  if (!lastLongAt) lastLongAt = now;
  state.timer = setInterval(() => nextImage(1), dwellMs);
}

export async function preloadFirstImage() {
  const ok = await preload(state.images[0].id);
  if (!ok) throw new Error("Failed to load first image");
}
