import { setLastError } from "./state.js";

export function imageUrl(id) {
  return `/api/image/${id}`;
}

export function preload(id) {
  return new Promise((resolve) => {
    const url = imageUrl(id);
    const img = new Image();
    img.onload = () => resolve(true);
    img.onerror = () => {
      setLastError(`Image failed to load: ${url}`);
      resolve(false);
    };
    img.src = url;
  });
}
