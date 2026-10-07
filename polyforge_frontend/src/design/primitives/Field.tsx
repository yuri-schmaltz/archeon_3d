/**
 * Field — labelled input with optional hint.
 *
 * The label is a small uppercase-eyebrow in the technical voice.
 * The input is a flat rectangle with a hairline border, a
 * transparent background, and an amber focus ring.
 *
 * For file inputs use ``FieldFile``. For selects, ``FieldSelect``.
 */
import React from "react";
import { clsx } from "clsx";
import { Text } from "./Text";

const inputClass = clsx(
  "block w-full bg-transparent text-fg",
  "border-0 border-b border-border-strong",
  "h-9 px-1 text-sm font-mono tabular-nums",
  "placeholder:text-fg-dim",
  "focus:outline-none focus:border-accent",
  "transition-colors duration-[120ms] ease-[cubic-bezier(0.16,1,0.3,1)]",
  "disabled:text-fg-dim disabled:cursor-not-allowed",
);

export interface FieldProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> {
  label: string;
  hint?: string;
}

export const Field: React.FC<FieldProps> = ({
  label,
  hint,
  className,
  ...rest
}) => (
  <label className="block">
    <Text
      as="span"
      voice="mono"
      size="2xs"
      tone="muted"
      tracking="widest"
      uppercase
    >
      {label}
    </Text>
    <input className={clsx(inputClass, "mt-1", className)} {...rest} />
    {hint && (
      <Text
        as="span"
        voice="mono"
        size="2xs"
        tone="dim"
        className="block mt-1"
      >
        {hint}
      </Text>
    )}
  </label>
);

export interface FieldTextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hint?: string;
}

export const FieldTextarea: React.FC<FieldTextareaProps> = ({
  label,
  hint,
  className,
  ...rest
}) => (
  <label className="block">
    <Text
      as="span"
      voice="mono"
      size="2xs"
      tone="muted"
      tracking="widest"
      uppercase
    >
      {label}
    </Text>
    <textarea
      className={clsx(
        inputClass,
        "h-auto py-2 resize-y font-body",
        className,
      )}
      {...rest}
    />
    {hint && (
      <Text
        as="span"
        voice="mono"
        size="2xs"
        tone="dim"
        className="block mt-1"
      >
        {hint}
      </Text>
    )}
  </label>
);

export interface FieldFileProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: string;
  hint?: string;
  filename?: string | null;
}

export const FieldFile: React.FC<FieldFileProps> = ({
  label,
  hint,
  filename,
  ...rest
}) => (
  <label className="block">
    <Text
      as="span"
      voice="mono"
      size="2xs"
      tone="muted"
      tracking="widest"
      uppercase
    >
      {label}
    </Text>
    <div className="mt-1 flex items-center gap-3 border-b border-border-strong h-9">
      <span
        className={clsx(
          "inline-flex h-7 items-center rounded-sm px-3",
          "bg-surface-2 text-fg-muted",
          "font-mono text-[11px] uppercase tracking-wider",
          "cursor-pointer hover:bg-surface-3 hover:text-fg",
          "transition-colors duration-[120ms]",
        )}
      >
        Choose file
      </span>
      <Text
        as="span"
        voice="mono"
        size="2xs"
        tone="dim"
        className="truncate"
      >
        {filename ?? "No file selected"}
      </Text>
      <input
        key={filename ?? "empty"}
        type="file"
        className="sr-only"
        {...rest}
      />
    </div>
    {hint && (
      <Text
        as="span"
        voice="mono"
        size="2xs"
        tone="dim"
        className="block mt-1"
      >
        {hint}
      </Text>
    )}
  </label>
);
