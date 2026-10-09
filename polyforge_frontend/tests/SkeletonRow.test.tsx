/**
 * Tests for the SkeletonRow and SkeletonCard placeholders.
 *
 * These tests avoid @testing-library/jest-dom so the suite can run
 * with the default vitest configuration. The skeleton components
 * are simple enough that we can assert on DOM structure directly.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SkeletonRow, SkeletonCard } from "../src/components/common/SkeletonRow";

describe("SkeletonRow", () => {
  it("renders the requested number of rows with a status role", () => {
    render(<SkeletonRow rows={4} label="Carregando" />);
    const status = screen.getByRole("status", { name: "Carregando" });
    expect(status).toBeTruthy();
    // 4 rows, each rendered as a div, plus the outer container.
    expect(status.children.length).toBe(4);
  });

  it("falls back to a default label when none is provided", () => {
    render(<SkeletonRow />);
    const status = screen.getByRole("status", { name: "Loading…" });
    expect(status).toBeTruthy();
  });

  it("exposes a deterministic but varied width for each row", () => {
    const { container } = render(<SkeletonRow rows={3} />);
    const widths = Array.from(
      container.querySelectorAll<HTMLElement>("[style*='width']"),
    ).map((el) => el.style.width);
    expect(widths).toHaveLength(3);
    // All widths are different — the LCG is seeded per row index.
    expect(new Set(widths).size).toBeGreaterThan(1);
  });
});

describe("SkeletonCard", () => {
  it("renders a single card with status role", () => {
    render(<SkeletonCard />);
    const status = screen.getByRole("status", { name: "Loading job" });
    expect(status).toBeTruthy();
  });
});
