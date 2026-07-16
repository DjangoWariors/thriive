import type { SelectHTMLAttributes } from 'react';
import { cn } from '../../utils/cn';

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  options: SelectOption[];
  placeholder?: string;
}

export function Select({ label, error, options, placeholder, className, id, ...props }: SelectProps) {
  const selectId = id ?? (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={selectId} className="block text-sm font-medium text-gray-700 mb-1">
          {label}
        </label>
      )}
      <select
        id={selectId}
        className={cn(
          'w-full rounded-lg border bg-gray-50 text-gray-900 text-sm px-3 py-2',
          'transition-colors cursor-pointer',
          'focus:outline-none focus:ring-2 focus:border-primary focus:ring-primary/20',
          error
            ? 'border-danger focus:border-danger focus:ring-danger/20'
            : 'border-gray-200',
          className
        )}
        {...props}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}
