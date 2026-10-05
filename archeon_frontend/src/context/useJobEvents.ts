import { createContext, useContext } from "react";
import type { JobEvent, JobResponse } from "../api/types";

/**
 * A simple pub/sub channel so any component (e.g. CreateJobForm) can
 * notify the rest of the UI that a new job was submitted, without
 * lifting the job list state up to App.tsx or introducing a heavier
 * state library.
 *
 * Listeners register a callback via ``onJobSubmitted``; the form
 * calls ``notifyJobSubmitted`` after a successful POST.
 *
 * The provider also surfaces the most recent list of SSE events
 * and the connection state so chrome components (header, footer
 * ticker) can render without each subscribing to the stream
 * themselves.
 */
export interface JobEvents {
  /** Subscribe to "a new job was just submitted" events. */
  onJobSubmitted: (cb: () => void) => () => void;
  /** Fire-and-forget notification. */
  notifyJobSubmitted: () => void;
  /** Monotonically increasing counter for the last submitted job (debug). */
  submissionCount: number;
  /** Most recent SSE events (oldest first, capped). */
  events: JobEvent[];
  /** True while the list-SSE stream is connected. */
  connected: boolean;
  /** True if the stream fell back to polling. */
  isFallback: boolean;
  /** Last stream error message, if any. */
  lastError: string | null;
  /** Force a re-fetch (used after submitting a new job). */
  refetch: () => void;
  /** Current snapshot of jobs (sorted by created_at desc). */
  jobs: JobResponse[];
  loading: boolean;
}

export const JobEventsContext = createContext<JobEvents | null>(null);

/** Hook for consuming the JobEvents context. */
export function useJobEvents(): JobEvents {
  const ctx = useContext(JobEventsContext);
  if (!ctx) {
    throw new Error("useJobEvents must be used within a <JobEventsProvider>");
  }
  return ctx;
}
