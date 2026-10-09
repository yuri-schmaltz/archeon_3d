/**
 * SystemMonitor — vertical stack of system metrics.
 *
 * Replaces the grid-of-cards layout. Each metric is a row with a
 * mono label on the left, the value on the right, and a hairline
 * divider between rows. Reads as a control panel readout.
 *
 * Polling is delegated to ``useSystemMetrics`` so other surfaces
 * (CapabilityStrip, mobile health indicator, etc.) can share the
 * same cached fetch loop without duplicating the cleanup logic.
 */
import React from "react";
import { useSystemMetrics } from "../../hooks/useSystemMetrics";
import { Text, StatusDot, Stack, type StatusKind } from "../../design/primitives";
import { useT } from "../../i18n";

function pickKind(
  hasError: boolean,
  hasData: boolean,
  status: ReturnType<typeof useSystemMetrics>["status"],
): StatusKind {
  if (hasError) return "off";
  if (!hasData) return "queued";
  if (status === "loading") return "queued";
  return "live";
}

function fmtBytes(n: number | undefined | null): string {
  if (n == null || !isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "K", "M", "G", "T"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

type UpTimeFormatter = (
  seconds: number,
  t: (key: string, vars?: Record<string, string | number>) => string,
) => string;

const formatUptime: UpTimeFormatter = (seconds, t) => {
  if (seconds < 60) return t("monitor.uptime.s", { n: Math.floor(seconds) });
  if (seconds < 3600) return t("monitor.uptime.m", { n: Math.floor(seconds / 60) });
  if (seconds < 86_400) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return t("monitor.uptime.h", { n: h, m });
  }
  const d = Math.floor(seconds / 86_400);
  const h = Math.floor((seconds % 86_400) / 3600);
  return t("monitor.uptime.d", { n: d, h });
};

export interface SystemMonitorProps {
  /** Compact rendering: smaller font + tighter rows. */
  dense?: boolean;
  /** Hide the persistence / jobs / uptime rows; show only live resources. */
  resourcesOnly?: boolean;
}

export const SystemMonitor: React.FC<SystemMonitorProps> = ({
  dense = false,
  resourcesOnly = false,
}) => {
  const t = useT();
  const { metrics, error, status } = useSystemMetrics();

  const hasData = metrics !== null;
  const kind = pickKind(Boolean(error), hasData, status);
  const dash = t("monitor.dash");

  const cpu = hasData
    ? metrics!.process?.cpu_percent !== undefined
      ? metrics!.process!.cpu_percent
      : metrics!.cpu_percent !== undefined
        ? metrics!.cpu_percent!
        : null
    : null;
  const ramMb = hasData
    ? metrics!.process?.rss_mb !== undefined
      ? metrics!.process!.rss_mb
      : metrics!.ram_bytes !== undefined
        ? metrics!.ram_bytes! / (1024 * 1024)
        : null
    : null;
  const gpuU =
    hasData && metrics!.gpu_percent !== undefined ? metrics!.gpu_percent! : null;
  const gpuUsed = hasData
    ? metrics!.gpu?.memory_allocated_mb !== undefined
      ? metrics!.gpu!.memory_allocated_mb! * 1024 * 1024
      : metrics!.gpu_mem_used ?? null
    : null;
  const gpuTotal = hasData
    ? metrics!.gpu?.memory_total_mb !== undefined
      ? metrics!.gpu!.memory_total_mb! * 1024 * 1024
      : metrics!.gpu_mem_total ?? null
    : null;
  const jobsInMem = hasData ? metrics!.jobs_in_memory : undefined;
  const jobsInStore = hasData ? metrics!.jobs_in_store : undefined;
  const persist = hasData ? metrics!.persistence_enabled : undefined;
  const uptime = hasData ? metrics!.uptime_seconds : undefined;

  return (
    <Stack
      gap={0}
      className="divide-y divide-border"
      role="list"
      aria-label={t("system.metrics")}
    >
      <Row
        label={t("monitor.cpu")}
        value={cpu !== null ? `${cpu.toFixed(1)}%` : dash}
        kind={kind}
        dense={dense}
      />
      <Row
        label={t("monitor.ram")}
        value={fmtBytes(ramMb !== null ? ramMb * 1024 * 1024 : null)}
        kind={kind}
        dense={dense}
      />
      {gpuU !== null && (
        <Row
          label={t("monitor.gpu")}
          value={`${gpuU.toFixed(1)}%`}
          kind={kind}
          dense={dense}
        />
      )}
      {gpuUsed !== null && gpuTotal !== null && (
        <Row
          label={t("monitor.vram")}
          value={`${fmtBytes(gpuUsed)} / ${fmtBytes(gpuTotal)}`}
          kind={kind}
          dense={dense}
        />
      )}
      {!resourcesOnly && (
        <>
          <Row
            label={t("monitor.jobsInMem")}
            value={jobsInMem !== undefined ? String(jobsInMem) : dash}
            kind={kind}
            dense={dense}
          />
          <Row
            label={t("monitor.jobsInStore")}
            value={jobsInStore !== undefined ? String(jobsInStore) : dash}
            kind={kind}
            dense={dense}
          />
          <Row
            label={t("monitor.persistence")}
            value={
              persist === undefined
                ? dash
                : persist
                  ? t("monitor.persistence.on")
                  : t("monitor.persistence.off")
            }
            kind={kind}
            dense={dense}
          />
          <Row
            label={t("monitor.uptime")}
            value={uptime !== undefined ? formatUptime(uptime, t) : dash}
            kind={kind}
            dense={dense}
          />
        </>
      )}
      {error && (
        <p
          role="status"
          aria-live="polite"
          className="text-2xs font-mono text-danger mt-2"
        >
          {t("monitor.offline")}
        </p>
      )}
    </Stack>
  );
};

const Row: React.FC<{
  label: string;
  value: string;
  kind: StatusKind;
  dense?: boolean;
}> = ({ label, value, kind, dense }) => (
  <div
    role="listitem"
    className={`${dense ? "py-1.5" : "py-3"} flex items-baseline justify-between gap-3`}
  >
    <div className="flex items-center gap-2 min-w-0">
      <StatusDot kind={kind} size={5} />
      <Text
        voice="mono"
        size="2xs"
        tone="muted"
        tracking="widest"
        uppercase
        className="truncate"
      >
        {label}
      </Text>
    </div>
    <Text
      voice="mono"
      size={dense ? "2xs" : "sm"}
      tone="fg"
      className="tabular-nums shrink-0"
    >
      {value}
    </Text>
  </div>
);
