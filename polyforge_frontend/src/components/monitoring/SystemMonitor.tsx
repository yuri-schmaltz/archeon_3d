/**
 * SystemMonitor — vertical stack of system metrics.
 *
 * Replaces the grid-of-cards layout. Each metric is a row with a
 * mono label on the left, the value on the right, and a hairline
 * divider between rows. Reads as a control panel readout.
 */
import React, { useEffect, useState } from "react";
import type { SystemMetrics } from "../../api/types";
import { apiClient } from "../../api/client";
import { Text, StatusDot, Stack, type StatusKind } from "../../design/primitives";

function pickKind(metrics: SystemMetrics | null, error: string | null): StatusKind {
  if (error) return "off";
  if (!metrics) return "queued";
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

// The backend may return process metrics nested (current shape) or flat
// (legacy). These helpers normalise both so the rows below stay clean.
function cpuPct(m: SystemMetrics): number | null {
  if (m.process?.cpu_percent !== undefined) return m.process.cpu_percent;
  return m.cpu_percent ?? null;
}
function ramMb(m: SystemMetrics): number | null {
  if (m.process?.rss_mb !== undefined) return m.process.rss_mb;
  if (m.ram_bytes !== undefined) return m.ram_bytes / (1024 * 1024);
  return null;
}
function gpuPct(m: SystemMetrics): number | null {
  return m.gpu_percent ?? null;
}
function gpuMemUsed(m: SystemMetrics): number | null {
  if (m.gpu?.memory_allocated_mb !== undefined) {
    return m.gpu.memory_allocated_mb * (1024 * 1024);
  }
  return m.gpu_mem_used ?? null;
}
function gpuMemTotal(m: SystemMetrics): number | null {
  if (m.gpu?.memory_total_mb !== undefined) {
    return m.gpu.memory_total_mb * (1024 * 1024);
  }
  return m.gpu_mem_total ?? null;
}

export const SystemMonitor: React.FC = () => {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const fetchMetrics = async () => {
      try {
        const response = await apiClient.get<SystemMetrics>("/system/metrics");
        if (!alive) return;
        setMetrics(response.data);
        setError(null);
      } catch (err) {
        if (!alive) return;
        console.error("Failed to fetch metrics", err);
        setError("Offline");
      }
    };
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 2000);
    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, []);

  const kind = pickKind(metrics, error);
  const cpu = metrics ? cpuPct(metrics) : null;
  const ramBytes = metrics
    ? ramMb(metrics) !== null
      ? ramMb(metrics)! * (1024 * 1024)
      : null
    : null;
  const gpuU = metrics ? gpuPct(metrics) : null;
  const gpuUsed = metrics ? gpuMemUsed(metrics) : null;
  const gpuTotal = metrics ? gpuMemTotal(metrics) : null;
  const jobsInMem = metrics?.jobs_in_memory;
  const jobsInStore = metrics?.jobs_in_store;
  const persist = metrics?.persistence_enabled;
  const uptime = metrics?.uptime_seconds;

  return (
    <Stack gap={0} className="divide-y divide-border">
      <Row
        label="CPU (process)"
        value={cpu !== null ? `${cpu.toFixed(1)}%` : "—"}
        kind={kind}
      />
      <Row label="RAM (process)" value={fmtBytes(ramBytes)} kind={kind} />
      {gpuU !== null && (
        <Row label="GPU" value={`${gpuU.toFixed(1)}%`} kind={kind} />
      )}
      {gpuUsed !== null && gpuTotal !== null && (
        <Row
          label="VRAM"
          value={`${fmtBytes(gpuUsed)} / ${fmtBytes(gpuTotal)}`}
          kind={kind}
        />
      )}
      <Row
        label="Jobs in mem"
        value={jobsInMem !== undefined ? String(jobsInMem) : "—"}
        kind={kind}
      />
      <Row
        label="Jobs in store"
        value={jobsInStore !== undefined ? String(jobsInStore) : "—"}
        kind={kind}
      />
      <Row label="Persistence" value={persist ? "on" : "off"} kind={kind} />
      <Row
        label="Uptime"
        value={uptime !== undefined ? formatUptime(uptime) : "—"}
        kind={kind}
      />
    </Stack>
  );
};

const Row: React.FC<{ label: string; value: string; kind: StatusKind }> = ({
  label,
  value,
  kind,
}) => (
  <div className="py-3 flex items-baseline justify-between gap-3">
    <div className="flex items-center gap-2">
      <StatusDot kind={kind} size={5} />
      <Text
        voice="mono"
        size="2xs"
        tone="muted"
        tracking="widest"
        uppercase
      >
        {label}
      </Text>
    </div>
    <Text voice="mono" size="sm" tone="fg" className="tabular-nums">
      {value}
    </Text>
  </div>
);

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d`;
}
