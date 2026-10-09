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
import { useT } from "../../i18n";

export type ModeKey = "text" | "image" | "multiview" | "texture";

interface ModeChipsProps {
  value: ModeKey;
  onChange: (k: ModeKey) => void;
  /** Per-mode availability + reason, from /v1/capabilities. */
  availability?: Partial<Record<ModeKey, { available: boolean; reason: string | null }>>;
}

export const ModeChips: React.FC<ModeChipsProps> = ({ value, onChange, availability }) => {
  const t = useT();
  const MODES: { key: ModeKey; glyph: string; labelKey: string; hintKey: string }[] = [
    { key: "text", glyph: "Aa", labelKey: "create.mode.text", hintKey: "create.mode.text.hint" },
    { key: "image", glyph: "▢", labelKey: "create.mode.image", hintKey: "create.mode.image.hint" },
    { key: "multiview", glyph: "▦", labelKey: "create.mode.multiview", hintKey: "create.mode.multiview.hint" },
    { key: "texture", glyph: "◇", labelKey: "create.mode.texture", hintKey: "create.mode.texture.hint" },
  ];
  return (
    <div
      role="tablist"
      aria-label={t("create.heading")}
      className="flex min-w-0 border-b border-border overflow-x-auto"
    >
      {MODES.map((m) => {
        const active = m.key === value;
        const cap = availability?.[m.key];
        const unavailable = cap?.available === false;
        const reason = cap?.reason ?? null;
        const label = t(m.labelKey);
        const hint = t(m.hintKey);
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
                ? `${hint} — ${t("mode.unavailable", { reason })}`
                : hint
            }
            aria-label={
              unavailable
                ? t("mode.ariaUnavailable", { label, reason: reason ?? t("mode.unknownReason") })
                : label
            }
            data-unavailable={unavailable || undefined}
            className={clsx(
              "group relative shrink-0 px-4 h-11 flex items-center gap-2",
              "font-mono text-xs uppercase tracking-wider",
              "border-b-2 -mb-px transition-colors duration-[120ms] " +
                "ease-[cubic-bezier(0.16,1,0.3,1)]",
              "focus:outline-none focus-visible:text-fg focus-visible:ring-1 focus-visible:ring-accent",
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
            <span>{label}</span>
            {unavailable && (
              <span
                aria-hidden="true"
                data-testid="mode-unavailable-indicator"
                className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-400/80"
                title={reason ?? t("mode.unknownReason")}
              />
            )}
          </button>
        );
      })}
    </div>
  );
};
