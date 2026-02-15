import { API_BASE } from "./config.js";
import { els } from "./dom.js";
import { state } from "./state.js";
import { fetchJsonWithTimeout, postJsonWithTimeout } from "./api.js";

let debugHandlersBound = false;
let systemRefreshTimer = null;
let systemFetchInFlight = false;
let lastDebugEvent = "-";
const SYSTEM_REFRESH_MS = 15000;

function esc(value) {
  return String(value ?? "-")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fmtTemp(value) {
  return typeof value === "number" ? `${value.toFixed(1)} °C` : "-";
}

function fmtUptime(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "-";
  const total = Math.floor(value);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const mins = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}d ${String(hours).padStart(2, "0")}h ${String(mins).padStart(2, "0")}m`;
  return `${String(hours).padStart(2, "0")}h ${String(mins).padStart(2, "0")}m`;
}

function fmtWifiStatus(wifi) {
  if (!wifi || typeof wifi !== "object") return "-";
  const status = wifi.status || "unknown";
  const iface = wifi.interface ? ` (${wifi.interface})` : "";
  return `${status}${iface}`;
}

function fmtWifiSignal(wifi) {
  if (!wifi || typeof wifi !== "object") return "-";
  const dbm = typeof wifi.signal_dbm === "number" ? `${wifi.signal_dbm} dBm` : null;
  const pct = typeof wifi.link_quality_pct === "number" ? `${wifi.link_quality_pct}%` : null;
  if (dbm && pct) return `${dbm} / ${pct}`;
  return dbm || pct || "-";
}

function sectionMarkup(title, rows) {
  const cells = rows.map(([k, v]) => (
    `<div class="debug-key">${esc(k)}</div><div class="debug-value">${esc(v)}</div>`
  )).join("");
  return (
    `<section class="debug-section">` +
      `<div class="debug-section-title">${esc(title)}</div>` +
      `<div class="debug-grid">${cells}</div>` +
    `</section>`
  );
}

function stopSystemPolling() {
  if (systemRefreshTimer) {
    clearInterval(systemRefreshTimer);
    systemRefreshTimer = null;
  }
}

function startSystemPolling() {
  stopSystemPolling();
  refreshSystemInfo();
  systemRefreshTimer = setInterval(refreshSystemInfo, SYSTEM_REFRESH_MS);
}

async function refreshSystemInfo() {
  if (!state.debugEnabled) return;
  if (systemFetchInFlight) return;
  systemFetchInFlight = true;
  try {
    const data = await fetchJsonWithTimeout("/api/system", 5000);
    state.system = {
      ...state.system,
      ...data,
      status: "ok",
      fetchedAt: new Date().toISOString(),
      error: null,
    };
  } catch (e) {
    state.system = {
      ...state.system,
      status: "error",
      fetchedAt: new Date().toISOString(),
      error: String(e?.message || e),
    };
  } finally {
    systemFetchInFlight = false;
    renderDebug();
  }
}

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
  if (enabled) {
    startSystemPolling();
  } else {
    stopSystemPolling();
  }
  renderDebug();
}

export function renderDebug(extra) {
  if (extra) lastDebugEvent = extra;
  if (!state.debugEnabled) return;
  bindDebugHandlers();
  const current = state.images[state.index] || {};
  const system = state.system || {};
  const wifi = system.wifi || null;
  const apiBaseLabel = API_BASE ? API_BASE : "same-origin";
  const imgASrc = (els.imgA && els.imgA.currentSrc) ? els.imgA.currentSrc : (els.imgA?.src || "-");
  const imgBSrc = (els.imgB && els.imgB.currentSrc) ? els.imgB.currentSrc : (els.imgB?.src || "-");
  const imgAOpacity = els.imgA ? `${getComputedStyle(els.imgA).opacity} / inline:${els.imgA.style.opacity || "-"}` : "-";
  const imgBOpacity = els.imgB ? `${getComputedStyle(els.imgB).opacity} / inline:${els.imgB.style.opacity || "-"}` : "-";
  const footerLocation = state.footer?.location
    ? `${state.footer.location.name || "-"}, ${state.footer.location.state || "-"}`
    : "-";

  const sections = [
    sectionMarkup("Slideshow", [
      ["images", state.images.length],
      ["index", state.index],
      ["current.id", current.id || "-"],
      ["current.name", current.name || "-"],
      ["last event", lastDebugEvent],
      ["last error", state.lastError || "-"],
      ["API base", apiBaseLabel],
    ]),
    sectionMarkup("System", [
      ["temperature", fmtTemp(system.temp_c)],
      ["uptime", fmtUptime(system.uptime_s)],
      ["Wi-Fi", fmtWifiStatus(wifi)],
      ["Wi-Fi signal", fmtWifiSignal(wifi)],
      ["default route iface", wifi?.default_route_iface || "-"],
      ["wifi operstate", wifi?.operstate || "-"],
      ["system status", system.status || "-"],
      ["system error", system.error || "-"],
    ]),
    sectionMarkup("Footer", [
      ["expanded", state.footer?.expanded ? "yes" : "no"],
      ["location", footerLocation],
      ["weather.status", state.footer?.weatherStatus || "-"],
      ["weather.updated_at", state.footer?.weatherUpdatedAt || "-"],
      ["weather.last_refresh_ms", state.footer?.lastWeatherRefreshMs || "-"],
      ["holidays.status", state.footer?.holidaysStatus || "-"],
      ["holidays.updated_at", state.footer?.holidaysUpdatedAt || "-"],
    ]),
    sectionMarkup("Admin", [
      ["sync.status", state.admin?.syncStatus || "-"],
      ["sync.detail", state.admin?.syncDetail || "-"],
    ]),
    sectionMarkup("Image Layers", [
      ["imgA.src", imgASrc],
      ["imgA.opacity", imgAOpacity],
      ["imgB.src", imgBSrc],
      ["imgB.opacity", imgBOpacity],
    ]),
  ];

  const button = "<button id=\"debugSyncBtn\" class=\"debug-sync-btn\" type=\"button\">Cache Update jetzt</button>";
  els.debug.innerHTML =
    "<div class=\"debug-title\">Debug</div>" +
    "<div class=\"debug-actions\">" + button + "</div>" +
    sections.join("");
}
