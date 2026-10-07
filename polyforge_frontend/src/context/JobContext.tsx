import React, { useCallback, useEffect, useRef, useState, useMemo } from "react";
import { JobEventsContext, type JobEvents } from "./useJobEvents";
import { useJobListStream } from "../api/useJobListStream";
import { BASE_URL } from "../api/client";
import type { JobEvent, JobResponse } from "../api/types";

/**
 * Cap the in-memory event history so the context value doesn't
 * grow unbounded for long-running sessions.
 */
const MAX_EVENTS = 64;

/**
 * Build a synthetic ``JobEvent`` from a ``JobResponse`` so the
 * ticker/header can render a single uniform event log without
 * needing a separate ``/v1/events`` endpoint.
 */
function toEvent(job: JobResponse): JobEvent {
  return {
    uid: job.uid,
    status: job.status,
    at: job.updated_at ?? job.created_at,
    request_type: job.request_type,
  };
}

/** Provider component. Should wrap the entire app. */
export const JobEventsProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const listeners = useRef<Set<() => void>>(new Set());
  const [submissionCount, setSubmissionCount] = useState(0);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const statuses = useRef<Map<string, string>>(new Map());

  const { jobs, connected, isFallback, loading, error, refetch } =
    useJobListStream(BASE_URL);

  // Diff the streaming job list and append new entries to the event
  // log. Only statuses that change are recorded as new events.
  useEffect(() => {
    const list = Array.isArray(jobs) ? jobs : [];
    const currentIds = new Set(list.map((job) => job.uid));
    for (const uid of statuses.current.keys()) {
      if (!currentIds.has(uid)) statuses.current.delete(uid);
    }
    const fresh = list.filter((job) => statuses.current.get(job.uid) !== job.status);
    for (const job of fresh) statuses.current.set(job.uid, job.status);
    if (fresh.length) {
      const added = fresh.map(toEvent).sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
      setEvents((previous) => [...previous, ...added].slice(-MAX_EVENTS));
    }
  }, [jobs]);

  const onJobSubmitted = useCallback((cb: () => void) => {
    listeners.current.add(cb);
    return () => {
      listeners.current.delete(cb);
    };
  }, []);

  const notifyJobSubmitted = useCallback(() => {
    setSubmissionCount((n) => n + 1);
    refetch();
    for (const cb of listeners.current) {
      try {
        cb();
      } catch (err) {
        console.error("JobEvent listener threw:", err);
      }
    }
  }, [refetch]);

  const lastError = error ?? null;

  const value: JobEvents = useMemo(() => ({
    onJobSubmitted,
    notifyJobSubmitted,
    submissionCount,
    events,
    connected,
    isFallback,
    lastError,
    refetch,
    jobs,
    loading,
  }), [onJobSubmitted, notifyJobSubmitted, submissionCount, events, connected, isFallback, lastError, refetch, jobs, loading]);

  return (
    <JobEventsContext.Provider value={value}>
      {children}
    </JobEventsContext.Provider>
  );
};
