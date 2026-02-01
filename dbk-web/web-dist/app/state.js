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
};

export function setLastError(value) {
  state.lastError = value;
}
