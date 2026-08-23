import { describe, expect, it } from "vitest";

import { formatReaction, reactionTone } from "./format";
import { calculateAverageReaction } from "./reactions";

describe("calculateAverageReaction", () => {
  it("averages all six values", () => {
    expect(calculateAverageReaction([1, 2, 3, 4, 5, 6])).toBe(3.5);
  });

  it("averages exactly three available values", () => {
    expect(calculateAverageReaction([3, null, 6, null, 0, null])).toBe(3);
  });

  it("returns null below three available values", () => {
    expect(calculateAverageReaction([2, null, null, -2, null, null])).toBeNull();
  });

  it("counts zero as an available value", () => {
    expect(calculateAverageReaction([0, 0, 3, null, null, null])).toBe(1);
  });

  it("preserves positive and negative reactions", () => {
    expect(calculateAverageReaction([6, -3, -3, null, null, null])).toBe(0);
    expect(reactionTone(1)).toBe("text-emerald-300");
    expect(reactionTone(-1)).toBe("text-rose-300");
  });

  it("formats percentage units without multiplying by 100", () => {
    expect(formatReaction(2.41)).toBe("+2.41%");
    expect(formatReaction(-1.18)).toBe("-1.18%");
    expect(formatReaction(0)).toBe("0.00%");
  });
});
