import { els, setOverlay } from "./dom.js";
import { fetchJsonWithTimeout, postJsonWithTimeout } from "./api.js";
import { state } from "./state.js";
import { iconSvg } from "./icons.js";

const FOOTER_IDLE_MS = 15000;
const WEATHER_REFRESH_INTERVAL_MS = 45 * 60 * 1000;
const WEATHER_MIN_REFRESH_MS = 30 * 60 * 1000;
const CONFIG_POLL_MS = 60 * 1000;
// Die Liste scrollt, sie darf also alles zeigen, was der Tag hergibt.
const EVENTS_DAY_MAX = 40;
const MAX_DAY_DOTS = 4;

const ICON_EMOJI = {
  sunny: "☀️",
  partly_cloudy_day: "🌤️",
  cloudy: "☁️",
  rain: "🌧️",
  drizzle: "🌦️",
  snow: "❄️",
  storm: "⛈️",
  fog: "🌫️",
  unknown: "❔",
};

let locationConfig = null;
let weatherData = null;
let holidaysData = null;
let eventsData = [];
let eventsLoaded = false;
let eventsSerialized = "";
let selectedYmd = null;
let footerExpanded = false;
let footerIdleTimer = null;
let weatherRefreshTimer = null;
let configPollTimer = null;
let weatherRefreshInFlight = false;
let lastWeatherRefresh = 0;
let shutdownInFlight = false;

function toYmd(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function iconMarkup(key) {
  return iconSvg(key || "unknown");
}

function truncate(text, maxLen) {
  if (!text) return "";
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 1) + "…";
}

function formatCollapsedCondition(text) {
  let t = text || "";
  t = t.replace(/Teilweise/g, "Teilw.");
  t = t.replace(/Überwiegend/g, "Übw.");
  t = t.replace(/vereinzelte/g, "vereinz.");
  t = t.replace(/Schauer/g, "Schau.");
  t = t.replace(/Gewitter/g, "Gew.");
  if (t.length > 18) t = t.slice(0, 17) + "…";
  return t;
}

function setExpanded(value) {
  footerExpanded = value;
  state.footer.expanded = value;
  if (els.footer) els.footer.classList.toggle("expanded", value);
  if (els.footerExpanded) els.footerExpanded.setAttribute("aria-hidden", value ? "false" : "true");
  if (value) {
    resetFooterIdleTimer();
    return;
  }
  if (footerIdleTimer) {
    clearTimeout(footerIdleTimer);
    footerIdleTimer = null;
  }
  // A closed footer forgets the tapped day, so it reopens on the preview.
  if (selectedYmd) {
    selectedYmd = null;
    renderCalendar();
    renderEventsList();
  }
}

function resetFooterIdleTimer() {
  if (!footerExpanded) return;
  if (footerIdleTimer) clearTimeout(footerIdleTimer);
  footerIdleTimer = setTimeout(() => setExpanded(false), FOOTER_IDLE_MS);
}

function renderHoliday() {
  const label = els.holidayLabel;
  if (!label) return;
  state.footer.holidaysStatus = holidaysData?.status || null;
  state.footer.holidaysUpdatedAt = holidaysData?.updated_at || null;
  const today = toYmd(new Date());
  const holiday = holidaysData?.status === "ok"
    ? (holidaysData.days || []).find((d) => d.date === today)
    : null;
  if (!holiday) {
    label.style.display = "none";
    label.textContent = "";
    return;
  }
  const text = truncate(`Feiertag: ${holiday.name}`, 28);
  label.textContent = text;
  label.style.display = "block";
}

function holidayNameOn(ymd) {
  if (holidaysData?.status !== "ok") return null;
  const hit = (holidaysData.days || []).find((d) => d.date === ymd);
  return hit ? hit.name : null;
}

function ymdOf(year, month, day) {
  return new Date(year, month - 1, day);
}

function isSameDay(date, year, month, day) {
  return date.getFullYear() === year && date.getMonth() + 1 === month && date.getDate() === day;
}

// Birthdays repeat every year. Appointments match their own date, or any day
// inside their range when one is set.
function eventsOn(date) {
  const month = date.getMonth() + 1;
  const day = date.getDate();
  return eventsData.filter((e) => {
    if (e.type === "birthday") return e.month === month && e.day === day;
    const start = ymdOf(e.year, e.month, e.day);
    const end = e.end_day ? ymdOf(e.end_year, e.end_month, e.end_day) : start;
    const probe = ymdOf(date.getFullYear(), month, day);
    return probe >= start && probe <= end;
  });
}

// On a multi-day appointment the start time belongs to the first day and the
// end time to the last one; the days in between carry no time at all.
function timeLabelFor(event, date) {
  if (event.type !== "appointment") return "";
  if (!event.end_day) {
    if (event.time && event.time_end) return `${event.time}–${event.time_end}`;
    return event.time || "";
  }
  if (isSameDay(date, event.year, event.month, event.day)) {
    return event.time ? `ab ${event.time}` : "";
  }
  if (isSameDay(date, event.end_year, event.end_month, event.end_day)) {
    return event.time_end ? `bis ${event.time_end}` : "";
  }
  return "";
}

const KIND_ORDER = { holiday: 0, birthday: 1, appointment: 2 };

// One flat list per day: holiday first, then the user's own entries.
function occurrencesOn(date) {
  const entries = [];
  const holiday = holidayNameOn(toYmd(date));
  if (holiday) entries.push({ kind: "holiday", title: holiday, time: "" });
  for (const e of eventsOn(date)) {
    const title = e.type === "birthday" && e.year
      ? `${e.title} (${date.getFullYear() - e.year})`
      : e.title;
    entries.push({ id: e.id, kind: e.type, title, time: timeLabelFor(e, date) });
  }
  entries.sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind]);
  return entries;
}

function dotFor(kind) {
  const dot = document.createElement("span");
  dot.className = `calendar-dot ${kind}`;
  return dot;
}

// One dot per entry, but a cell must not turn into a string of beads: beyond the
// cap the last dot is a neutral "there is more" marker. Tapping the day shows all.
function appendDots(container, entries) {
  const overflow = entries.length > MAX_DAY_DOTS;
  const visible = overflow ? MAX_DAY_DOTS - 1 : entries.length;
  entries.slice(0, visible).forEach((entry) => container.appendChild(dotFor(entry.kind)));
  if (overflow) container.appendChild(dotFor("more"));
}

function renderEventsBadge() {
  const label = els.eventsLabel;
  if (!label) return;
  if (!eventsLoaded) {
    label.style.display = "none";
    return;
  }
  const entries = occurrencesOn(new Date());
  label.innerHTML = "";
  [...new Set(entries.map((e) => e.kind))].forEach((kind) => label.appendChild(dotFor(kind)));
  const text = document.createElement("span");
  if (!entries.length) text.textContent = "Keine Ereignisse heute";
  else if (entries.length === 1) text.textContent = "Ein Ereignis heute";
  else text.textContent = `${entries.length} Ereignisse heute`;
  label.appendChild(text);
  label.style.display = "flex";
}

function eventRow(entry, whenText, isToday) {
  const row = document.createElement("div");
  row.className = "event-row" + (isToday ? " is-today" : "");
  const when = document.createElement("span");
  when.className = "event-when";
  when.textContent = whenText;
  const title = document.createElement("span");
  title.className = "event-title";
  title.textContent = entry.title;
  row.appendChild(dotFor(entry.kind));
  row.appendChild(when);
  row.appendChild(title);
  return row;
}

// Immer genau EIN Tag: beim Aufklappen heute, nach einem Tipp der gewaehlte Tag.
// Der Block bleibt dabei dauerhaft sichtbar, damit sich im Panel nichts bewegt.
function renderEventsList() {
  const box = els.eventsExpanded;
  const list = els.eventsList;
  if (!box || !list) return;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const [y, m, d] = (selectedYmd || toYmd(today)).split("-").map(Number);
  const day = ymdOf(y, m, d);
  const isToday = toYmd(day) === toYmd(today);

  if (els.eventsHeader) {
    const label = day.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" });
    els.eventsHeader.textContent = isToday ? `Heute — ${label}` : label;
  }

  list.innerHTML = "";
  const entries = occurrencesOn(day);
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "events-empty";
    empty.textContent = "Keine Ereignisse an diesem Tag";
    list.appendChild(empty);
  } else {
    entries.slice(0, EVENTS_DAY_MAX).forEach((entry) => {
      list.appendChild(eventRow(entry, entry.time, isToday));
    });
  }
  box.style.display = "flex";
}

function selectDay(ymd) {
  selectedYmd = selectedYmd === ymd ? null : ymd;
  renderCalendar();
  renderEventsList();
}

function renderLocation() {
  const label = els.locationLabel;
  if (!label) return;
  if (!locationConfig) {
    label.style.display = "none";
    label.textContent = "";
    return;
  }
  label.textContent = `${locationConfig.name}`;
  label.style.display = "block";
}

function renderCollapsedWeather() {
  const pill = els.weatherPill;
  if (!pill) return;
  state.footer.weatherStatus = weatherData?.status || null;
  state.footer.weatherUpdatedAt = weatherData?.updated_at || null;
  if (!weatherData || weatherData.status !== "ok") {
    pill.style.display = "none";
    return;
  }
  const temp = weatherData.current?.temp_c;
  const condition = weatherData.current?.condition_text || "";
  const icon = iconMarkup(weatherData.current?.icon);
  if (els.weatherPillIcon) els.weatherPillIcon.innerHTML = icon;
  els.weatherPillLine1.textContent = `${temp}°C`;
  els.weatherPillLine2.textContent = formatCollapsedCondition(condition);
  pill.style.display = "flex";
}

function renderExpandedWeather() {
  if (!els.weatherExpanded) return;
  if (!weatherData || weatherData.status !== "ok") {
    if (els.weatherUnavailable) els.weatherUnavailable.style.display = "block";
    if (els.weatherToday) els.weatherToday.style.display = "none";
    if (els.weatherForecast) els.weatherForecast.innerHTML = "";
    return;
  }
  if (els.weatherUnavailable) els.weatherUnavailable.style.display = "none";
  if (els.weatherToday) els.weatherToday.style.display = "none";

  if (els.weatherForecast) {
    els.weatherForecast.innerHTML = "";
    const forecast = Array.isArray(weatherData.forecast_3d) ? weatherData.forecast_3d : [];
    forecast.slice(0, 3).forEach((day) => {
      const card = document.createElement("div");
      card.className = "forecast-day";
      const dateObj = new Date(`${day.date}T00:00:00`);
      let weekday = dateObj.toLocaleDateString("de-DE", { weekday: "short" });
      weekday = weekday.replace(".", "");
      const line1 = document.createElement("div");
      line1.className = "forecast-weekday";
      line1.textContent = weekday;

      const main = document.createElement("div");
      main.className = "forecast-main";

      const icon = document.createElement("div");
      icon.className = "forecast-icon";
      icon.innerHTML = iconMarkup(day.icon);

      const temps = document.createElement("div");
      temps.className = "forecast-temps";
      const tMin = document.createElement("div");
      tMin.className = "forecast-min";
      tMin.textContent = `${day.min_c}°`;
      const tMax = document.createElement("div");
      tMax.className = "forecast-max";
      tMax.textContent = `${day.max_c}°`;
      temps.appendChild(tMin);
      temps.appendChild(tMax);

      main.appendChild(icon);
      main.appendChild(temps);

      card.appendChild(line1);
      card.appendChild(main);
      els.weatherForecast.appendChild(card);
    });
  }
}

function renderCalendar() {
  if (!els.calendarGrid || !els.calendarHeader) return;
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();

  els.calendarHeader.textContent = now.toLocaleDateString("de-DE", { month: "long", year: "numeric" });

  const holidaySet = new Set();
  if (holidaysData?.status === "ok") {
    for (const item of holidaysData.days || []) {
      holidaySet.add(item.date);
    }
  }

  const first = new Date(year, month, 1);
  const firstDow = (first.getDay() + 6) % 7; // Monday=0
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const prevDays = new Date(year, month, 0).getDate();
  const totalCells = Math.ceil((firstDow + daysInMonth) / 7) * 7;

  els.calendarGrid.innerHTML = "";
  const weekdays = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
  weekdays.forEach((label) => {
    const cell = document.createElement("div");
    cell.className = "calendar-weekday";
    cell.textContent = label;
    els.calendarGrid.appendChild(cell);
  });

  for (let i = 0; i < totalCells; i++) {
    const dayIndex = i - firstDow + 1;
    let dateObj;
    let inMonth = true;
    if (dayIndex <= 0) {
      inMonth = false;
      dateObj = new Date(year, month - 1, prevDays + dayIndex);
    } else if (dayIndex > daysInMonth) {
      inMonth = false;
      dateObj = new Date(year, month + 1, dayIndex - daysInMonth);
    } else {
      dateObj = new Date(year, month, dayIndex);
    }

    const ymd = toYmd(dateObj);
    const cell = document.createElement("div");
    cell.className = "calendar-day";
    if (!inMonth) cell.classList.add("dim");
    if (ymd === toYmd(now)) cell.classList.add("today");
    if (holidaySet.has(ymd)) cell.classList.add("holiday");
    if (ymd === selectedYmd) cell.classList.add("selected");
    cell.textContent = String(dateObj.getDate());

    const entries = occurrencesOn(dateObj);
    if (entries.length) {
      const dots = document.createElement("span");
      dots.className = "calendar-dots";
      appendDots(dots, entries);
      cell.appendChild(dots);
    }

    // pointerdown statt click: click feuert auf Touch erst nach touchend und der
    // Gestenerkennung des Browsers — das fuehlte sich beim Antippen traege an.
    cell.addEventListener("pointerdown", (ev) => {
      ev.stopPropagation();
      resetFooterIdleTimer();
      selectDay(ymd);
    });

    els.calendarGrid.appendChild(cell);
  }
}

async function fetchLocationConfig() {
  try {
    const data = await fetchJsonWithTimeout("/api/config", 6000);
    return data?.settings?.location || null;
  } catch (e) {
    return null;
  }
}

// The place can be changed from the phone while the kiosk keeps running.
async function pollLocationConfig() {
  const next = await fetchLocationConfig();
  if (!next || !next.name || !next.state) return;
  if (next.name === locationConfig?.name && next.state === locationConfig?.state) return;
  locationConfig = next;
  state.footer.location = next;
  renderLocation();
  lastWeatherRefresh = 0;
  refreshWeather();
  refreshHolidays();
}

async function fetchWeather(location, mode) {
  const name = encodeURIComponent(location.name);
  const state = encodeURIComponent(location.state);
  return fetchJsonWithTimeout(`/api/weather?name=${name}&state=${state}&mode=${mode}`, 8000);
}

async function fetchHolidays(location, year, mode) {
  const state = encodeURIComponent(location.state);
  return fetchJsonWithTimeout(`/api/holidays?state=${state}&year=${year}&mode=${mode}`, 8000);
}

async function refreshWeather() {
  if (!locationConfig) return;
  const now = Date.now();
  if (weatherRefreshInFlight) return;
  if (now - lastWeatherRefresh < WEATHER_MIN_REFRESH_MS) return;
  weatherRefreshInFlight = true;
  try {
    const data = await fetchWeather(locationConfig, "refresh");
    weatherData = data;
    lastWeatherRefresh = Date.now();
    state.footer.lastWeatherRefreshMs = lastWeatherRefresh;
    renderCollapsedWeather();
    renderExpandedWeather();
  } finally {
    weatherRefreshInFlight = false;
  }
}

async function refreshHolidays() {
  if (!locationConfig) return;
  const year = new Date().getFullYear();
  try {
    const data = await fetchHolidays(locationConfig, year, "refresh");
    holidaysData = data;
    state.footer.holidaysStatus = holidaysData?.status || null;
    state.footer.holidaysUpdatedAt = holidaysData?.updated_at || null;
    renderHoliday();
    renderCalendar();
    renderEventsBadge();
    renderEventsList();
  } catch (e) {}
}

// Events are edited from the phone, so they are polled like the location.
// Re-rendering only on a real change keeps the idle CPU flat.
async function refreshEvents() {
  try {
    const data = await fetchJsonWithTimeout("/api/events", 6000);
    const next = Array.isArray(data?.events) ? data.events : [];
    const serialized = JSON.stringify(next);
    if (eventsLoaded && serialized === eventsSerialized) return;
    eventsSerialized = serialized;
    eventsData = next;
    eventsLoaded = true;
    state.footer.eventsCount = next.length;
    renderEventsBadge();
    renderEventsList();
    renderCalendar();
  } catch (e) {}
}

async function requestShutdown() {
  if (shutdownInFlight) return;
  const confirmed = window.confirm("System jetzt herunterfahren?");
  if (!confirmed) return;

  shutdownInFlight = true;
  if (els.shutdownBtn) els.shutdownBtn.disabled = true;
  setOverlay(true, "Herunterfahren…", "Sende Ausschaltbefehl…");

  try {
    const data = await postJsonWithTimeout("/api/admin/shutdown", {}, 7000);
    const status = data?.status || "unknown";
    if (status !== "started" && status !== "busy") {
      throw new Error(data?.error || data?.message || "Unerwartete Antwort vom Server");
    }
    if (status === "busy") {
      setOverlay(true, "Herunterfahren…", "Herunterfahren wurde bereits gestartet.");
      return;
    }
    setOverlay(true, "Herunterfahren…", "System wird heruntergefahren.");
  } catch (e) {
    const msg = String(e?.message || e);
    setOverlay(true, "Herunterfahren fehlgeschlagen", msg);
    shutdownInFlight = false;
    if (els.shutdownBtn) els.shutdownBtn.disabled = false;
    setTimeout(() => setOverlay(false), 5000);
  }
}

function attachFooterHandlers() {
  if (els.footerCollapsed) {
    els.footerCollapsed.addEventListener("click", () => setExpanded(!footerExpanded));
    els.footerCollapsed.addEventListener("touchstart", () => setExpanded(!footerExpanded), { passive: true });
  }
  if (els.footerExpanded) {
    els.footerExpanded.addEventListener("click", resetFooterIdleTimer);
    els.footerExpanded.addEventListener("touchstart", resetFooterIdleTimer, { passive: true });
  }
  if (els.shutdownBtn) {
    els.shutdownBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      requestShutdown();
    });
    els.shutdownBtn.addEventListener("touchstart", (ev) => {
      ev.stopPropagation();
    }, { passive: true });
  }
}

export async function bootFooter() {
  attachFooterHandlers();
  renderCalendar();

  locationConfig = await fetchLocationConfig();
  state.footer.location = locationConfig;
  if (!locationConfig) return;
  renderLocation();

  // No geocoding here: GET /api/config already refreshes the geocode cache
  // from the stored coordinates, so the weather fetch always finds it.
  fetchWeather(locationConfig, "cache").then((data) => {
    weatherData = data;
    state.footer.weatherStatus = weatherData?.status || null;
    state.footer.weatherUpdatedAt = weatherData?.updated_at || null;
    renderCollapsedWeather();
    renderExpandedWeather();
  }).catch(() => {});

  const year = new Date().getFullYear();
  fetchHolidays(locationConfig, year, "cache").then((data) => {
    holidaysData = data;
    state.footer.holidaysStatus = holidaysData?.status || null;
    state.footer.holidaysUpdatedAt = holidaysData?.updated_at || null;
    renderHoliday();
    renderCalendar();
  }).catch(() => {});

  refreshWeather();
  refreshHolidays();
  refreshEvents();

  if (weatherRefreshTimer) clearInterval(weatherRefreshTimer);
  weatherRefreshTimer = setInterval(refreshWeather, WEATHER_REFRESH_INTERVAL_MS);

  if (configPollTimer) clearInterval(configPollTimer);
  configPollTimer = setInterval(() => {
    pollLocationConfig().catch(() => {});
    refreshEvents().catch(() => {});
  }, CONFIG_POLL_MS);
}
