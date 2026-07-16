import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';

interface BadgeProps {
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'purple';
  size?: 'sm' | 'md';
  children: ReactNode;
  className?: string;
}

const variantClasses = {
  default: 'bg-gray-100 text-gray-700',
  success: 'bg-success-100 text-success',
  warning: 'bg-warning-100 text-warning',
  danger: 'bg-danger-100 text-danger',
  info: 'bg-blue-100 text-blue-700',
  purple: 'bg-purple-100 text-purple-700',
};

const sizeClasses = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-sm',
};

export function Badge({ variant = 'default', size = 'sm', children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center font-medium rounded-full',
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
    >
      {children}
    </span>
  );
}
