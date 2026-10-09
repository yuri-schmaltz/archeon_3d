/**
 * CapabilityStrip — compact readout of server capabilities + active mode.
 *
 * Renders next to the create-form heading so the user always sees:
 *   - backend status (live / offline / auth-locked / loading)
 *   - the active mode
 *   - which model is loaded (when available)
 *   - whether texture generation is enabled
 *
 * Aligns with the "Laboratory Instrument" aesthetic: mono labels,
 * tabular numbers, hairline borders, single accent dot.
 */
import React from 'react';
import { useCapabilities } from '../../api/capabilities';
import { useSystemMetrics } from '../../hooks/useSystemMetrics';
import { Text, StatusDot, type StatusKind } from '../../design/primitives';
import { useT } from '../../i18n';
import { clsx } from 'clsx';

type Status = 'online' | 'offline' | 'loading' | 'error';

function pickStatus(
  capsLoading: boolean,
  capsError: string | null,
  metricsError: string | null,
): Status {
  if (capsError) return 'error';
  if (metricsError) return 'offline';
  if (capsLoading) return 'loading';
  return 'online';
}

function statusKind(status: Status): StatusKind {
  switch (status) {
    case 'online':
      return 'live';
    case 'loading':
      return 'queued';
    case 'offline':
      return 'failed';
    case 'error':
      return 'failed';
  }
}

export interface CapabilityStripProps {
  /** Active mode (e.g. "text", "image", "multiview", "texture"). */
  mode?: string;
  /** When true, render a tighter layout suitable for embedding under a heading. */
  dense?: boolean;
  className?: string;
}

export const CapabilityStrip: React.FC<CapabilityStripProps> = ({
  mode,
  dense = false,
  className,
}) => {
  const t = useT();
  const { capabilities, loading, error } = useCapabilities();
  const metrics = useSystemMetrics();

  const status = pickStatus(loading, error, metrics.error);
  const kind = statusKind(status);

  // Pick a model name from capabilities.models (if any loaded).
  const modelName = Object.values(capabilities.models).find((m) => m.loaded)?.id;

  // Pick queue depth (0 when unknown / disabled).
  const queueDepth = capabilities.limits.queue_depth;

  const labelClass = clsx(
    'font-mono uppercase tracking-widest text-fg-dim',
    dense ? 'text-[10px]' : 'text-2xs',
  );
  const valueClass = clsx(
    'font-mono tabular-nums text-fg',
    dense ? 'text-xs' : 'text-sm',
  );

  const statusLabel =
    status === 'online'
      ? t('strip.status.ready')
      : status === 'loading'
        ? t('strip.status.loading')
        : status === 'offline'
          ? t('strip.status.offline')
          : t('strip.status.error');

  return (
    <div
      aria-live="polite"
      className={clsx(
        'flex flex-wrap items-center gap-x-5 gap-y-2',
        'border border-border rounded-md',
        'bg-surface-1/40 px-4 py-3',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <StatusDot kind={kind} size={6} />
        <span className={labelClass}>{statusLabel}</span>
      </div>

      {mode && (
        <div className="flex items-baseline gap-2">
          <span className={labelClass}>{t('strip.field.mode')}</span>
          <span className={valueClass}>{mode}</span>
        </div>
      )}

      {modelName && (
        <div className="flex items-baseline gap-2">
          <span className={labelClass}>{t('strip.field.model')}</span>
          <span className={valueClass}>{modelName}</span>
        </div>
      )}

      <div className="flex items-baseline gap-2">
        <span className={labelClass}>{t('strip.field.queue')}</span>
        <span className={valueClass}>
          {queueDepth >= 1024 ? '∞' : queueDepth}
        </span>
      </div>

      {capabilities.modes.texture && (
        <div className="flex items-baseline gap-2">
          <span className={labelClass}>{t('strip.field.texture')}</span>
          <span className={valueClass}>
            {capabilities.modes.texture.available ? 'on' : 'off'}
          </span>
        </div>
      )}

      {metrics.metrics && metrics.metrics.gpu_percent !== null && metrics.metrics.gpu_percent !== undefined && (
        <div className="flex items-baseline gap-2">
          <span className={labelClass}>{t('strip.field.gpu')}</span>
          <span className={valueClass}>
            {metrics.metrics.gpu_percent.toFixed(0)}%
          </span>
        </div>
      )}

      <span className="sr-only">
        {t('auth.alert.connecting')} {status}.
      </span>
    </div>
  );
};

/**
 * Lightweight text-only line version of the strip for tight headers.
 * Used in mobile or wherever the full strip would be too wide.
 */
export const CapabilityStripInline: React.FC<{ mode?: string }> = ({ mode }) => {
  const t = useT();
  const { loading, error } = useCapabilities();
  const metrics = useSystemMetrics();
  const status = pickStatus(loading, error, metrics.error);
  const statusLabel =
    status === 'online'
      ? t('strip.status.ready')
      : status === 'loading'
        ? t('strip.status.loading')
        : status === 'offline'
          ? t('strip.status.offline')
          : t('strip.status.error');
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs">
      <span className="flex items-center gap-1.5 font-mono uppercase tracking-widest text-fg-dim">
        <StatusDot kind={statusKind(status)} size={5} />
        {statusLabel}
      </span>
      {mode && (
        <span className="font-mono text-fg-muted">
          <span className="text-fg-dim">{t('strip.field.mode')} </span>
          {mode}
        </span>
      )}
      {metrics.metrics?.gpu_percent !== null && metrics.metrics?.gpu_percent !== undefined && (
        <Text voice="mono" size="2xs" tone="dim" tracking="wider">
          {t('strip.field.gpu')} {metrics.metrics.gpu_percent.toFixed(0)}%
        </Text>
      )}
    </div>
  );
};
