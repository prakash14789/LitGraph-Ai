import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// shadcn/ui's standard helper — merges Tailwind classes, letting later
// classes in the list win over earlier conflicting ones (e.g. a caller's
// className overriding a component's default padding).
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
