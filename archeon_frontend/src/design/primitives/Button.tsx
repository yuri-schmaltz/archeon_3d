/**
 * Button — three variants tuned for the "laboratory instrument" feel.
 *
 *   primary   — amber pill. Mono uppercase eyebrow label. Reserved
 *               for the single most important action on the screen
 *               (Submit Job, Confirm).
 *   secondary — outlined. Used for secondary actions.
 *   ghost     — text-only with a hover background. For tertiary
 *               actions inside a row.
 *
 * Buttons are square at the corners (2px radius) to keep the
 * technical aesthetic. Padding is generous so they read as
 * "controls" not "links".
 */
import React from "react";
import { clsx } from "clsx";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md" | "lg";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  block?: boolean;
}

const variantClass: Record<Variant, string> = {
  primary:
    "bg-accent text-stone-950 hover:bg-accent-2 " +
    "disabled:bg-surface-3 disabled:text-fg-dim disabled:cursor-not-allowed",
  secondary:
    "bg-transparent text-fg border border-border-strong " +
    "hover:bg-surface-2 hover:border-accent/50 " +
    "disabled:text-fg-dim disabled:cursor-not-allowed",
  ghost:
    "bg-transparent text-fg-muted hover:text-fg hover:bg-surface-2 " +
    "disabled:text-fg-dim disabled:cursor-not-allowed",
};

const sizeClass: Record<Size, string> = {
  sm: "h-9 max-sm:h-11 px-3 text-xs",
  md: "h-11 px-4 text-xs",
  lg: "h-11 px-6 text-sm",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { variant = "secondary", size = "md", block = false, className, children, ...rest },
    ref,
  ) => (
    <button
      type="button"
      ref={ref}
      className={clsx(
        "inline-flex items-center justify-center gap-2 " +
          "rounded-sm font-mono uppercase tracking-wider " +
          "transition-colors duration-[120ms] ease-[cubic-bezier(0.16,1,0.3,1)] " +
          "focus:outline-none focus-visible:ring-1 focus-visible:ring-accent",
        variantClass[variant],
        sizeClass[size],
        block && "w-full",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  ),
);
Button.displayName = "Button";
