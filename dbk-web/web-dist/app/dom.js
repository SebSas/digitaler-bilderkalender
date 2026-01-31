export const els = {
  imgA: document.getElementById("imgA"),
  imgB: document.getElementById("imgB"),
  filePill: document.getElementById("filePill"),
  time: document.getElementById("time"),
  date: document.getElementById("date"),
  subtitle: document.getElementById("subtitle"),
  overlay: document.getElementById("overlay"),
  overlayTitle: document.getElementById("overlayTitle"),
  overlayText: document.getElementById("overlayText"),
  debug: document.getElementById("debug"),
  secretTapZone: document.getElementById("secretTapZone"),
};

export function setOverlay(show, title, text) {
  els.overlay.style.display = show ? "grid" : "none";
  if (title) els.overlayTitle.textContent = title;
  if (text) els.overlayText.textContent = text;
}
