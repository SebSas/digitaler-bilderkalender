export const state = {
  images: [],
  index: 0,
  showingA: true,
  timer: null,
  refreshTimer: null,
  debugEnabled: false,
  tap: { last: 0, count: 0 },
  lastError: null,
  footer: {
    expanded: false,
    location: null,
    weatherStatus: null,
    weatherUpdatedAt: null,
    holidaysStatus: null,
    holidaysUpdatedAt: null,
    lastWeatherRefreshMs: null,
  },
  admin: {
    syncStatus: null,
    syncDetail: null,
  },
  system: {
    status: null,
    temp_c: null,
    cpu_usage_pct: null,
    memory: null,
    uptime_s: null,
    wifi: null,
    tailscale: null,
    fetchedAt: null,
    error: null,
  },
};

export function setLastError(value) {
  state.lastError = value;
}
