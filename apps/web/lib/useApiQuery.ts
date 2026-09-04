"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type QueryState<T> =
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "success"; data: T };

export function useApiQuery<T>(
  key: string,
  fetcher: () => Promise<T>,
  options?: { enabled?: boolean; refreshMs?: number },
): QueryState<T> & { reload: () => void } {
  const enabled = options?.enabled ?? true;
  const [state, setState] = useState<QueryState<T>>({ status: "loading" });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(() => {
    if (!enabled) {
      return;
    }
    let cancelled = false;
    void fetcherRef.current()
      .then((data) => {
        if (!cancelled) {
          setState({ status: "success", data });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            error: error instanceof Error ? error : new Error("Request failed"),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    setState({ status: "loading" });
    const cancel = load();
    return cancel;
  }, [enabled, key, load]);

  useEffect(() => {
    if (!enabled || !options?.refreshMs) {
      return;
    }
    const timer = window.setInterval(() => {
      void fetcherRef.current()
        .then((data) => setState({ status: "success", data }))
        .catch(() => undefined);
    }, options.refreshMs);
    return () => window.clearInterval(timer);
  }, [enabled, options?.refreshMs, key]);

  const reload = useCallback(() => {
    void load();
  }, [load]);

  return useMemo(() => ({ ...state, reload }), [state, reload]);
}
