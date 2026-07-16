import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '../../utils/cn';
import { Spinner } from './Spinner';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: ReactNode;
  iconRight?: ReactNode;
  fullWidth?: boolean;
}

const variantClasses = {
  primary: 'bg-primary text-white hover:bg-primary-dark focus-visible:ring-primary/30',
  secondary: 'bg-gray-100 text-gray-700 hover:bg-gray-200 focus-visible:ring-gray-300',
  outline: 'border border-gray-300 bg-transparent text-gray-700 hover:bg-gray-50 focus-visible:ring-gray-300',
  ghost: 'bg-transparent text-gray-600 hover:bg-gray-100 focus-visible:ring-gray-200',
  danger: 'bg-danger text-white hover:bg-danger/90 focus-visible:ring-danger/30',
};

const sizeClasses = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-5 py-2.5 text-sm',
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  iconRight,
  fullWidth = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2',
        'disabled:opacity-60 disabled:cursor-not-allowed',
        variantClasses[variant],
        sizeClasses[size],
        fullWidth && 'w-full',
        className
      )}
      {...props}
    >
      {loading ? (
        <Spinner size="sm" />
      ) : (
        icon && <span className="shrink-0">{icon}</span>
      )}
      {children}
      {!loading && iconRight && <span className="shrink-0">{iconRight}</span>}
    </button>
  );
}
