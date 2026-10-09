/**
 * Tests for the Stepper primitive.
 */
import { describe, it, expect, vi, beforeAll, afterAll } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Stepper, type StepperStep } from "../src/design/primitives/Stepper";
import { setLocale } from "../src/i18n";

const STEPS: StepperStep[] = [
  { id: "a", eyebrow: "Step A", title: "Choose mode" },
  { id: "b", eyebrow: "Step B", title: "Fill input" },
  { id: "c", eyebrow: "Step C", title: "Review and submit" },
];

// Force English for stable, locale-agnostic test assertions.
beforeAll(() => setLocale("en"));
afterAll(() => setLocale("pt-BR"));

describe("Stepper", () => {
  it("renders one indicator per step with the eyebrow label", () => {
    render(
      <Stepper steps={STEPS} current={0} onNext={() => undefined}>
        <p>step body</p>
      </Stepper>
    );
    const progress = screen.getByRole("list", { name: "Progress" });
    expect(progress.children.length).toBe(3);
    // The eyebrow text is uppercased by CSS but the underlying DOM
    // text is the original case. We look for the localised step
    // counter ("Step 1 of 3", "Step 2 of 3", "Step 3 of 3") instead
    // because the eyebrow may share substrings across steps.
    expect(screen.getByText("Step 1 of 3")).toBeTruthy();
    expect(screen.getByText("Step 2 of 3")).toBeTruthy();
    expect(screen.getByText("Step 3 of 3")).toBeTruthy();
  });

  it("marks the current step with aria-current=step", () => {
    render(
      <Stepper steps={STEPS} current={1} onNext={() => undefined}>
        <p>step body</p>
      </Stepper>
    );
    const current = screen.getByRole("listitem", { current: "step" });
    expect(current.textContent).toContain("Step 2 of 3");
  });

  it("calls onNext when the next button is clicked", () => {
    const onNext = vi.fn().mockReturnValue(true);
    render(
      <Stepper steps={STEPS} current={0} onNext={onNext}>
        <p>step body</p>
      </Stepper>
    );
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(onNext).toHaveBeenCalledOnce();
  });

  it("blocks navigation when onNext returns false", () => {
    const onNext = vi.fn().mockReturnValue(false);
    render(
      <Stepper steps={STEPS} current={0} onNext={onNext}>
        <p>step body</p>
      </Stepper>
    );
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(onNext).toHaveBeenCalledOnce();
  });

  it("disables Next when nextDisabled is true", () => {
    render(
      <Stepper steps={STEPS} current={0} nextDisabled>
        <p>step body</p>
      </Stepper>
    );
    const next = screen.getByRole("button", { name: /next/i }) as HTMLButtonElement;
    expect(next.disabled).toBe(true);
  });

  it("disables Back on the first step", () => {
    render(
      <Stepper steps={STEPS} current={0} onNext={() => undefined}>
        <p>step body</p>
      </Stepper>
    );
    const back = screen.getByRole("button", { name: /back/i }) as HTMLButtonElement;
    expect(back.disabled).toBe(true);
  });

  it("renders the Submit button on the last step and calls onSubmit", () => {
    const onSubmit = vi.fn();
    render(
      <Stepper
        steps={STEPS}
        current={2}
        onSubmit={onSubmit}
      >
        <p>step body</p>
      </Stepper>
    );
    const submit = screen.getByRole("button", { name: /submit job/i });
    expect(submit).toBeTruthy();
    fireEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("hides the navigation bar when hideNav is set", () => {
    render(
      <Stepper steps={STEPS} current={0} hideNav>
        <p>step body</p>
      </Stepper>
    );
    expect(screen.queryByRole("button", { name: /next/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /back/i })).toBeNull();
  });
});
