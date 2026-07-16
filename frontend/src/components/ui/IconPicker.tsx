import {useMemo, useRef, useState} from 'react';
import {ChevronDown, Search} from 'lucide-react';
import {cn} from '../../utils/cn';
import {ENTITY_ICONS, resolveIcon} from '../../utils/entityIcons';

interface Props {
    value?: string | null;
    onChange: (name: string) => void;
    placeholder?: string;
}

/**
 * Searchable icon grid. Replaces free-text "type a lucide name" entry — users
 * pick from a curated set with live previews. Stores the kebab-case name.
 */
export function IconPicker({value, onChange, placeholder = 'Choose an icon'}: Props) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const containerRef = useRef<HTMLDivElement>(null);

    const Current = resolveIcon(value);

    const results = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return ENTITY_ICONS;
        return ENTITY_ICONS.filter((i) => i.name.includes(q));
    }, [query]);

    return (
        <div ref={containerRef} className="relative">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="flex w-full items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm
                   hover:border-gray-300 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
                <span className="flex items-center gap-2 text-gray-700">
                    <Current className="h-4 w-4 text-gray-500"/>
                    {value ? value : <span className="text-gray-400">{placeholder}</span>}
                </span>
                <ChevronDown className={cn('h-4 w-4 text-gray-400 transition-transform', open && 'rotate-180')}/>
            </button>

            {open && (
                <>
                    <div className="fixed inset-0 z-10" onClick={() => setOpen(false)}/>
                    <div className="absolute z-20 mt-1 w-full rounded-lg border border-gray-200 bg-white p-2 shadow-lg">
                        <div className="relative mb-2">
                            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400"/>
                            <input
                                autoFocus
                                type="text"
                                placeholder="Search icons…"
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                className="w-full rounded-lg border border-gray-200 bg-gray-50 py-1.5 pl-8 pr-3 text-sm
                           focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                            />
                        </div>
                        <div className="grid max-h-48 grid-cols-7 gap-1 overflow-y-auto">
                            {results.map(({name, Icon}) => (
                                <button
                                    key={name}
                                    type="button"
                                    title={name}
                                    aria-label={name}
                                    onClick={() => {
                                        onChange(name);
                                        setOpen(false);
                                        setQuery('');
                                    }}
                                    className={cn(
                                        'flex aspect-square items-center justify-center rounded-lg border transition-colors',
                                        value === name
                                            ? 'border-primary bg-primary-50 text-primary'
                                            : 'border-transparent text-gray-600 hover:bg-gray-100',
                                    )}
                                >
                                    <Icon className="h-4 w-4"/>
                                </button>
                            ))}
                            {results.length === 0 && (
                                <p className="col-span-7 py-3 text-center text-xs text-gray-400">No icons match “{query}”.</p>
                            )}
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}
