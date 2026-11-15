// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { animateIssuePulse } from "./issue-pulse";

let reduced = false;
let motionChange: () => void;
let intersection: (entries: { isIntersecting: boolean }[]) => void;
let tick: FrameRequestCallback | undefined;
const requestFrame = vi.fn((callback: FrameRequestCallback) => {
  tick = callback;
  return 1;
});
const cancelFrame = vi.fn();
beforeEach(() => {
  reduced = false;
  tick = undefined;
  requestFrame.mockClear();
  cancelFrame.mockClear();
  vi.stubGlobal("requestAnimationFrame", requestFrame);
  vi.stubGlobal("cancelAnimationFrame", cancelFrame);
  vi.stubGlobal("matchMedia", () => ({
    get matches() {
      return reduced;
    },
    addEventListener: (_event: string, callback: () => void) => {
      motionChange = callback;
    },
    removeEventListener: vi.fn(),
  }));
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: typeof intersection) {
        intersection = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("expands and fades the shared ring on a 1.5 second loop and cleans up", () => {
  const paint = vi.fn();
  const stop = animateIssuePulse({ setPaintProperty: paint }, document.body);
  tick!(0);
  tick!(750);
  expect(paint).toHaveBeenCalledWith("issue-pulse", "circle-radius", 19);
  expect(paint).toHaveBeenCalledWith(
    "issue-pulse",
    "circle-stroke-opacity",
    0.375,
  );
  tick!(1500);
  expect(paint).toHaveBeenCalledWith("issue-pulse", "circle-radius", 12);
  stop();
  expect(cancelFrame).toHaveBeenCalled();
  expect(paint).toHaveBeenLastCalledWith(
    "issue-pulse",
    "circle-stroke-opacity",
    0,
  );
});
it("uses a static ring with reduced motion and responds to preference changes", () => {
  reduced = true;
  const paint = vi.fn();
  const stop = animateIssuePulse({ setPaintProperty: paint }, document.body);
  expect(requestFrame).not.toHaveBeenCalled();
  expect(paint).toHaveBeenCalledWith("issue-pulse", "circle-radius", 14);
  expect(paint).toHaveBeenLastCalledWith(
    "issue-pulse",
    "circle-stroke-opacity",
    0.6,
  );
  reduced = false;
  motionChange();
  expect(requestFrame).toHaveBeenCalledOnce();
  reduced = true;
  motionChange();
  expect(cancelFrame).toHaveBeenCalledOnce();
  stop();
});
it("suspends while offscreen or in a hidden tab, and resumes when visible", () => {
  const paint = vi.fn();
  const stop = animateIssuePulse({ setPaintProperty: paint }, document.body);
  intersection([{ isIntersecting: false }]);
  expect(cancelFrame).toHaveBeenCalledOnce();
  expect(paint).toHaveBeenLastCalledWith(
    "issue-pulse",
    "circle-stroke-opacity",
    0,
  );
  intersection([{ isIntersecting: true }]);
  expect(requestFrame).toHaveBeenCalledTimes(2);
  const visibility = vi.spyOn(document, "visibilityState", "get");
  visibility.mockReturnValue("hidden");
  document.dispatchEvent(new Event("visibilitychange"));
  expect(cancelFrame).toHaveBeenCalledTimes(2);
  visibility.mockReturnValue("visible");
  document.dispatchEvent(new Event("visibilitychange"));
  expect(requestFrame).toHaveBeenCalledTimes(3);
  stop();
});
