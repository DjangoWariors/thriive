import {cn} from '../../utils/cn';
import type {EntityType} from '../../types/entity';

interface Props {
    blueprint: EntityType[];
    counts: Record<string, number>;
    total: number;
    activeType: string | null;
    onTypeSelect: (code: string | null) => void;
}

export function BlueprintPanel({blueprint, counts, total, activeType, onTypeSelect}: Props) {

    return (
        <div className="border-b border-gray-200 bg-gray-50 px-3 py-2.5">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
                Entity Types
            </p>
            <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none">

                <button
                    type="button"
                    onClick={() => onTypeSelect(null)}
                    className={cn(
                        'flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                        activeType === null
                            ? 'border-primary bg-primary text-white'
                            : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300',
                    )}
                >
                    All
                    <span
                        className={cn('rounded-full px-1 text-xs', activeType === null ? 'bg-white/20' : 'bg-gray-100')}>
            {total}
          </span>
                </button>

                {blueprint.map((et) => {
                    const active = activeType === et.code;
                    const count = counts[et.code] ?? 0;
                    const color = et.display_config.color ?? '#6B7280';

                    return (
                        <button
                            key={et.id}
                            type="button"
                            onClick={() => onTypeSelect(active ? null : et.code)}
                            className={cn(
                                'flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                                active
                                    ? 'border-primary bg-primary text-white'
                                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300',
                            )}
                        >
              <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{background: active ? 'white' : color}}
              />
                            {et.name}
                            <span
                                className={cn('rounded-full px-1 text-xs', active ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500')}>
                {count}
              </span>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
