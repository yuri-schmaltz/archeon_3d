/**
 * Stack — vertical or horizontal flex with tokenised gap.
 *
 * Use this for layout. Avoids hand-rolled margin/space-y classes
 * scattered through feature components.
 */
import React from "react";
import { clsx } from "clsx";

type Direction = "row" | "col";
type Align = "start" | "center" | "end" | "stretch" | "baseline";
type Justify = "start" | "center" | "end" | "between";

export interface StackProps {
  direction?: Direction;
  gap?: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 8 | 10 | 12;
  align?: Align;
  justify?: Justify;
  wrap?: boolean;
  className?: string;
  children: React.ReactNode;
  /** ARIA role forwarded to the rendered div. */
  role?: string;
  /** ARIA label forwarded to the rendered div. */
  'aria-label'?: string;
  /** ARIA labelledby forwarded to the rendered div. */
  'aria-labelledby'?: string;
  /** ARIA live region politeness. */
  'aria-live'?: 'off' | 'polite' | 'assertive';
  /** Tabindex forwarded to the rendered div. */
  tabIndex?: number;
}

const alignMap: Record<Align, string> = {
  start: "items-start",
  center: "items-center",
  end: "items-end",
  stretch: "items-stretch",
  baseline: "items-baseline",
};

const justifyMap: Record<Justify, string> = {
  start: "justify-start",
  center: "justify-center",
  end: "justify-end",
  between: "justify-between",
};

export const Stack: React.FC<StackProps> = ({
  direction = "col",
  gap = 4,
  align = "stretch",
  justify = "start",
  wrap = false,
  className,
  children,
  role,
  ...aria
}) => (
  <div
    role={role}
    aria-label={aria['aria-label']}
    aria-labelledby={aria['aria-labelledby']}
    aria-live={aria['aria-live']}
    tabIndex={aria.tabIndex}
    className={clsx(
      "flex",
      direction === "row" ? "flex-row" : "flex-col",
      `gap-${gap}`,
      alignMap[align],
      justifyMap[justify],
      wrap && "flex-wrap",
      className,
    )}
  >
    {children}
  </div>
);
