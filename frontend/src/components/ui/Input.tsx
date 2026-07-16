import type { InputHTMLAttributes, ReactNode } from 'react';
import { cn } from '../../utils/cn';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

export function Input({
  label,
  error,
  hint,
  leftIcon,
  rightIcon,
  className,
  id,
  ...props
}: InputProps) {
  const inputId = id ?? (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={inputId} className="block text-sm font-medium text-gray-700 mb-1">
          {label}
        </label>
      )}
      <div className="relative">
        {leftIcon && (
          <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none text-gray-400">
            {leftIcon}
          </div>
        )}
        <input
          id={inputId}
          className={cn(
            'w-full rounded-lg border bg-gray-50 text-gray-900 text-sm py-2',
            'placeholder:text-gray-400 transition-colors',
            'focus:outline-none focus:ring-2 focus:border-primary focus:ring-primary/20',
            leftIcon ? 'pl-10' : 'pl-3',
            rightIcon ? 'pr-10' : 'pr-3',
            error
              ? 'border-danger focus:border-danger focus:ring-danger/20'
              : 'border-gray-200',
            className
          )}
          {...props}
        />
        {rightIcon && (
          <div className="absolute inset-y-0 right-3 flex items-center text-gray-400">
            {rightIcon}
          </div>
        )}
      </div>
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      {!error && hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}
