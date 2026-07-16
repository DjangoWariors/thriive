import { useState } from 'react';
import { X } from 'lucide-react';
import { Spinner } from '../ui/Spinner';
import { useSKUs } from '../../hooks/useMasterData';

/**
 * Search + chips multi-select for an explicit list of SKU codes. Users search the
 * SKU master by code or name and add matches as removable chips, instead of typing
 * a comma-separated list by hand.
 */
export function SKUMultiSelect({
    value,
    onChange,
    label,
    placeholder = 'Search products by code or name…',
}: {
    value: string[];
    onChange: (codes: string[]) => void;
    label?: string;
    placeholder?: string;
}) {
    const [q, setQ] = useState('');
    const [open, setOpen] = useState(false);

    const term = q.trim();
    const { data, isLoading } = useSKUs(open && term.length > 0 ? { search: term } : undefined);
    const results = (open && term.length > 0 ? data?.results ?? [] : []).filter(
        (s) => !value.includes(s.code),
    );

    const add = (code: string) => {
        if (!value.includes(code)) onChange([...value, code]);
    };
    const remove = (code: string) => onChange(value.filter((c) => c !== code));

    return (
        <div className="relative w-full space-y-1.5">
            {label && <label className="text-xs font-medium text-gray-600">{label}</label>}
            {value.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                    {value.map((code) => (
                        <span
                            key={code}
                            className="flex items-center gap-1 rounded-md border border-gray-200 bg-gray-50 px-2 py-0.5 font-mono text-xs text-gray-700"
                        >
                            {code}
                            <button
                                type="button"
                                onClick={() => remove(code)}
                                className="rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                                aria-label={`Remove ${code}`}
                            >
                                <X className="h-3 w-3" />
                            </button>
                        </span>
                    ))}
                </div>
            )}
            <input
                type="text"
                placeholder={placeholder}
                value={q}
                onChange={(e) => {
                    setQ(e.target.value);
                    setOpen(true);
                }}
                onFocus={() => setOpen(true)}
                onBlur={() => setTimeout(() => setOpen(false), 150)}
                className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm
                   focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            {open && term.length > 0 && (
                <div className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                    {isLoading && (
                        <div className="flex justify-center py-2">
                            <Spinner size="sm" />
                        </div>
                    )}
                    {!isLoading && results.length === 0 && (
                        <p className="px-3 py-2 text-sm text-gray-400">No matching products.</p>
                    )}
                    {results.map((s) => (
                        <button
                            key={s.id}
                            type="button"
                            onMouseDown={() => {
                                add(s.code);
                                setQ('');
                                setOpen(false);
                            }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
                        >
                            <span className="font-mono text-xs text-gray-500">{s.code}</span>
                            <span className="flex-1 truncate">{s.name}</span>
                            {s.brand && <span className="text-xs text-gray-500">{s.brand}</span>}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
