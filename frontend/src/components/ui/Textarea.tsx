import type { TextareaHTMLAttributes } from 'react';
import { cn } from '../../utils/cn';

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export function Textarea({ label, error, hint, className, id, ...props }: TextareaProps) {
  const textareaId = id ?? (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={textareaId} className="block text-sm font-medium text-gray-700 mb-1">
          {label}
        </label>
      )}
      <textarea
        id={textareaId}
        className={cn(
          'w-full rounded-lg border bg-gray-50 text-gray-900 text-sm px-3 py-2',
          'placeholder:text-gray-400 transition-colors resize-y',
          'focus:outline-none focus:ring-2 focus:border-primary focus:ring-primary/20',
          error
            ? 'border-danger focus:border-danger focus:ring-danger/20'
            : 'border-gray-200',
          className
        )}
        {...props}
      />
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      {!error && hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}
