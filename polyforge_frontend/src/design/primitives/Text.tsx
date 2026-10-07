/**
 * Text — type ramp with three voices: display, body, mono.
 *
 * `display` is the italic serif (Newsreader). Used for the wordmark
 * and section headings.
 * `body` is the sans (IBM Plex Sans). Default.
 * `mono` is JetBrains Mono. Used for technical labels and values.
 *
 * `tone` is a foreground colour. `size` is a token from the type
 * scale, not a raw px value.
 */
import React from "react";
import { clsx } from "clsx";

type Voice = "display" | "body" | "mono";
type Size = "2xs" | "xs" | "sm" | "base" | "lg" | "xl" | "2xl" | "3xl";
type Tone = "fg" | "muted" | "dim" | "accent" | "success" | "warning" | "danger";

const voiceClass: Record<Voice, string> = {
  display: "font-display italic leading-tight",
  body: "font-body leading-normal",
  mono: "font-mono leading-snug tabular-nums",
};

const sizeClass: Record<Size, string> = {
  "2xs": "text-[11px]",
  xs: "text-xs",
  sm: "text-[13px]",
  base: "text-[15px]",
  lg: "text-lg",
  xl: "text-2xl",
  "2xl": "text-4xl",
  "3xl": "text-[56px]",
};

const toneClass: Record<Tone, string> = {
  fg: "text-fg",
  muted: "text-fg-muted",
  dim: "text-fg-dim",
  accent: "text-accent",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
};

export interface TextProps {
  voice?: Voice;
  size?: Size;
  tone?: Tone;
  tracking?: "tight" | "normal" | "wide" | "wider" | "widest";
  uppercase?: boolean;
  as?: keyof React.JSX.IntrinsicElements;
  className?: string;
  id?: string;
  children: React.ReactNode;
}

const trackingClass: Record<NonNullable<TextProps["tracking"]>, string> = {
  tight: "tracking-tight",
  normal: "tracking-normal",
  wide: "tracking-wide",
  wider: "tracking-wider",
  widest: "tracking-[0.2em]",
};

export const Text: React.FC<TextProps> = ({
  voice = "body",
  size = "base",
  tone = "fg",
  tracking = "normal",
  uppercase = false,
  as: As = "span",
  className,
  id,
  children,
}) => (
  <As
    id={id}
    className={clsx(
      voiceClass[voice],
      sizeClass[size],
      toneClass[tone],
      trackingClass[tracking],
      uppercase && "uppercase",
      className,
    )}
  >
    {children}
  </As>
);
