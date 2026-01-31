export const state = {
  images: [],
  index: 0,
  showingA: true,
  timer: null,
  refreshTimer: null,
  debugEnabled: false,
  tap: { last: 0, count: 0 },
  lastError: null,
};

export function setLastError(value) {
  state.lastError = value;
}
