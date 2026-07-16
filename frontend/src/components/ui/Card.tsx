import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';

interface CardProps {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  borderColor?: 'red' | 'green' | 'amber' | 'blue' | 'purple';
  padding?: 'none' | 'sm' | 'md' | 'lg';
  children?: ReactNode;
  className?: string;
}

const borderColorClasses = {
  red: 'border-t-red-500',
  green: 'border-t-green-500',
  amber: 'border-t-amber-500',
  blue: 'border-t-blue-500',
  purple: 'border-t-purple-500',
};

const paddingClasses = {
  none: '',
  sm: 'p-4',
  md: 'p-6',
  lg: 'p-8',
};

export function Card({
  title,
  subtitle,
  actions,
  borderColor,
  padding = 'md',
  children,
  className,
}: CardProps) {
  const hasHeader = Boolean(title ?? actions);

  return (
    <div
      className={cn(
        'bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden',
        borderColor && 'border-t-4',
        borderColor && borderColorClasses[borderColor],
        className
      )}
    >
      {hasHeader && (
        <div className="flex items-start justify-between px-6 py-4 border-b border-gray-100">
          <div>
            {title && (
              <h3 className="text-base font-semibold text-gray-900">{title}</h3>
            )}
            {subtitle && (
              <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
            )}
          </div>
          {actions && (
            <div className="flex items-center gap-2 ml-4 shrink-0">{actions}</div>
          )}
        </div>
      )}
      <div className={paddingClasses[padding]}>{children}</div>
    </div>
  );
}
