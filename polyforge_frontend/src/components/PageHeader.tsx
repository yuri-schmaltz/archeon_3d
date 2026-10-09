/**
 * PageHeader — the wordmark zone.
 *
 * The "PolyForge" wordmark uses the serif display face in italic for "Poly"
 * + mono uppercase for "FORGE" in the surgical amber accent.
 * No gradient. No glow. Just typography doing the work.
 *
 * On the right: a small mono cluster with the version + a live
 * status dot indicating SSE connection state.
 */
import React from "react";
import { Text, Divider, StatusDot } from "../design/primitives";
import { useJobEvents } from "../context/useJobEvents";
import { useT } from "../i18n";

export const PageHeader: React.FC = () => {
  const { connected, isFallback } = useJobEvents();
  const t = useT();
  // The wordmark "Poly" + "Forge" stays in Latin script by design (it's
  // the brand); the localised status label handles the rest.
  const statusText = connected
    ? t("header.live")
    : isFallback
      ? t("header.refreshing")
      : t("header.connecting");
  return (
    <header
      className="h-14 shrink-0 border-b border-border bg-bg/80 backdrop-blur-sm flex items-center px-5 sm:px-6 gap-3 z-(--z-header)"
      aria-label={t("app.title")}
    >
      <div className="flex items-baseline gap-3">
        <Text voice="display" size="xl" tracking="tight" aria-hidden="true">
          Poly
        </Text>
        <Text
          voice="mono"
          size="xl"
          tone="accent"
          tracking="wider"
          uppercase
          aria-hidden="true"
        >
          Forge
        </Text>
      </div>
      <div className="hidden md:flex ml-8 items-center gap-2">
        <Text
          voice="mono"
          size="2xs"
          tone="dim"
          className="hidden sm:block"
          tracking="widest"
          uppercase
        >
          {t("app.tagline")}
        </Text>
      </div>
      <div className="flex-1" />
      <div
        className="flex items-center gap-2 shrink-0"
        role="status"
        aria-live="polite"
      >
        <StatusDot kind={connected ? "live" : "off"} />
        <Text
          voice="mono"
          size="2xs"
          tone="muted"
          tracking="widest"
          uppercase
        >
          {statusText}
        </Text>
        <Divider className="hidden sm:block !w-px !h-4 !bg-border-strong" />
        <Text
          voice="mono"
          size="2xs"
          tone="dim"
          className="hidden sm:block"
          tracking="widest"
          uppercase
        >
          {t("header.studio")}
        </Text>
      </div>
    </header>
  );
};
