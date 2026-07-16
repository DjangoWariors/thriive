import { cn } from '../../utils/cn';

interface ProgressBarProps {
  value: number;
  max?: number;
  showLabel?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

export function ProgressBar({
  value,
  max = 100,
  showLabel = false,
  size = 'md',
  className,
}: ProgressBarProps) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  const clampedPct = Math.min(pct, 100);

  const barColor =
    pct >= 100 ? 'bg-success' : pct >= 80 ? 'bg-warning' : 'bg-danger';

  const trackHeight = size === 'sm' ? 'h-1.5' : 'h-2.5';

  return (
    <div className={cn('w-full', className)}>
      {showLabel && (
        <div className="flex justify-between text-xs text-gray-600 mb-1">
          <span>{value.toLocaleString('en-IN')}</span>
          <span>{pct.toFixed(1)}%</span>
        </div>
      )}
      <div className={cn('w-full bg-gray-200 rounded-full overflow-hidden', trackHeight)}>
        <div
          className={cn('h-full rounded-full transition-all duration-300', barColor)}
          style={{ width: `${clampedPct}%` }}
        />
      </div>
    </div>
  );
}
