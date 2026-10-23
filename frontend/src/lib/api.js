// Thin fetch wrapper for the WindDesk API.
// VITE_API_BASE_URL is baked in at build time (e.g. the Heroku URL on Vercel);
// when empty, requests are same-origin and the Vite dev server proxies /api.

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(id);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

export function buildUrl(path, params = {}) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""),
  ).toString();
  return `${API_BASE}${path}${query ? `?${query}` : ""}`;
}

/**
 * GET JSON. While the backend is still loading data (HTTP 503 - e.g. a Heroku
 * dyno waking up) the request is retried, and `onWaiting` lets the UI say so.
 */
export async function getJson(path, params, { signal, onWaiting, retries = 8 } = {}) {
  const url = buildUrl(path, params);
  for (let attempt = 0; ; attempt++) {
    let response;
    try {
      response = await fetch(url, { signal });
    } catch (err) {
      if (err.name === "AbortError" || attempt >= retries) throw err;
      onWaiting?.(true);
      await sleep(3000, signal);
      continue;
    }
    if (response.status === 503 && attempt < retries) {
      onWaiting?.(true);
      await sleep(3000, signal);
      continue;
    }
    onWaiting?.(false);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail = typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`;
      throw new ApiError(detail, response.status);
    }
    return response.json();
  }
}
