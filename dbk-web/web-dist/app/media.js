import { setLastError } from "./state.js";

export function imageUrl(id) {
  return `/api/image/${id}`;
}

export function preload(id) {
  const url = imageUrl(id);
  const img = new Image();
  img.src = url;
  // decode() waits for fetch AND decode, so a later showImage() finds a
  // ready-to-paint bitmap instead of paying the full decode on swipe (Pi 4).
  if (img.decode) {
    return img.decode().then(() => true).catch(() => {
      setLastError(`Image failed to load: ${url}`);
      return false;
    });
  }
  return new Promise((resolve) => {
    img.onload = () => resolve(true);
    img.onerror = () => {
      setLastError(`Image failed to load: ${url}`);
      resolve(false);
    };
  });
}
