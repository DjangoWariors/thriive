import { useEffect, useState } from 'react';
import { Check, X } from 'lucide-react';
import { Spinner } from '../ui/Spinner';
import { useSKUGroups } from '../../hooks/useMasterData';
import type { SKUGroup } from '../../types/master';

/**
 * Search-driven SKU-group picker. Users pick a group by name/code instead of
 * typing its code blind. On edit-load the parent only has the group code, so we
 * resolve it to the full group (for the name + resolved count) via a code search.
 */
export function SKUGroupCombobox({
    value,
    onChange,
    label,
    placeholder = 'Search a product group by name or code…',
}: {
    value: string;
    onChange: (group: SKUGroup | null) => void;
    label?: string;
    placeholder?: string;
}) {
    const [q, setQ] = useState('');
    const [open, setOpen] = useState(false);
    const [selected, setSelected] = useState<SKUGroup | null>(null);

    const term = q.trim();
    const { data, isLoading } = useSKUGroups(open && term.length > 0 ? { search: term } : undefined);
    const results = open && term.length > 0 ? (data?.results ?? []) : [];

    // Resolve a code coming from saved state (or a template) to the full group so the
    // chip can show the name and resolved count, not a bare code.
    const needsResolve = !!value && (!selected || selected.code !== value);
    const { data: resolveData } = useSKUGroups(needsResolve ? { search: value } : undefined);
    useEffect(() => {
        if (!value) {
            if (selected) setSelected(null);
            return;
        }
        if (needsResolve && resolveData) {
            const match = resolveData.results.find((g) => g.code === value) ?? null;
            if (match) setSelected(match);
        }
    }, [value, needsResolve, resolveData, selected]);

    if (value && selected && selected.code === value) {
        return (
            <div className="space-y-1">
                {label && <label className="text-xs font-medium text-gray-600">{label}</label>}
                <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                    <span className="flex min-w-0 items-center gap-2 text-sm">
                        <Check className="h-4 w-4 shrink-0 text-success" />
                        <span className="font-mono text-xs text-gray-500">{selected.code}</span>
                        <span className="truncate font-medium text-gray-900">{selected.name}</span>
                        <span className="shrink-0 text-xs text-gray-400">({selected.resolved_sku_count} SKUs)</span>
                    </span>
                    <button
                        type="button"
                        onClick={() => {
                            setSelected(null);
                            onChange(null);
                        }}
                        className="ml-2 shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                        aria-label="Clear selection"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="relative w-full space-y-1">
            {label && <label className="text-xs font-medium text-gray-600">{label}</label>}
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
                        <p className="px-3 py-2 text-sm text-gray-400">No matching product groups.</p>
                    )}
                    {results.map((g) => (
                        <button
                            key={g.id}
                            type="button"
                            onMouseDown={() => {
                                setSelected(g);
                                onChange(g);
                                setQ('');
                                setOpen(false);
                            }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
                        >
                            <span className="font-mono text-xs text-gray-500">{g.code}</span>
                            <span className="flex-1 truncate">{g.name}</span>
                            <span className="text-xs text-gray-500">{g.resolved_sku_count} SKUs</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
