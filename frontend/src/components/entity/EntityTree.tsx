import {useEffect, useMemo, useRef} from 'react';
import {ChevronRight, ChevronDown, Circle} from 'lucide-react';
import {useVirtualizer} from '@tanstack/react-virtual';
import {cn} from '../../utils/cn';
import {Spinner} from '../ui/Spinner';
import {StatusBadge} from '../ui/StatusBadge';
import {useEntityChildren, useEntitiesInfinite} from '../../hooks/useEntities';
import {useHierarchyStore} from '../../stores/hierarchyStore';
import type {EntityListItem, EntityListParams, EntityType} from '../../types/entity';



interface NodeProps {
    item: EntityListItem;
    depth: number;
    blueprint: EntityType[];
}

function TreeNode({item, depth, blueprint}: NodeProps) {
    const {expanded, selectedId, selectedIds, toggle, select, toggleChecked} = useHierarchyStore();
    const isExpanded = expanded[item.id] ?? false;
    const isSelected = selectedId === item.id;
    const isChecked = selectedIds.has(item.id);


    const et = blueprint.find((t) => t.code === item.entity_type_code);
    const isLeaf = et?.is_leaf ?? false;


    const {
        data: childrenData,
        isLoading: childrenLoading,
        fetchNextPage,
        hasNextPage,
        isFetchingNextPage,
    } = useEntityChildren(isExpanded ? item.id : 0);
    const children = useMemo(
        () => childrenData?.pages.flatMap((p) => p.results) ?? [],
        [childrenData],
    );

    const color = et?.display_config.color ?? '#6B7280';
    const showToggle = !isLeaf;

    return (
        <div>
            <div
                className={cn(
                    'group flex cursor-pointer items-center gap-1 rounded-lg py-1.5 pr-2 text-sm transition-colors',
                    isSelected
                        ? 'bg-primary-50 text-primary'
                        : 'text-gray-700 hover:bg-gray-100',
                )}
                style={{paddingLeft: `${depth * 20 + 8}px`}}
                onClick={() => select(item.id)}
            >

                <input
                    type="checkbox"
                    checked={isChecked}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggleChecked(item.id, item.status)}
                    className="h-3.5 w-3.5 shrink-0 rounded border-gray-300 text-primary focus:ring-primary/30"
                    aria-label={`Select ${item.name}`}
                />


                {showToggle ? (
                    <button
                        type="button"
                        className="flex h-4 w-4 shrink-0 items-center justify-center text-gray-400 hover:text-gray-600"
                        onClick={(e) => {
                            e.stopPropagation();
                            toggle(item.id);
                        }}
                        aria-label={isExpanded ? 'Collapse' : 'Expand'}
                    >
                        {childrenLoading ? (
                            <Spinner size="sm"/>
                        ) : isExpanded ? (
                            <ChevronDown className="h-3 w-3"/>
                        ) : (
                            <ChevronRight className="h-3 w-3"/>
                        )}
                    </button>
                ) : (
                    <span className="w-4 shrink-0"/>
                )}


                <Circle
                    className="h-2 w-2 shrink-0 fill-current"
                    style={{color}}
                    aria-hidden="true"
                />


                <span className={cn(
                    'flex-1 truncate font-medium',
                    item.status !== 'active' && !isSelected && 'text-gray-400',
                )}>{item.name}</span>
                {item.entity_type_code && (
                    <span className="shrink-0 rounded bg-gray-100 px-1 font-mono text-xs text-gray-500">
            {item.entity_type_code}
          </span>
                )}
                {item.status !== 'active' && (
                    <StatusBadge status={item.status} className="shrink-0"/>
                )}
            </div>


            {isExpanded && children.length > 0 && (
                <div>
                    {children.map((child) => (
                        <TreeNode key={child.id} item={child} depth={depth + 1} blueprint={blueprint}/>
                    ))}
                    {hasNextPage && (
                        <button
                            type="button"
                            onClick={() => void fetchNextPage()}
                            disabled={isFetchingNextPage}
                            className="flex items-center gap-1 py-1 text-xs font-medium text-primary hover:text-primary-dark disabled:opacity-50"
                            style={{paddingLeft: `${(depth + 1) * 20 + 28}px`}}
                        >
                            {isFetchingNextPage ? (
                                <Spinner size="sm"/>
                            ) : (
                                <ChevronDown className="h-3 w-3"/>
                            )}
                            {isFetchingNextPage ? 'Loading…' : 'Load more'}
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}


interface Props {
    items: EntityListItem[];
    blueprint: EntityType[];
    isLoading: boolean;
}

export function EntityTree({items, blueprint, isLoading}: Props) {

    const roots = items.filter((e) => e.parent === null);

    if (isLoading) {
        return (
            <div className="flex items-center justify-center py-12">
                <Spinner size="lg"/>
            </div>
        );
    }

    if (roots.length === 0) {
        return (
            <p className="py-8 text-center text-sm text-gray-400">
                No entities found. Create one to get started.
            </p>
        );
    }

    return (
        <div className="py-2">
            {roots.map((root) => (
                <TreeNode key={root.id} item={root} depth={0} blueprint={blueprint}/>
            ))}
        </div>
    );
}



function FlatRow({item}: { item: EntityListItem }) {
    const {selectedId, selectedIds, select, toggleChecked} = useHierarchyStore();
    return (
        <div
            onClick={() => select(item.id)}
            className={cn(
                'mx-2 flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors',
                selectedId === item.id ? 'bg-primary-50 text-primary' : 'text-gray-700 hover:bg-gray-100',
            )}
        >
            <input
                type="checkbox"
                checked={selectedIds.has(item.id)}
                onClick={(e) => e.stopPropagation()}
                onChange={() => toggleChecked(item.id, item.status)}
                className="h-3.5 w-3.5 shrink-0 rounded border-gray-300 text-primary focus:ring-primary/30"
                aria-label={`Select ${item.name}`}
            />
            <span className={cn(
                'flex-1 truncate font-medium',
                item.status !== 'active' && selectedId !== item.id && 'text-gray-400',
            )}>{item.name}</span>
            {item.entity_type_code && (
                <span className="shrink-0 rounded bg-gray-100 px-1 font-mono text-xs text-gray-500">
          {item.entity_type_code}
        </span>
            )}
            {item.status !== 'active' && <StatusBadge status={item.status}/>}
        </div>
    );
}


export function FlatEntityList({items, isLoading}: { items: EntityListItem[]; isLoading: boolean }) {
    if (isLoading) {
        return (
            <div className="flex items-center justify-center py-12">
                <Spinner size="lg"/>
            </div>
        );
    }
    if (items.length === 0) {
        return <p className="py-8 text-center text-sm text-gray-400">No results.</p>;
    }

    return (
        <div className="py-2 space-y-0.5">
            {items.map((item) => (
                <FlatRow key={item.id} item={item}/>
            ))}
        </div>
    );
}



/** Virtualized infinite list over any entity-list filter set (type, channel,
 * geography, …) — the safe rendering path for filters that can match 150k rows. */
export function VirtualEntityList({params}: { params: EntityListParams }) {
    const {data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage} =
        useEntitiesInfinite(params);

    const items = useMemo(() => data?.pages.flatMap((p) => p.results) ?? [], [data]);
    const parentRef = useRef<HTMLDivElement>(null);

    const virtualizer = useVirtualizer({
        count: items.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 38,
        overscan: 12,
    });
    const virtualItems = virtualizer.getVirtualItems();


    useEffect(() => {
        const last = virtualItems[virtualItems.length - 1];
        if (last && last.index >= items.length - 1 && hasNextPage && !isFetchingNextPage) {
            void fetchNextPage();
        }
    }, [virtualItems, items.length, hasNextPage, isFetchingNextPage, fetchNextPage]);

    if (isLoading) {
        return (
            <div className="flex items-center justify-center py-12">
                <Spinner size="lg"/>
            </div>
        );
    }
    if (items.length === 0) {
        return <p className="py-8 text-center text-sm text-gray-400">No results.</p>;
    }

    return (
        <div ref={parentRef} className="h-full overflow-y-auto py-2">
            <div style={{height: virtualizer.getTotalSize(), position: 'relative', width: '100%'}}>
                {virtualItems.map((v) => (
                    <div
                        key={items[v.index].id}
                        style={{
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            width: '100%',
                            height: v.size,
                            transform: `translateY(${v.start}px)`,
                        }}
                    >
                        <FlatRow item={items[v.index]}/>
                    </div>
                ))}
            </div>
            {isFetchingNextPage && (
                <div className="flex justify-center py-2">
                    <Spinner size="sm"/>
                </div>
            )}
        </div>
    );
}
