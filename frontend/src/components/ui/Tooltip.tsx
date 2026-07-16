import { useCallback, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';

interface TooltipProps {
  content: string;
  side?: 'top' | 'bottom' | 'left' | 'right';
  children: ReactNode;
  className?: string;
  /** Keep the bubble on a single line. Default false — long help text wraps. */
  nowrap?: boolean;
}

interface Pos {
  x: number;
  y: number;
  transform: string;
}

// Gap between the trigger and the bubble, in px.
const GAP = 8;

function computePos(rect: DOMRect, side: TooltipProps['side']): Pos {
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  switch (side) {
    case 'bottom':
      return { x: cx, y: rect.bottom + GAP, transform: 'translate(-50%, 0)' };
    case 'left':
      return { x: rect.left - GAP, y: cy, transform: 'translate(-100%, -50%)' };
    case 'right':
      return { x: rect.right + GAP, y: cy, transform: 'translate(0, -50%)' };
    case 'top':
    default:
      return { x: cx, y: rect.top - GAP, transform: 'translate(-50%, -100%)' };
  }
}

/**
 * Hover/focus tooltip. The bubble is rendered in a portal with `position: fixed`
 * so it is never clipped by an ancestor's `overflow-hidden` (table cards, modals,
 * scroll panes) or trapped behind a stacking context.
 */
export function Tooltip({ content, side = 'top', children, className, nowrap = false }: TooltipProps) {
  const triggerRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<Pos | null>(null);

  const show = useCallback(() => {
    const el = triggerRef.current;
    if (el) setPos(computePos(el.getBoundingClientRect(), side));
  }, [side]);

  const hide = useCallback(() => setPos(null), []);

  return (
    <div
      ref={triggerRef}
      className={cn('relative inline-flex', className)}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {pos !== null &&
        createPortal(
          <div
            role="tooltip"
            style={{ position: 'fixed', top: pos.y, left: pos.x, transform: pos.transform }}
            className={cn(
              'pointer-events-none z-[9999] rounded bg-gray-900 px-2 py-1 text-xs text-white shadow-lg',
              nowrap ? 'whitespace-nowrap' : 'w-max max-w-xs whitespace-normal text-left leading-snug',
            )}
          >
            {content}
          </div>,
          document.body,
        )}
    </div>
  );
}
