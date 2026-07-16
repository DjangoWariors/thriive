import { useState } from 'react';
import { Check, X } from 'lucide-react';
import { Spinner } from '../ui/Spinner';
import { useEntitySearch } from '../../hooks/useEntities';

export interface EntitySelection {
    id: number;
    name: string;
    type: string;
    code: string;
}

/**
 * Search-driven entity picker. Queries /entities/search/ by term so users pick
 * a person or team by name instead of hunting for a numeric ID on another screen.
 */
export function EntityCombobox({
    value,
    onChange,
    label,
    placeholder = 'Search a person or team…',
}: {
    value: EntitySelection | null;
    onChange: (entity: EntitySelection | null) => void;
    label?: string;
    placeholder?: string;
}) {
    const [q, setQ] = useState('');
    const [open, setOpen] = useState(false);

    const term = q.trim();
    const { data, isLoading } = useEntitySearch(term.length > 0 ? term : '');
    const results = term.length > 0 ? (data ?? []) : [];

    if (value) {
        return (
            <div className="space-y-1">
                {label && <label className="text-xs font-medium text-gray-600">{label}</label>}
                <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                    <span className="flex min-w-0 items-center gap-2 text-sm">
                        <Check className="h-4 w-4 shrink-0 text-success" />
                        <span className="truncate font-medium text-gray-900">{value.name}</span>
                        <span className="text-xs text-gray-500">{value.type}</span>
                    </span>
                    <button
                        type="button"
                        onClick={() => onChange(null)}
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
                        <p className="px-3 py-2 text-sm text-gray-400">No matching people or teams.</p>
                    )}
                    {results.map((e) => (
                        <button
                            key={e.id}
                            type="button"
                            onMouseDown={() => {
                                onChange({ id: e.id, name: e.name, type: e.entity_type_name ?? '', code: e.code });
                                setQ('');
                                setOpen(false);
                            }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
                        >
                            <span className="flex-1 truncate">{e.name}</span>
                            <span className="text-xs text-gray-500">{e.entity_type_name ?? e.code}</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
