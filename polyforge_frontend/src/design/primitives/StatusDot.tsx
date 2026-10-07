/**
 * StatusDot — small LED indicator.
 *
 * Three states, each with its own colour and animation. The "live"
 * state pulses with two layered animations (the core + a fading
 * halo) so it reads as a real instrument, not a flat badge.
 *
 * The dot is 6px by default but accepts a ``size`` prop for use in
 * compact rows.
 */
import React from "react";
import { clsx } from "clsx";

export type StatusKind =
  | "live"        // actively processing, SSE connected
  | "queued"      // waiting
  | "done"        // completed
  | "failed"      // failed
  | "cancelled"   // cancelled by user
  | "idle"        // connected but nothing happening
  | "off";        // disconnected

const colorByKind: Record<StatusKind, string> = {
  live: "bg-accent",
  queued: "bg-warning",
  done: "bg-success",
  failed: "bg-danger",
  cancelled: "bg-fg-dim",
  idle: "bg-fg-muted",
  off: "bg-fg-dim",
};

export interface StatusDotProps {
  kind: StatusKind;
  size?: number; // px, default 6
  pulse?: boolean; // explicit override; defaults by kind
  className?: string;
}

export const StatusDot: React.FC<StatusDotProps> = ({
  kind,
  size = 6,
  pulse,
  className,
}) => {
  const shouldPulse = pulse ?? (kind === "live");
  return (
    <span
      className={clsx("relative inline-block rounded-full", className)}
      style={{ width: size, height: size }}
      aria-label={kind}
    >
      <span
        className={clsx(
          "absolute inset-0 rounded-full",
          colorByKind[kind],
          shouldPulse && "animate-pulse",
        )}
      />
      {kind === "live" && (
        <span
          className={clsx(
            "absolute inset-0 rounded-full bg-accent/40 animate-ping",
          )}
        />
      )}
    </span>
  );
};
