import { API_BASE } from "./config.js";
import { els } from "./dom.js";
import { state } from "./state.js";

export function setDebug(enabled) {
  state.debugEnabled = enabled;
  els.debug.style.display = enabled ? "block" : "none";
  renderDebug();
}

export function renderDebug(extra) {
  if (!state.debugEnabled) return;
  const current = state.images[state.index] || {};
  const apiBaseLabel = API_BASE ? API_BASE : "same-origin";
  const lines = [
    "Debug",
    `images: ${state.images.length}`,
    `index: ${state.index}`,
    `current.id: ${current.id || "-"}`,
    `current.name: ${current.name || "-"}`,
    `last: ${extra || "-"}`,
    `last error: ${state.lastError || "-"}`,
    `API base: ${apiBaseLabel}`,
    `imgA.src: ${(els.imgA && els.imgA.currentSrc) ? els.imgA.currentSrc : els.imgA.src || "-"}`,
    `imgA.opacity: ${getComputedStyle(els.imgA).opacity} / inline:${els.imgA.style.opacity || "-"}`,
    `imgB.src: ${(els.imgB && els.imgB.currentSrc) ? els.imgB.currentSrc : els.imgB.src || "-"}`,
    `imgB.opacity: ${getComputedStyle(els.imgB).opacity} / inline:${els.imgB.style.opacity || "-"}`,
  ];
  els.debug.innerHTML = "<b>" + lines[0] + "</b><br>" + lines.slice(1).join("<br>");
}
