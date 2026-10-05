/**
 * ModeChips — tabs-with-underline for the four generation modes.
 *
 * Not pills. Not buttons. A row of monospace, uppercase labels with
 * an amber underline on the active one. The glyphs on the left
 * (``Aa``, ``▢``, ``▦``, ``◇``) communicate the mode at a glance.
 *
 * Modes are always selectable. When the backend reports a mode as
 * ``unavailable`` (e.g. the inference model isn't loaded yet) we
 * show a small ``●`` dot next to the label and a tooltip with the
 * reason, but the user can still pick the mode and configure the
 * form. The actual job submission will surface the real error from
 * the server with a clear message; pre-blocking the UI is a worse
 * experience (the user has to wait for the model to load before
 * they can start typing their prompt).
 */
import React from "react";
import { clsx } from "clsx";

export type ModeKey = "text" | "image" | "multiview" | "texture";

const MODES: { key: ModeKey; glyph: string; label: string; hint: string }[] = [
  { key: "text", glyph: "Aa", label: "Text", hint: "Prompt → mesh" },
  { key: "image", glyph: "▢", label: "Image", hint: "Single view → mesh" },
  { key: "multiview", glyph: "▦", label: "4 Views", hint: "Multi-view → mesh" },
  { key: "texture", glyph: "◇", label: "Re-texture", hint: "Mesh + reference" },
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
      const unavailable = cap?.available === false;
      const reason = cap?.reason ?? null;
      return (
        <button
          type="button"
          key={m.key}
          role="tab"
          aria-selected={active}
          id={`mode-tab-${m.key}`}
          aria-controls={`mode-panel-${m.key}`}
          tabIndex={active ? 0 : -1}
          onKeyDown={(event) => {
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
          onClick={() => onChange(m.key)}
          title={
            unavailable && reason
              ? `${m.hint} — backend reports unavailable: ${reason}. You can still configure; the server will return a clear error on submit.`
              : m.hint
          }
          aria-label={
            unavailable
              ? `${m.label} mode (backend reports unavailable: ${reason ?? "model not loaded"})`
              : m.label
          }
          data-unavailable={unavailable || undefined}
          className={clsx(
            "group relative shrink-0 px-4 h-11 flex items-center gap-2",
            "font-mono text-xs uppercase tracking-wider",
            "border-b-2 -mb-px transition-colors duration-[120ms] " +
              "ease-[cubic-bezier(0.16,1,0.3,1)]",
            "focus:outline-none focus-visible:text-fg",
            "cursor-pointer",
            active
              ? "border-accent text-fg"
              : "border-transparent text-fg-muted hover:text-fg",
          )}
        >
          <span
            aria-hidden="true"
            className={clsx(
              "text-sm leading-none",
              active ? "text-accent" : "opacity-70",
            )}
          >
            {m.glyph}
          </span>
          <span>{m.label}</span>
          {unavailable && (
            <span
              aria-hidden="true"
              data-testid="mode-unavailable-indicator"
              className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-400/80"
              title={reason ?? "Model not loaded"}
            />
          )}
        </button>
      );
    })}
  </div>
);