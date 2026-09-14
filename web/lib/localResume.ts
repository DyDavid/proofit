const STORAGE_KEY = "proofit:last-resume";

export interface RememberedResume {
  id: string;
  filename: string;
  size: number;
}

/**
 * Remembers the last uploaded resume in the browser so reopening the Analyze
 * page doesn't require re-uploading. This only survives as long as the
 * backend's in-memory store does (api/store.py) — a server restart still
 * invalidates the id, which callers should handle via clearRememberedResume.
 */
export function loadRememberedResume(): RememberedResume | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      typeof parsed?.id === "string" &&
      typeof parsed?.filename === "string" &&
      typeof parsed?.size === "number"
    ) {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

export function saveRememberedResume(resume: RememberedResume): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(resume));
  } catch {
    // Private browsing / storage disabled / quota exceeded — non-fatal, just
    // means the next visit will ask for the resume again.
  }
}

export function clearRememberedResume(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to do if storage access itself throws.
  }
}
