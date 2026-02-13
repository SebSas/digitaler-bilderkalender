export const els = {
  slotA: document.getElementById("slotA"),
  slotB: document.getElementById("slotB"),
  imgA_bg: document.getElementById("imgA_bg"),
  imgB_bg: document.getElementById("imgB_bg"),
  imgA: document.getElementById("imgA"),
  imgB: document.getElementById("imgB"),
  filePill: document.getElementById("filePill"),
  time: document.getElementById("time"),
  date: document.getElementById("date"),
  subtitle: document.getElementById("subtitle"),
  footer: document.getElementById("footer"),
  footerCollapsed: document.getElementById("footerCollapsed"),
  footerExpanded: document.getElementById("footerExpanded"),
  holidayLabel: document.getElementById("holidayLabel"),
  locationLabel: document.getElementById("locationLabel"),
  weatherPill: document.getElementById("weatherPill"),
  weatherPillIcon: document.getElementById("weatherPillIcon"),
  weatherPillLine1: document.getElementById("weatherPillLine1"),
  weatherPillLine2: document.getElementById("weatherPillLine2"),
  calendarHeader: document.getElementById("calendarHeader"),
  calendarGrid: document.getElementById("calendarGrid"),
  weatherExpanded: document.getElementById("weatherExpanded"),
  weatherUnavailable: document.getElementById("weatherUnavailable"),
  weatherToday: document.getElementById("weatherToday"),
  weatherTodayIcon: document.getElementById("weatherTodayIcon"),
  weatherTodayTemp: document.getElementById("weatherTodayTemp"),
  weatherTodayText: document.getElementById("weatherTodayText"),
  weatherForecast: document.getElementById("weatherForecast"),
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
