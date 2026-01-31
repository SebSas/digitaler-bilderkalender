export function formatDateTime(now) {
  const date = now.toLocaleDateString("de-DE", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  const time = now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  return { date, time };
}

export function updateClock(els) {
  const now = new Date();
  const { date, time } = formatDateTime(now);
  els.time.textContent = time;
  els.date.textContent = date;
}
