/**
 * Pill — small tag combining an optional icon/dot, a label, and a tone.
 *
 * Used for status tags, file-type labels, and counts. Mono voice
 * with a wide tracking and small text.
 */
import React from "react";
import { clsx } from "clsx";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info" | "muted";

const toneClass: Record<Tone, string> = {
  neutral: "text-fg-muted border-border-strong",
  accent: "text-accent border-accent/40",
  success: "text-success border-success/40",
  warning: "text-warning border-warning/40",
  danger: "text-danger border-danger/40",
  info: "text-fg-muted border-border",
  muted: "text-fg-muted border-border",
};

export interface PillProps {
  tone?: Tone;
  className?: string;
  children: React.ReactNode;
}

export const Pill: React.FC<PillProps> = ({ tone = "neutral", className, children }) => (
  <span
    className={clsx(
      "inline-flex items-center gap-1.5 h-5 px-2 rounded-sm",
      "border bg-surface-1",
      "font-mono text-[10px] uppercase tracking-widest",
      toneClass[tone],
      className,
    )}
  >
    {children}
  </span>
);
