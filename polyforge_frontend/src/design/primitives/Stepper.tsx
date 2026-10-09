/**
 * Stepper — multi-step progress indicator.
 *
 * Visualises a wizard-style flow (Mode → Input → Review → Submit)
 * with mono-eyebrow labels, hairline connectors, and an amber
 * indicator on the active step. Built to match the
 * "Laboratory Instrument" aesthetic: small, technical, and
 * never decorative.
 *
 * The component is **controlled**: the parent owns the
 * ``current`` index and decides what happens on navigation. The
 * component itself does not change the index — it only exposes
 * the navigation buttons. That keeps the wizard state where it
 * belongs (in the form) and lets the parent short-circuit
 * navigation (e.g. disable "Next" until a required field is
 * filled in).
 *
 * Use cases:
 *   - The Create form (3 steps: mode → input → review).
 *   - Future wizards (model download, settings migration, etc.).
 */
import React from "react";
import { clsx } from "clsx";
import { Text, Button, Stack, type StatusKind } from ".";
import { useT } from "../../i18n";
import { StatusDot } from "./StatusDot";

export interface StepperStep {
  /** Unique identifier; the parent owns the wizard state. */
  id: string;
  /** Short mono-eyebrow label rendered above the title. */
  eyebrow: string;
  /** Display title (italic serif). */
  title: string;
  /** Optional hint shown beneath the title. */
  hint?: string;
}

export interface StepperProps {
  steps: StepperStep[];
  /** Zero-based index of the current step. */
  current: number;
  /**
   * Called when the user asks to advance. Return ``false`` to
   * block the transition (e.g. a validation error). Return
   * ``true`` (or ``void``) to allow it.
   */
  onNext?: () => boolean | void;
  /**
   * Called when the user asks to go back. The wizard is always
   * allowed to go back — this callback is for analytics or
   * side-effects, not gating.
   */
  onBack?: () => void;
  /** Label of the "next" button. Defaults to a localised "Next". */
  nextLabel?: string;
  /** Label of the "back" button. Defaults to a localised "Back". */
  backLabel?: string;
  /** Label of the "submit" button shown on the last step. */
  submitLabel?: string;
  /** Submit handler fired on the last step when "Submit" is clicked. */
  onSubmit?: () => void;
  /** Disable the "next" button (e.g. when the form is invalid). */
  nextDisabled?: boolean;
  /** Show a busy spinner on the submit button. */
  submitting?: boolean;
  /** Hide the navigation bar entirely (rendering only the indicator). */
  hideNav?: boolean;
  /** The content of the current step. */
  children: React.ReactNode;
  /** Optional content rendered below the step body, above the nav. */
  footer?: React.ReactNode;
  className?: string;
}

function statusFor(current: number, index: number): StatusKind {
  if (index < current) return "done";
  if (index === current) return "live";
  return "queued";
}

export const Stepper: React.FC<StepperProps> = ({
  steps,
  current,
  onNext,
  onBack,
  nextLabel,
  backLabel,
  submitLabel,
  onSubmit,
  nextDisabled = false,
  submitting = false,
  hideNav = false,
  children,
  footer,
  className,
}) => {
  const t = useT();
  const step = steps[current];
  const isLast = current === steps.length - 1;
  const isFirst = current === 0;

  const handleNext = () => {
    if (!onNext) return;
    if (onNext() === false) return;
  };

  const handleSubmit = () => {
    onSubmit?.();
  };

  return (
    <section
      aria-label="Wizard"
      className={clsx("space-y-6", className)}
    >
      {/* Indicator: numbered dots + hairline connectors. */}
      <ol
        className="grid gap-3"
        style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}
        aria-label="Progress"
      >
        {steps.map((s, i) => {
          const kind = statusFor(current, i);
          const isActive = i === current;
          return (
            <li
              key={s.id}
              aria-current={isActive ? "step" : undefined}
              className="flex flex-col gap-1.5 min-w-0"
            >
              <div className="flex items-center gap-2">
                <StatusDot kind={kind} size={8} />
                <Text
                  voice="mono"
                  size="2xs"
                  tone={isActive ? "accent" : "muted"}
                  tracking="widest"
                  uppercase
                >
                  {t("stepper.step", { index: i + 1, total: steps.length })}
                </Text>
              </div>
              <Text
                voice="display"
                size="base"
                tone={isActive ? "fg" : "muted"}
                className="truncate"
              >
                {s.title}
              </Text>
              {s.hint && (
                <Text
                  voice="body"
                  size="xs"
                  tone="dim"
                  className="truncate leading-snug"
                >
                  {s.hint}
                </Text>
              )}
              {s.eyebrow && (
                <Text
                  voice="mono"
                  size="2xs"
                  tone="dim"
                  tracking="wider"
                  uppercase
                >
                  {s.eyebrow}
                </Text>
              )}
              {/* Hairline connector to the next step. */}
              {i < steps.length - 1 && (
                <div
                  aria-hidden="true"
                  className={clsx(
                    "h-px mt-1",
                    i < current ? "bg-accent" : "bg-border",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>

      {/* Step body. */}
      <div
        key={step.id}
        role="region"
        aria-live="polite"
        aria-label={step.title}
        className="space-y-4"
      >
        {children}
      </div>

      {footer}

      {/* Navigation. */}
      {!hideNav && (
        <Stack
          direction="row"
          gap={3}
          justify="between"
          className="pt-4 border-t border-border"
        >
          <Button
            type="button"
            variant="ghost"
            size="md"
            onClick={onBack}
            disabled={isFirst}
            aria-label={backLabel ?? t("common.back")}
          >
            ← {backLabel ?? t("common.back")}
          </Button>
          {isLast ? (
            <Button
              type="button"
              variant="primary"
              size="md"
              onClick={handleSubmit}
              disabled={submitting || nextDisabled}
            >
              {submitLabel ?? t("stepper.submit")}
            </Button>
          ) : (
            <Button
              type="button"
              variant="primary"
              size="md"
              onClick={handleNext}
              disabled={nextDisabled}
              aria-label={nextLabel ?? t("common.next")}
            >
              {nextLabel ?? t("common.next")} →
            </Button>
          )}
        </Stack>
      )}
    </section>
  );
};
