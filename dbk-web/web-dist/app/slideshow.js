import { els } from "./dom.js";
import { renderDebug } from "./debug.js";
import { fetchJson } from "./api.js";
import { imageUrl, preload } from "./media.js";
import { hashStringToInt, shuffleInPlace } from "./shuffle.js";
import { setLastError, state } from "./state.js";

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

  const front = state.showingA ? els.imgA : els.imgB;
  const back = state.showingA ? els.imgB : els.imgA;

  back.classList.remove("show", "kenburns");
  back.style.opacity = "";

  front.style.opacity = "";
  front.src = url;
  front.alt = obj.name || "";
  front.classList.add("show", "kenburns");

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
