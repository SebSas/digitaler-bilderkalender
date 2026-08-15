import { els } from "./dom.js";
import { fetchJsonWithTimeout } from "./api.js";

const SETTINGS_PATH = "/settings/";

function setPanel(open) {
  els.settingsPanel.style.display = open ? "grid" : "none";
}

function settingsUrl(address) {
  const ip = String(address || "").split("/")[0];
  if (!ip) return null;
  const port = window.location.port ? `:${window.location.port}` : "";
  return `http://${ip}${port}${SETTINGS_PATH}`;
}

async function openPanel() {
  setPanel(true);
  els.settingsQrBox.style.display = "none";
  els.settingsUrl.textContent = "—";
  els.settingsMsg.textContent = "Adresse wird gelesen …";
  try {
    // Read the address on every open: after a new DHCP lease a cached QR points nowhere.
    const status = await fetchJsonWithTimeout("/api/wifi/status", 8000);
    const url = settingsUrl(status.address);
    if (!url) {
      els.settingsMsg.textContent = "Keine Netzwerkverbindung — die Seite ist erst nach der WLAN-Einrichtung erreichbar.";
      return;
    }
    els.settingsQr.src = `/api/qr.svg?data=${encodeURIComponent(url)}&t=${Date.now()}`;
    els.settingsQrBox.style.display = "inline-block";
    els.settingsUrl.textContent = url;
    els.settingsMsg.textContent = "";
  } catch (e) {
    els.settingsMsg.textContent = `Adresse nicht lesbar: ${String(e?.message || e)}`;
  }
}

export function bootSettings() {
  els.settingsBtn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    openPanel();
  });
  els.settingsBtn.addEventListener("touchstart", (ev) => ev.stopPropagation(), { passive: true });
  els.settingsCloseBtn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    setPanel(false);
  });
}
