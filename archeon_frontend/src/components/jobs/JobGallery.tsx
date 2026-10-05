/**
 * JobGallery — list of recent jobs.
 *
 * Replaces the boxy card grid with a hairline-separated row list.
 * Each row is a horizontal slab with three zones:
 *   1. Status glyph (large) on the left.
 *   2. Job metadata in the middle.
 *   3. Action buttons on the right.
 *
 * Rows hover with a subtle surface change. The status filter is a
 * row of underline tabs (matching the new ModeChips aesthetic).
 */
import React, { useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiClient, BASE_URL, errorMessage } from "../../api/client";
import { JobStatus } from "../../api/types";
import type { JobResponse, JobStatusType } from "../../api/types";
import { X, Download, Scissors, Eye, EyeOff } from "lucide-react";
import { MeshPreview } from "./MeshPreview";
import { useJobEvents } from "../../context/useJobEvents";
import {
  Text,
  StatusDot,
  Stack,
  Button,
  Divider,
  Pill,
  type StatusKind,
} from "../../design/primitives";

type StatusFilter = "all" | JobStatusType;

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: JobStatus.QUEUED, label: "Queued" },
  { key: JobStatus.PROCESSING, label: "Processing" },
  { key: JobStatus.COMPLETED, label: "Completed" },
  { key: JobStatus.FAILED, label: "Failed" },
  { key: JobStatus.CANCELLED, label: "Cancelled" },
];

const kindByStatus: Record<JobStatusType, StatusKind> = {
  queued: "queued",
  processing: "live",
  completed: "done",
  failed: "failed",
  cancelled: "cancelled",
};

export const JobGallery: React.FC = () => {
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingUid, setPendingUid] = useState<string | null>(null);
  const [previewingUid, setPreviewingUid] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const { jobs: streamJobs, isFallback: listIsFallback, connected: listConnected,
    loading, lastError, refetch: refetchList } = useJobEvents();
  const error = actionError ?? lastError;
  const jobs = useMemo(() => [...streamJobs].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  ), [streamJobs]);

  const handleCancel = async (uid: string) => {
    setPendingUid(uid);
    setActionError(null);
    try {
      await apiClient.delete(`/jobs/${uid}`);
      refetchList();
    } catch (err) {
      console.error(err);
      setActionError(errorMessage(err));
    } finally { setPendingUid(null); }
  };

  const handleOptimize = async (uid: string) => {
    setPendingUid(uid);
    setActionError(null);
    try {
      const res = await apiClient.post<{ file_path: string }>(
        "/meshops/process",
        { job_uid: uid, action: "decimate", ratio: 0.5 },
      );
      const fname = res.data.file_path.split("/").pop();
      window.open(
        `${BASE_URL}/files/${encodeURIComponent(fname ?? "")}`,
        "_blank",
      );
    } catch (err) {
      console.error(err);
      setActionError(errorMessage(err));
    } finally { setPendingUid(null); }
  };

  const previewUrl = (job: JobResponse): string | null => {
    if (!job.file_path) return null;
    const fname = job.file_path.split(/[\\/]/).pop();
    return `${BASE_URL}/files/${encodeURIComponent(fname ?? "")}`;
  };

  const previewedFromList = previewingUid
    ? jobs.find((j) => j.uid === previewingUid) ?? null
    : null;
  const previewedJob =
    previewedFromList;

  const visible =
    statusFilter === "all"
      ? jobs
      : jobs.filter((j) => j.status === statusFilter);

  return (
    <section className="bg-bg">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-3">
        <Stack gap={1}>
          <Text
            voice="mono"
            size="2xs"
            tone="muted"
            tracking="widest"
            uppercase
          >
            Job stream
          </Text>
          <Text as="h2" voice="display" size="xl" tracking="tight">
            Recent jobs
          </Text>
        </Stack>
        <Stack direction="row" gap={3} align="center">
          <Stack direction="row" gap={2} align="center">
            <StatusDot kind={listConnected ? "live" : "off"} size={5} />
            <Text
              voice="mono"
              size="2xs"
              tone="muted"
              tracking="widest"
              uppercase
            >
              {listIsFallback
                ? "polling"
                : listConnected
                ? "live"
                : "connecting"}
            </Text>
          </Stack>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetchList()}
            aria-label="Refresh jobs"
          >
            ↻ Refresh
          </Button>
        </Stack>
      </div>
      <Divider />

      {/* Status filter row */}
      <div
        role="group"
        aria-label="Filter jobs by status"
        className="flex border-b border-border overflow-x-auto"
      >
        {STATUS_FILTERS.map((f) => {
          const count =
            f.key === "all"
              ? jobs.length
              : jobs.filter((j) => j.status === f.key).length;
          const isActive = statusFilter === f.key;
          return (
            <button
              key={f.key}
              aria-pressed={isActive}
              onClick={() => setStatusFilter(f.key)}
              className={
                "px-4 h-10 flex items-center gap-2 " +
                "font-mono text-xs uppercase tracking-wider " +
                "border-b-2 -mb-px transition-colors duration-[120ms] " +
                (isActive
                  ? "border-accent text-fg"
                  : "border-transparent text-fg-muted hover:text-fg")
              }
            >
              <span>{f.label}</span>
              <Text
                voice="mono"
                size="2xs"
                tone="dim"
                as="span"
                className="tabular-nums"
              >
                {String(count).padStart(2, "0")}
              </Text>
            </button>
          );
        })}
      </div>

      {/* Error line */}
      {error && (
        <div role="alert" className="py-3">
          <Pill tone="danger">{error}</Pill>
        </div>
      )}

      {/* Preview pane */}
      <AnimatePresence>
        {previewedJob && previewUrl(previewedJob) && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
            className="overflow-hidden"
          >
            <div className="py-4">
              <div className="flex items-center justify-between mb-2">
                <Stack direction="row" gap={2} align="center">
                  <StatusDot
                    kind={
                      previewedJob
                        ? kindByStatus[previewedJob.status]
                        : "idle"
                    }
                  />
                  <Text
                    voice="mono"
                    size="2xs"
                    tone="muted"
                    tracking="widest"
                    uppercase
                  >
                    Preview
                  </Text>
                  <Text
                    voice="mono"
                    size="2xs"
                    tone="fg"
                    tracking="wider"
                  >
                    {previewedJob.uid.slice(0, 8)}
                  </Text>
                  <Text
                    voice="mono"
                    size="2xs"
                    tone="dim"
                    tracking="wider"
                  >
                    {listIsFallback ? "· polling" : listConnected ? "· live" : "· connecting"}
                  </Text>
                </Stack>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPreviewingUid(null)}
                  aria-label="Close preview"
                >
                  Close ×
                </Button>
              </div>
              <MeshPreview
                src={previewUrl(previewedJob)!}
                alt={`Mesh for job ${previewedJob.uid}`}
                height={320}
              />
            </div>
            <Divider />
          </motion.div>
        )}
      </AnimatePresence>

      {/* List */}
      <div className="divide-y divide-border">
        {loading && jobs.length === 0 && (
          <div className="py-8 text-center" role="status" aria-live="polite">
            <Text voice="mono" size="xs" tone="dim" tracking="widest" uppercase>
              Loading jobs…
            </Text>
          </div>
        )}
        {!loading && jobs.length === 0 && !error && (
          <div className="py-8 text-center">
            <Text voice="mono" size="xs" tone="dim" tracking="widest" uppercase>
              No jobs found
            </Text>
          </div>
        )}
        {jobs.length > 0 && visible.length === 0 && (
          <div className="py-8 text-center">
            <Text voice="mono" size="xs" tone="dim" tracking="widest" uppercase>
              No jobs match this filter
            </Text>
          </div>
        )}
        <AnimatePresence initial={false}>
          {visible.map((job) => (
            <JobRow
              key={job.uid}
              job={job}
              pending={pendingUid === job.uid}
              isPreviewing={previewingUid === job.uid}
              onPreviewToggle={() =>
                setPreviewingUid(previewingUid === job.uid ? null : job.uid)
              }
              onCancel={() => handleCancel(job.uid)}
              onOptimize={() => handleOptimize(job.uid)}
              previewUrl={previewUrl(job)}
            />
          ))}
        </AnimatePresence>
      </div>
    </section>
  );
};

// ---------------------------------------------------------------- row

const JobRow: React.FC<{
  job: JobResponse;
  pending: boolean;
  isPreviewing: boolean;
  previewUrl: string | null;
  onPreviewToggle: () => void;
  onCancel: () => void;
  onOptimize: () => void;
}> = ({ job, pending, isPreviewing, previewUrl, onPreviewToggle, onCancel, onOptimize }) => {
  const kind = kindByStatus[job.status];
  const isDone = job.status === JobStatus.COMPLETED;
  const isCancellable =
    job.status === JobStatus.QUEUED;
  const time = new Date(job.created_at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
      className="group grid grid-cols-[auto_1fr] sm:grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-3 sm:gap-6 px-2 py-4 hover:bg-surface-1 transition-colors"
    >
      <StatusDot kind={kind} size={8} />
      <div className="min-w-0">
        <Stack direction="row" gap={3} align="baseline">
          <Text
            voice="mono"
            size="sm"
            tone="fg"
            tracking="wider"
            className="truncate"
          >
            {job.uid.slice(0, 8)}
          </Text>
          <Pill tone={kind === "done" ? "success" : kind === "failed" ? "danger" : kind === "live" ? "accent" : "neutral"}>
            {job.status}
          </Pill>
        </Stack>
        <Text
          voice="mono"
          size="2xs"
          tone="dim"
          tracking="wider"
          as="div"
          className="mt-1"
        >
          {new Date(job.created_at).toLocaleDateString()} · {time} · {job.request_type ?? "Generation"}
        </Text>
        {job.error && <p className="text-sm text-danger mt-2 break-words">{job.error}</p>}
      </div>
      <Stack direction="row" gap={2} align="center" className="col-start-2 sm:col-start-auto">
        {isDone && previewUrl && (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={onPreviewToggle}
              aria-label={isPreviewing ? "Hide preview" : "Show preview"}
              title={isPreviewing ? "Hide preview" : "Show preview"}
            >
              {isPreviewing ? <EyeOff size={12} /> : <Eye size={12} />}
            </Button>
            <a
              href={previewUrl}
              target="_blank"
              rel="noreferrer noopener"
              className={
                "inline-flex items-center justify-center gap-2 h-9 max-sm:h-11 px-3 " +
                "rounded-sm font-mono uppercase tracking-wider " +
                "text-[11px] text-fg-muted hover:text-fg hover:bg-surface-2 " +
                "transition-colors duration-[120ms]"
              }
              title="Download"
              aria-label="Download mesh"
            >
              <Download size={12} />
            </a>
            <Button
              variant="ghost"
              size="sm"
              onClick={onOptimize}
              disabled={pending}
              title="Optimize (Decimate 50%)"
              aria-label="Optimize mesh"
            >
              <Scissors size={12} />
            </Button>
          </>
        )}
        {isCancellable && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onCancel}
            disabled={pending}
            title="Cancel job"
            aria-label="Cancel job"
          >
            <X size={12} />
          </Button>
        )}
      </Stack>
    </motion.article>
  );
};
