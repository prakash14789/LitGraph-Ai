import { type ClassValue, clsx } from "clsx";
import { isAxiosError } from "axios";
import { twMerge } from "tailwind-merge";

// shadcn/ui's standard helper — merges Tailwind classes, letting later
// classes in the list win over earlier conflicting ones (e.g. a caller's
// className overriding a component's default padding).
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Live finding 2026-08-20: every query-failure catch block (chat, compare)
// discarded the real error into the same hardcoded string, regardless of
// what the backend actually said — so a genuine, distinguishable "every LLM
// provider is rate-limited right now, try again later" (middleware.py's own
// 503) rendered identically to a real server crash. Backend's `detail`
// string is meant to be shown; use it when present, fall back to
// `fallback` only when the response truly carries nothing useful (network
// down, CORS, a non-JSON error page).
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return fallback;
}
