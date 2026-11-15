interface PulseMap {
  setPaintProperty(layer: string, property: string, value: number): void;
}

export function animateIssuePulse(map: PulseMap, container: HTMLElement) {
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let visible = true;
  let frame: number | undefined;
  let start: number | undefined;
  const paint = (radius: number, opacity: number) => {
    map.setPaintProperty("issue-pulse", "circle-radius", radius);
    map.setPaintProperty("issue-pulse", "circle-stroke-opacity", opacity);
  };
  const tick = (now: number) => {
    start ??= now;
    const progress = ((now - start) % 1500) / 1500;
    paint(12 + progress * 14, (1 - progress) * 0.75);
    frame = requestAnimationFrame(tick);
  };
  const sync = () => {
    if (frame !== undefined) cancelAnimationFrame(frame);
    frame = undefined;
    start = undefined;
    if (!visible || document.visibilityState === "hidden") paint(14, 0);
    else if (motion.matches) paint(14, 0.6);
    else frame = requestAnimationFrame(tick);
  };
  const observer = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    sync();
  });
  observer.observe(container);
  document.addEventListener("visibilitychange", sync);
  motion.addEventListener("change", sync);
  sync();
  return () => {
    if (frame !== undefined) cancelAnimationFrame(frame);
    observer.disconnect();
    document.removeEventListener("visibilitychange", sync);
    motion.removeEventListener("change", sync);
    paint(14, 0);
  };
}
