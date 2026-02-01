import { els } from "./dom.js";
import { fetchJsonWithTimeout } from "./api.js";
import { state } from "./state.js";
import { iconSvg } from "./icons.js";

const FOOTER_IDLE_MS = 15000;
const WEATHER_REFRESH_INTERVAL_MS = 45 * 60 * 1000;
const WEATHER_MIN_REFRESH_MS = 30 * 60 * 1000;

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
let footerExpanded = false;
let footerIdleTimer = null;
let weatherRefreshTimer = null;
let weatherRefreshInFlight = false;
let lastWeatherRefresh = 0;

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
  } else if (footerIdleTimer) {
    clearTimeout(footerIdleTimer);
    footerIdleTimer = null;
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
  els.weatherPillLine1.innerHTML = `${icon}<span class="weather-temp-inline">${temp}°C</span>`;
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
  if (els.weatherToday) els.weatherToday.style.display = "flex";

  const temp = weatherData.current?.temp_c;
  const condition = truncate(weatherData.current?.condition_text || "", 28);
  const icon = iconMarkup(weatherData.current?.icon);
  els.weatherTodayIcon.innerHTML = icon;
  els.weatherTodayTemp.textContent = `${temp}°C`;
  els.weatherTodayText.textContent = condition;

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
      const line2 = document.createElement("div");
      line2.className = "forecast-icon";
      line2.innerHTML = iconMarkup(day.icon);
      const line3 = document.createElement("div");
      line3.className = "forecast-temp";
      line3.textContent = `${day.min_c}/${day.max_c}°`;
      card.appendChild(line1);
      card.appendChild(line2);
      card.appendChild(line3);
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

    const cell = document.createElement("div");
    cell.className = "calendar-day";
    if (!inMonth) cell.classList.add("dim");
    if (toYmd(dateObj) === toYmd(now)) cell.classList.add("today");
    if (holidaySet.has(toYmd(dateObj))) cell.classList.add("holiday");
    cell.textContent = String(dateObj.getDate());

    if (holidaySet.has(toYmd(dateObj))) {
      const dot = document.createElement("span");
      dot.className = "holiday-dot";
      cell.appendChild(dot);
    }

    els.calendarGrid.appendChild(cell);
  }
}

async function fetchLocationConfig() {
  try {
    return await fetchJsonWithTimeout("/config/location.json", 6000);
  } catch (e) {
    return null;
  }
}

async function fetchGeocode(location) {
  const name = encodeURIComponent(location.name);
  const state = encodeURIComponent(location.state);
  return fetchJsonWithTimeout(`/api/geocode?name=${name}&state=${state}&mode=refresh`, 8000);
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
  } catch (e) {}
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
}

export async function bootFooter() {
  attachFooterHandlers();
  renderCalendar();

  locationConfig = await fetchLocationConfig();
  state.footer.location = locationConfig;
  if (!locationConfig) return;
  renderLocation();

  fetchGeocode(locationConfig).catch(() => {});

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

  if (weatherRefreshTimer) clearInterval(weatherRefreshTimer);
  weatherRefreshTimer = setInterval(refreshWeather, WEATHER_REFRESH_INTERVAL_MS);
}
