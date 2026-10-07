/**
 * Divider — 1px hairline in a tokenised colour.
 *
 * Prefer this over `border-b` ad-hoc. The line is intentionally thin
 * (1px) and warm; the design language is "paper millimetrado", not
 * "rounded card with shadow".
 */
import React from "react";
import { clsx } from "clsx";

type Tone = "default" | "strong";

export const Divider: React.FC<{ tone?: Tone; className?: string }> = ({
  tone = "default",
  className,
}) => (
  <hr
    className={clsx(
      "border-0 h-px w-full",
      tone === "default" ? "bg-border" : "bg-border-strong",
      className,
    )}
  />
);
