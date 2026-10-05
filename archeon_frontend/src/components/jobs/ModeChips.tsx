/**
 * ModeChips — tabs-with-underline for the four generation modes.
 *
 * Not pills. Not buttons. A row of monospace, uppercase labels with
 * an amber underline on the active one. The glyphs on the left
 * (``Aa``, ``◐``, ``⊞``, ``◈``) communicate the mode at a glance.
 */
import React from "react";
import { clsx } from "clsx";

export type ModeKey = "text" | "image" | "multiview" | "texture";

const MODES: { key: ModeKey; glyph: string; label: string; hint: string }[] = [
  { key: "text", glyph: "Aa", label: "Text", hint: "Prompt → mesh" },
  { key: "image", glyph: "◐", label: "Image", hint: "Single view → mesh" },
  { key: "multiview", glyph: "⊞", label: "4 Views", hint: "Multi-view → mesh" },
  { key: "texture", glyph: "◈", label: "Re-texture", hint: "Mesh + reference" },
];

interface ModeChipsProps {
  value: ModeKey;
  onChange: (k: ModeKey) => void;
  /** Per-mode availability + reason, from /v1/capabilities. */
  availability?: Partial<Record<ModeKey, { available: boolean; reason: string | null }>>;
}

export const ModeChips: React.FC<ModeChipsProps> = ({ value, onChange, availability }) => (
  <div role="tablist" aria-label="Generation mode" className="flex min-w-0 border-b border-border overflow-x-auto">
    {MODES.map((m) => {
      const active = m.key === value;
      const cap = availability?.[m.key];
      const disabled = cap ? cap.available === false : false;
      const reason = cap?.reason;
      return (
        <button
          type="button"
          key={m.key}
          role="tab"
          aria-selected={active}
          aria-disabled={disabled || undefined}
          id={`mode-tab-${m.key}`}
          aria-controls={`mode-panel-${m.key}`}
          tabIndex={active ? 0 : -1}
          onKeyDown={(event) => {
            if (disabled) return;
            const index = MODES.findIndex((mode) => mode.key === value);
            let next = index;
            if (event.key === "ArrowRight") next = (index + 1) % MODES.length;
            else if (event.key === "ArrowLeft") next = (index + MODES.length - 1) % MODES.length;
            else if (event.key === "Home") next = 0;
            else if (event.key === "End") next = MODES.length - 1;
            else return;
            event.preventDefault();
            if (MODES[next].key === value) return;
            onChange(MODES[next].key);
            document.getElementById(`mode-tab-${MODES[next].key}`)?.focus();
          }}
          onClick={() => {
            if (disabled) return;
            onChange(m.key);
          }}
          title={disabled && reason ? `${m.hint} — unavailable: ${reason}` : m.hint}
          aria-label={
            disabled
              ? `${m.label} mode unavailable${reason ? `: ${reason}` : ""}`
              : m.label
          }
          className={clsx(
            "group relative shrink-0 px-4 h-11 flex items-center gap-2",
            "font-mono text-xs uppercase tracking-wider",
            "border-b-2 -mb-px transition-colors duration-[120ms] " +
              "ease-[cubic-bezier(0.16,1,0.3,1)]",
            "focus:outline-none focus-visible:text-fg",
            disabled
              ? "border-transparent text-fg-dim cursor-not-allowed opacity-50"
              : active
              ? "border-accent text-fg"
              : "border-transparent text-fg-muted hover:text-fg",
          )}
        >
          <span
            aria-hidden="true"
            className={clsx(
              "text-sm",
              active && !disabled ? "text-accent" : "opacity-60",
            )}
          >
            {m.glyph}
          </span>
          <span>{m.label}</span>
        </button>
      );
    })}
  </div>
);
