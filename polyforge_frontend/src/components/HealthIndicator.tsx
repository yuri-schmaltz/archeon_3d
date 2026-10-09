/**
 * HealthIndicator — compact status dot for the bottom tab bar.
 *
 * Reads from the same ``useSystemMetrics`` hook that the sidebar
 * monitor uses, so a single polling loop powers every indicator
 * in the app. Falls back to the SSE connection state from
 * ``useJobEvents`` when metrics are not yet available.
 *
 * Rendered as a small accent dot at the top-right of the tab bar
 * so users on mobile can see at a glance whether the backend is
 * healthy without leaving the current screen.
 */
import React from "react";
import { useSystemMetrics } from "../hooks/useSystemMetrics";
import { useJobEvents } from "../context/useJobEvents";
import { StatusDot } from "../design/primitives";
import { clsx } from "clsx";
import { useT } from "../i18n";

export interface HealthIndicatorProps {
  /** Render in a compact pill (icon + label) instead of a bare dot. */
  variant?: "dot" | "pill";
  className?: string;
}

export const HealthIndicator: React.FC<HealthIndicatorProps> = ({
  variant = "dot",
  className,
}) => {
  const t = useT();
  const { metrics, error } = useSystemMetrics();
  const { connected } = useJobEvents();

  // Decision tree: prefer real metrics when the polling loop is
  // healthy, fall back to the SSE connection otherwise.
  let kind: "live" | "queued" | "off" = "queued";
  let label = t("strip.status.loading");
  if (error) {
    kind = "off";
    label = t("strip.status.offline");
  } else if (metrics) {
    kind = "live";
    label = t("strip.status.ready");
  } else if (connected) {
    // SSE is up but the first metrics poll hasn't arrived yet.
    kind = "queued";
    label = t("strip.status.loading");
  }

  if (variant === "dot") {
    return (
      <span
        role="status"
        aria-live="polite"
        aria-label={label}
        title={label}
        className={clsx("inline-block", className)}
      >
        <StatusDot kind={kind} size={6} />
      </span>
    );
  }

  return (
    <span
      role="status"
      aria-live="polite"
      className={clsx(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm",
        "bg-surface-2 border border-border",
        className,
      )}
    >
      <StatusDot kind={kind} size={5} />
      <span className="font-mono text-2xs uppercase tracking-widest text-fg-muted">
        {label}
      </span>
    </span>
  );
};
