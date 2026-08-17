import { els } from "./dom.js";
import { fetchJsonWithTimeout, postJsonWithTimeout } from "./api.js";

const POLL_IDLE_MS = 60000;
const POLL_ACTIVE_MS = 3000;
const AUTO_CLOSE_MS = 6000;

let pollTimer = null;
let closeTimer = null;
let startInFlight = false;
let panelOpen = false;
let lastStatus = null;

function setPanel(open) {
  panelOpen = open;
  if (els.wifiPanel) els.wifiPanel.style.display = open ? "grid" : "none";
  if (!open && closeTimer) {
    clearTimeout(closeTimer);
    closeTimer = null;
  }
  schedulePoll(open ? POLL_ACTIVE_MS : POLL_IDLE_MS);
}

function renderStatus(status) {
  lastStatus = status;

  if (els.wifiBtn) {
    els.wifiBtn.style.display = status.connected ? "none" : "flex";
  }

  if (!panelOpen) return;

  const hotspot = status.hotspot;
  if (hotspot) {
    if (els.wifiSsid) els.wifiSsid.textContent = hotspot.ssid;
    if (els.wifiPsk) els.wifiPsk.textContent = hotspot.psk;
    if (els.wifiQr) els.wifiQr.src = `/api/wifi/qr.svg?t=${Date.now()}`;
    if (els.wifiQrBox) els.wifiQrBox.style.display = "inline-block";
  } else {
    if (els.wifiQrBox) els.wifiQrBox.style.display = "none";
  }

  if (els.wifiMsg) els.wifiMsg.textContent = statusText(status);

  // Ergebnis kurz stehen lassen, dann schließt sich die Box von selbst.
  if (status.connected && !closeTimer) {
    closeTimer = setTimeout(() => {
      closeTimer = null;
      setPanel(false);
    }, AUTO_CLOSE_MS);
  }
}

function statusText(status) {
  switch (status.phase) {
    case "hotspot":
      return "QR-Code mit dem Handy scannen, dann öffnet sich die Einrichtungsseite.";
    case "connecting":
      return `Verbinde mit ${status.message.replace(/^Verbinde mit /, "").replace(/ …$/, "")} …`;
    case "connected":
      return `Verbunden mit ${status.ssid || status.connection}. Die Einrichtung ist abgeschlossen.`;
    case "failed":
      return status.message;
    case "error":
      return status.message;
    default:
      return "Einrichtung wird vorbereitet …";
  }
}

async function poll() {
  try {
    const status = await fetchJsonWithTimeout("/api/wifi/status", 8000);
    renderStatus(status);
    const busy = status.phase === "connecting" || status.hotspot_active;
    schedulePoll(panelOpen || busy ? POLL_ACTIVE_MS : POLL_IDLE_MS);
  } catch (e) {
    schedulePoll(POLL_IDLE_MS);
  }
}

function schedulePoll(delayMs) {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, delayMs);
}

async function startHotspot() {
  if (startInFlight) return;
  startInFlight = true;
  if (els.wifiMsg) els.wifiMsg.textContent = "Hotspot wird gestartet …";

  try {
    await postJsonWithTimeout("/api/wifi/hotspot/start", {}, 45000);
    await poll();
  } catch (e) {
    if (els.wifiMsg) els.wifiMsg.textContent = `Hotspot konnte nicht gestartet werden: ${e?.message || e}`;
  } finally {
    startInFlight = false;
  }
}

async function stopHotspot() {
  try {
    await postJsonWithTimeout("/api/wifi/hotspot/stop", {}, 30000);
  } catch (e) {}
  await poll();
}

async function openPanel() {
  setPanel(true);
  if (els.wifiQrBox) els.wifiQrBox.style.display = "none";
  if (els.wifiMsg) els.wifiMsg.textContent = "Hotspot wird gestartet …";
  await startHotspot();
}

function closePanel() {
  const wasActive = lastStatus?.hotspot_active;
  setPanel(false);
  if (wasActive) stopHotspot();
}

export function bootWifi() {
  if (els.wifiBtn) {
    // pointerdown statt click, siehe settings.js: click wartet das Loslassen ab.
    els.wifiBtn.addEventListener("pointerdown", (ev) => {
      ev.stopPropagation();
      openPanel();
    });
    els.wifiBtn.addEventListener("click", (ev) => ev.stopPropagation());
  }
  if (els.wifiCloseBtn) {
    els.wifiCloseBtn.addEventListener("pointerdown", (ev) => {
      ev.stopPropagation();
      closePanel();
    });
    els.wifiCloseBtn.addEventListener("click", (ev) => ev.stopPropagation());
  }
  poll();
}
