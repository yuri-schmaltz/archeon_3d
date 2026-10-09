/**
 * SkeletonRow — placeholder block used while async data is loading.
 *
 * Renders a stack of soft, hairline bars that pulse to communicate
 * "loading" without resorting to a spinner. The block is a vertical
 * stack of ``rows`` lines whose width follows a deterministic
 * pseudo-random sequence so the layout never looks identical on
 * different renders (which would feel broken to a careful reader).
 *
 * Use for:
 *   - Library list (replacement for an empty ``<ul/>`` while the
 *     first page of jobs is being fetched).
 *   - System metrics while the polling loop is in its first cycle.
 *   - Anywhere else a list/grid of similar cards is loading.
 */
import React from "react";
import { clsx } from "clsx";

export interface SkeletonRowProps {
  /** Number of rows to render. */
  rows?: number;
  /** Height of each row in tailwind classes (h-2, h-3, h-4, etc.). */
  rowHeight?: string;
  /** Vertical gap between rows in tailwind classes. */
  gap?: number;
  /** Class name of the outer container. */
  className?: string;
  /** Accessible label. Defaults to "Carregando…". */
  label?: string;
}

// Stable pseudo-random widths so the layout looks alive but never
// jumps. Index is the row number, hash is a tiny LCG.
const pseudoWidth = (index: number, seed = 17): number => {
  const x = Math.sin(index * seed + seed) * 10_000;
  const frac = x - Math.floor(x);
  // Clamp into a [60, 100] range so the bars look natural.
  return 60 + Math.floor(frac * 40);
};

export const SkeletonRow: React.FC<SkeletonRowProps> = ({
  rows = 3,
  rowHeight = "h-2.5",
  gap = 2,
  className,
  label = "Loading…",
}) => (
  <div
    role="status"
    aria-live="polite"
    aria-label={label}
    className={clsx("animate-pulse flex flex-col", className)}
    style={{ gap: `${gap * 0.25}rem` }}
  >
    {Array.from({ length: rows }).map((_, i) => (
      <div
        key={i}
        className={clsx(
          rowHeight,
          "rounded-sm bg-surface-3",
        )}
        style={{ width: `${pseudoWidth(i)}%` }}
      />
    ))}
  </div>
);

/**
 * SkeletonCard — slightly richer placeholder that mimics the
 * JobRow layout (uid / status / metadata). Useful for the first
 * paint of the library list.
 */
export const SkeletonCard: React.FC<{ className?: string }> = ({
  className,
}) => (
  <div
    role="status"
    aria-live="polite"
    aria-label="Loading job"
    className={clsx(
      "py-4 flex flex-col gap-2 border-b border-border",
      "animate-pulse",
      className,
    )}
  >
    <div className="flex items-center gap-2">
      <span className="h-2 w-12 rounded-sm bg-surface-3" />
      <span className="h-2 w-20 rounded-sm bg-surface-3" />
    </div>
    <span className="h-3 w-3/4 rounded-sm bg-surface-3" />
    <div className="flex items-center gap-2">
      <span className="h-2 w-10 rounded-sm bg-surface-3" />
      <span className="h-2 w-6 rounded-sm bg-surface-3" />
      <span className="h-2 w-16 rounded-sm bg-surface-3" />
    </div>
  </div>
);
