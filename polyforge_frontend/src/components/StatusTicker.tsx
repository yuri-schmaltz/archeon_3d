/**
 * StatusTicker — live feed of the most recent SSE event.
 *
 * A 28px-tall footer with a monospace, fixed-pitch ticker line.
 * Receives events from the existing ``JobEventsProvider`` (already
 * wired to ``useJobListStream``).
 *
 * When idle, shows a static "—" placeholder so the footer never
 * looks broken. When the SSE connection drops, shows a dimmer
 * "stream idle" line instead.
 */
import React, { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Text, StatusDot, type StatusKind } from "../design/primitives";
import { useJobEvents } from "../context/useJobEvents";
import type { JobEvent } from "../api/types";

function formatAge(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

const kindByStatus: Record<string, StatusKind> = {
  queued: "queued",
  processing: "live",
  running: "live",
  completed: "done",
  failed: "failed",
  cancelled: "cancelled",
};

export const StatusTicker: React.FC = () => {
  const { events, connected } = useJobEvents();
  const latest: JobEvent | null = useMemo(
    () => (events.length > 0 ? events[events.length - 1] : null),
    [events],
  );

  return (
    <footer
      className="h-7 shrink-0 min-w-0 border-t border-border bg-bg flex items-center px-4 gap-3 z-(--z-ticker)"
      role="log"
      aria-live="polite"
      aria-atomic="true"
      aria-label="Live job feed"
    >
      <Text voice="mono" size="2xs" tone="dim" tracking="widest" uppercase>
        feed
      </Text>
      <StatusDot kind={connected ? "live" : "off"} />
      <AnimatePresence mode="wait">
        {latest ? (
          <motion.div
            key={latest.uid + latest.status}
            initial={{ opacity: 0, y: 2 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -2 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
            className="flex items-center gap-3 truncate"
          >
            <Text
              voice="mono"
              size="2xs"
              tone="accent"
              tracking="wider"
              uppercase
              title={latest.uid}
            >
              {latest.uid.slice(0, 8)}
            </Text>
            <Text
              voice="mono"
              size="2xs"
              tone={kindByStatus[latest.status] === "done"
                ? "success"
                : kindByStatus[latest.status] === "failed"
                ? "danger"
                : "fg"}
              tracking="wider"
              uppercase
            >
              {latest.status}
            </Text>
            <Text voice="mono" size="2xs" tone="dim" tracking="wider">
              · {formatAge(latest.at)}
            </Text>
          </motion.div>
        ) : (
          <Text
            voice="mono"
            size="2xs"
            tone="dim"
            tracking="widest"
            uppercase
          >
            — no events yet
          </Text>
        )}
      </AnimatePresence>
      <div className="flex-1" />
      <Text voice="mono" size="2xs" tone="dim" tracking="widest" uppercase className="whitespace-nowrap shrink-0">
        {events.length} event{events.length === 1 ? "" : "s"}
      </Text>
    </footer>
  );
};
