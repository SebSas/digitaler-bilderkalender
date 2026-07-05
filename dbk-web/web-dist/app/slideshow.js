import { els } from "./dom.js";
import { renderDebug } from "./debug.js";
import { fetchJson } from "./api.js";
import { imageUrl, preload } from "./media.js";
import { hashStringToInt, shuffleInPlace } from "./shuffle.js";
import { setLastError, state } from "./state.js";

let swapId = 0;
const fadeMs = 900;
let landscapeSwapCounter = 0;

// Ken Burns via JS stepping instead of a CSS animation: the zoom is so slow
// (4% over 22s) that ~12fps is visually identical to 60fps, but the
// compositor can idle between steps (60fps CSS kept the Pi at ~25% total CPU).
const kenburnsMs = 22000;
const kenburnsFps = 8;
let kenburnsTimer = null;

function stopKenBurns() {
  if (kenburnsTimer) {
    clearInterval(kenburnsTimer);
    kenburnsTimer = null;
  }
}

function startKenBurns(el) {
  stopKenBurns();
  const start = performance.now();
  kenburnsTimer = setInterval(() => {
    const t = Math.min(1, (performance.now() - start) / kenburnsMs);
    const e = t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2; // ease-in-out
    el.style.transform =
      `scale(${(1.02 + 0.04 * e).toFixed(4)}) ` +
      `translate3d(${(-1.0 * e).toFixed(3)}%, ${(-0.8 * e).toFixed(3)}%, 0)`;
    if (t >= 1) stopKenBurns();
  }, Math.round(1000 / kenburnsFps));
}

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

      // Keep daily shuffle after refresh
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

export function showImage(obj) {
  const url = imageUrl(obj.id);

  const incoming = state.showingA ? els.imgA : els.imgB;
  const outgoing = state.showingA ? els.imgB : els.imgA;
  const incomingBg = state.showingA ? els.imgA_bg : els.imgB_bg;
  const incomingSlot = state.showingA ? els.slotA : els.slotB;
  const outgoingSlot = state.showingA ? els.slotB : els.slotA;
  const thisSwap = ++swapId;

  incoming.classList.remove("kenburns");
  incoming.style.transform = "";
  incomingSlot.classList.remove("show", "portrait");

  incoming.src = url;
  incoming.alt = obj.name || "";
  incomingBg.src = url;

  waitForImage(incoming).then(() => {
    if (thisSwap !== swapId) return;
    const isPortrait = incoming.naturalHeight > incoming.naturalWidth;
    const useKenBurns = !isPortrait && ((landscapeSwapCounter++ % 2) === 0);
    incomingSlot.classList.toggle("portrait", isPortrait);
    incoming.classList.toggle("kenburns", useKenBurns);
    if (useKenBurns) {
      startKenBurns(incoming);
    } else {
      stopKenBurns();
    }
    incomingSlot.classList.add("show");
    outgoingSlot.classList.remove("show");
    const cleanupId = thisSwap;
    setTimeout(() => {
      if (cleanupId !== swapId) return;
      outgoingSlot.classList.remove("portrait");
      outgoing.classList.remove("kenburns");
      outgoing.style.transform = "";
    }, fadeMs + 50);
  });

  els.filePill.style.display = "none";
  els.filePill.textContent = "";

  state.showingA = !state.showingA;

  // Preload next
  const next = state.images[(state.index + 1) % state.images.length];
  if (next?.id) preload(next.id).then((ok) => renderDebug(`preload next: ${ok}`));
}

export function nextImage(step) {
  if (!state.images.length) return;
  state.index = (state.index + step + state.images.length) % state.images.length;
  showImage(state.images[state.index]);
  renderDebug(`step: ${step}`);
}

export function startSlideshow() {
  if (state.timer) clearInterval(state.timer);
  const intervalMs = 9000;
  state.timer = setInterval(() => nextImage(1), intervalMs);
}

export async function preloadFirstImage() {
  const ok = await preload(state.images[0].id);
  if (!ok) throw new Error("Failed to load first image");
}
