import { useEffect, useState } from "react";
import { getJson } from "./api.js";

/**
 * Fetch `path` with `params`; refetch when they change. Keeps the previous data
 * while a refetch is in flight so charts dim instead of flashing.
 * Pass params = null to skip fetching.
 */
export function useApi(path, params) {
  const key = params === null ? null : `${path}?${JSON.stringify(params)}`;
  const [state, setState] = useState({ data: null, error: null, loading: key !== null, waiting: false });

  useEffect(() => {
    if (key === null) return undefined;
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    getJson(path, params, {
      signal: controller.signal,
      onWaiting: (waiting) => setState((s) => ({ ...s, waiting })),
    })
      .then((data) => setState({ data, error: null, loading: false, waiting: false }))
      .catch((error) => {
        if (error.name !== "AbortError") setState((s) => ({ ...s, error, loading: false, waiting: false }));
      });
    return () => controller.abort();
    // `key` captures path + params by value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
