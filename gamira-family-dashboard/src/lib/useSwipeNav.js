import { useRef } from 'react';

const SWIPE_DISTANCE = 60; // px a horizontal drag must cover to count
const SWIPE_SLOP = 40; // px of vertical drift allowed before it reads as a scroll

/**
 * Horizontal swipe handler for the member carousels.
 *
 * Returns props to spread onto the swipeable container. `onSwipe` is called
 * with -1 for a left swipe (next member) and 1 for a right swipe (previous).
 * Pointer events cover touch, pen and mouse in one path.
 */
export function useSwipeNav(onSwipe) {
  const start = useRef(null);

  const begin = (x, y) => {
    start.current = { x, y };
  };

  const end = (x, y) => {
    const from = start.current;
    start.current = null;
    if (!from || typeof onSwipe !== 'function') return;
    const dx = x - from.x;
    const dy = y - from.y;
    if (Math.abs(dx) < SWIPE_DISTANCE) return;
    if (Math.abs(dy) > SWIPE_SLOP) return; // vertical scroll, not a swipe
    onSwipe(dx < 0 ? -1 : 1);
  };

  return {
    onTouchStart: (e) => {
      const t = e.touches[0];
      if (t) begin(t.clientX, t.clientY);
    },
    onTouchEnd: (e) => {
      const t = e.changedTouches[0];
      if (t) end(t.clientX, t.clientY);
    },
    onPointerDown: (e) => {
      if (e.pointerType === 'touch') return; // handled by the touch events above
      begin(e.clientX, e.clientY);
    },
    onPointerUp: (e) => {
      if (e.pointerType === 'touch') return;
      end(e.clientX, e.clientY);
    },
    onPointerCancel: () => {
      start.current = null;
    },
  };
}

export default useSwipeNav;
