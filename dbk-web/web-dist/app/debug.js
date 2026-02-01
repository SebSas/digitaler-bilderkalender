import { API_BASE } from "./config.js";
import { els } from "./dom.js";
import { state } from "./state.js";
import { postJsonWithTimeout } from "./api.js";

let debugHandlersBound = false;

function bindDebugHandlers() {
  if (debugHandlersBound) return;
  if (!els.debug) return;
  els.debug.addEventListener("click", async (ev) => {
    const target = ev.target;
    if (!target || target.id !== "debugSyncBtn") return;
    target.disabled = true;
    state.admin.syncStatus = "starting";
    state.admin.syncDetail = null;
    renderDebug("sync: starting");
    try {
      const data = await postJsonWithTimeout("/api/admin/immich-sync", {}, 15000);
      state.admin.syncStatus = data.status || "unknown";
      state.admin.syncDetail = data.error || data.message || null;
      renderDebug(`sync: ${state.admin.syncStatus}`);
    } catch (e) {
      state.admin.syncStatus = "error";
      state.admin.syncDetail = String(e?.message || e);
      renderDebug("sync: error");
    } finally {
      target.disabled = false;
    }
  });
  debugHandlersBound = true;
}

export function setDebug(enabled) {
  state.debugEnabled = enabled;
  els.debug.style.display = enabled ? "block" : "none";
  renderDebug();
}

export function renderDebug(extra) {
  if (!state.debugEnabled) return;
  bindDebugHandlers();
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
    `sync.status: ${state.admin?.syncStatus || "-"}`,
    `sync.detail: ${state.admin?.syncDetail || "-"}`,
    `footer.expanded: ${state.footer?.expanded ? "yes" : "no"}`,
    `footer.location: ${state.footer?.location ? `${state.footer.location.name || "-"}, ${state.footer.location.state || "-"}` : "-"}`,
    `footer.weather.status: ${state.footer?.weatherStatus || "-"}`,
    `footer.weather.updated_at: ${state.footer?.weatherUpdatedAt || "-"}`,
    `footer.weather.last_refresh_ms: ${state.footer?.lastWeatherRefreshMs || "-"}`,
    `footer.holidays.status: ${state.footer?.holidaysStatus || "-"}`,
    `footer.holidays.updated_at: ${state.footer?.holidaysUpdatedAt || "-"}`,
    `imgA.src: ${(els.imgA && els.imgA.currentSrc) ? els.imgA.currentSrc : els.imgA.src || "-"}`,
    `imgA.opacity: ${getComputedStyle(els.imgA).opacity} / inline:${els.imgA.style.opacity || "-"}`,
    `imgB.src: ${(els.imgB && els.imgB.currentSrc) ? els.imgB.currentSrc : els.imgB.src || "-"}`,
    `imgB.opacity: ${getComputedStyle(els.imgB).opacity} / inline:${els.imgB.style.opacity || "-"}`,
  ];
  const button = "<button id=\"debugSyncBtn\" style=\"margin:8px 0 6px 0;padding:6px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.1);color:#fff;font:inherit;\">Cache Update jetzt</button>";
  els.debug.innerHTML = "<b>" + lines[0] + "</b><br>" + button + "<br>" + lines.slice(1).join("<br>");
}
