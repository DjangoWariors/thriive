import {useState} from 'react';
import {Check, X} from 'lucide-react';
import {Spinner} from '../ui/Spinner';
import {useGeographyNodes} from '../../hooks/useEntities';

export interface GeoSelection {
    id: number;
    name: string;
    level: string;
    code: string;
}

/**
 * Search-driven territory picker. Queries the geography-nodes endpoint by term
 * instead of rendering every node as an <option> — safe when a client has tens
 * of thousands of territories/beats.
 */
export function GeoNodeCombobox({
    typeCode,
    value,
    onChange,
    label,
    placeholder = 'Search territory…',
    levels,
    excludePathPrefix,
}: {
    typeCode: string;
    value: GeoSelection | null;
    onChange: (node: GeoSelection | null) => void;
    label?: string;
    placeholder?: string;
    /** Restrict matches to these level names (e.g. levels shallower than the node being placed). */
    levels?: string[];
    /** Drop a node and its whole subtree from the results (Move: never offer self/descendants). */
    excludePathPrefix?: string;
}) {
    const [q, setQ] = useState('');
    const [open, setOpen] = useState(false);

    const term = q.trim();
    const {data, isLoading} = useGeographyNodes(
        typeCode && term.length > 0
            ? {
                type: typeCode, q: term, page_size: 50,
                ...(levels && levels.length > 0 ? {levels: levels.join(',')} : {}),
            }
            : undefined,
    );
    const nodes = (term.length > 0 ? (data?.results ?? []) : []).filter(
        (n) => !excludePathPrefix || !n.path.startsWith(excludePathPrefix),
    );

    if (value) {
        return (
            <div className="space-y-1">
                {label && <label className="text-xs font-medium text-gray-600">{label}</label>}
                <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                    <span className="flex min-w-0 items-center gap-2 text-sm">
                        <Check className="h-4 w-4 shrink-0 text-success"/>
                        <span className="truncate font-medium text-gray-900">{value.name}</span>
                        <span className="text-xs text-gray-500">{value.level}</span>
                    </span>
                    <button
                        type="button"
                        onClick={() => onChange(null)}
                        className="ml-2 shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                        aria-label="Clear territory"
                    >
                        <X className="h-4 w-4"/>
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
                <div className="absolute z-10 mt-1 max-h-40 w-full overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                    {isLoading && (
                        <div className="flex justify-center py-2">
                            <Spinner size="sm"/>
                        </div>
                    )}
                    {!isLoading && nodes.length === 0 && (
                        <p className="px-3 py-2 text-sm text-gray-400">No matching territories.</p>
                    )}
                    {nodes.map((n) => (
                        <button
                            key={n.id}
                            type="button"
                            onMouseDown={() => {
                                onChange({id: n.id, name: n.name, level: n.level, code: n.code});
                                setQ('');
                                setOpen(false);
                            }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
                        >
                            <span className="flex-1 truncate">{n.name}</span>
                            <span className="text-xs text-gray-500">{n.level}</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
