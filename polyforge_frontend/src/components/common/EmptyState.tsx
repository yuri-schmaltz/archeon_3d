/**
 * EmptyState — zero-state card for lists and pages.
 *
 * Aligns with the "Laboratory Instrument" theme: monochrome wireframe
 * glyph, mono-eyebrow label, display title, body hint, optional CTA.
 *
 * Use for: empty library, empty search results, no models loaded,
 * no capabilities available. Keeps the language of the product
 * consistent across pages.
 */
import React from 'react';
import { Stack, Text, Button } from '../../design/primitives';
import { clsx } from 'clsx';

export interface EmptyStateProps {
  /** Optional mono-eyebrow label (e.g. "library"). */
  eyebrow?: string;
  /** Display title (e.g. "Nenhum trabalho ainda"). */
  title: string;
  /** Supporting copy. */
  body?: string;
  /** Primary CTA label. */
  ctaLabel?: string;
  /** Primary CTA action. */
  onCta?: () => void;
  /** Optional illustration variant. */
  illustration?: 'mesh' | 'search' | 'queue';
  className?: string;
}

const Illustrations: Record<NonNullable<EmptyStateProps['illustration']>, React.FC> = {
  mesh: () => (
    <svg
      aria-hidden="true"
      viewBox="0 0 80 80"
      width="64"
      height="64"
      className="text-fg-dim"
    >
      {/* Wireframe mesh: cube with diagonal mesh lines. */}
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      >
        <polygon points="40,8 72,24 72,56 40,72 8,56 8,24" />
        <line x1="40" y1="8" x2="40" y2="40" />
        <line x1="8" y1="24" x2="40" y2="40" />
        <line x1="72" y1="24" x2="40" y2="40" />
        <line x1="40" y1="40" x2="40" y2="72" />
        <line x1="40" y1="40" x2="8" y2="56" />
        <line x1="40" y1="40" x2="72" y2="56" />
      </g>
    </svg>
  ),
  search: () => (
    <svg
      aria-hidden="true"
      viewBox="0 0 80 80"
      width="64"
      height="64"
      className="text-fg-dim"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      >
        <circle cx="34" cy="34" r="20" />
        <line x1="49" y1="49" x2="68" y2="68" />
        <line x1="26" y1="34" x2="42" y2="34" />
      </g>
    </svg>
  ),
  queue: () => (
    <svg
      aria-hidden="true"
      viewBox="0 0 80 80"
      width="64"
      height="64"
      className="text-fg-dim"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      >
        <rect x="14" y="14" width="52" height="52" />
        <line x1="14" y1="28" x2="66" y2="28" />
        <line x1="14" y1="44" x2="66" y2="44" />
        <line x1="14" y1="60" x2="66" y2="60" />
        <circle cx="20" cy="21" r="1.5" fill="currentColor" />
        <circle cx="20" cy="37" r="1.5" fill="currentColor" />
        <circle cx="20" cy="53" r="1.5" fill="currentColor" />
      </g>
    </svg>
  ),
};

export const EmptyState: React.FC<EmptyStateProps> = ({
  eyebrow,
  title,
  body,
  ctaLabel,
  onCta,
  illustration = 'mesh',
  className,
}) => {
  const Illustration = Illustrations[illustration];
  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center text-center gap-4 py-14 px-6',
        'border border-dashed border-border rounded-md',
        className,
      )}
    >
      <Illustration />
      <Stack gap={2} className="max-w-md">
        {eyebrow && (
          <Text
            voice="mono"
            size="2xs"
            tone="muted"
            tracking="widest"
            uppercase
          >
            {eyebrow}
          </Text>
        )}
        <Text as="h3" voice="display" size="xl" tracking="tight">
          {title}
        </Text>
        {body && (
          <Text voice="body" size="sm" tone="muted" className="leading-snug">
            {body}
          </Text>
        )}
      </Stack>
      {ctaLabel && onCta && (
        <Button onClick={onCta} variant="primary" size="md">
          {ctaLabel}
        </Button>
      )}
    </div>
  );
};
