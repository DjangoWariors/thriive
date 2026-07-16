import {useState} from 'react';
import {ChevronRight, ChevronDown, MapPin} from 'lucide-react';
import {cn} from '../../utils/cn';
import {Spinner} from '../ui/Spinner';
import {Badge} from '../ui/Badge';
import {useGeographyNodeChildren} from '../../hooks/useEntities';
import type {GeographyNode} from '../../types/entity';


interface NodeProps {
    node: GeographyNode;
    depth: number;
    selectedId: number | null;
    onSelect: (node: GeographyNode) => void;
}

function GeoTreeNode({node, depth, selectedId, onSelect}: NodeProps) {
    const [expanded, setExpanded] = useState(false);
    const hasChildren = node.children_count > 0;

    const {data: children, isLoading} = useGeographyNodeChildren(node.id, expanded);

    return (
        <div>
            <div
                className={cn(
                    'group flex cursor-pointer items-center gap-1 rounded-lg py-1.5 pr-2 text-sm transition-colors',
                    selectedId === node.id ? 'bg-primary-50 text-primary' : 'text-gray-700 hover:bg-gray-100',
                )}
                style={{paddingLeft: `${depth * 20 + 8}px`}}
                onClick={() => onSelect(node)}
            >
                {hasChildren ? (
                    <button
                        type="button"
                        className="flex h-4 w-4 shrink-0 items-center justify-center text-gray-400 hover:text-gray-600"
                        onClick={(e) => {
                            e.stopPropagation();
                            setExpanded((v) => !v);
                        }}
                        aria-label={expanded ? 'Collapse' : 'Expand'}
                    >
                        {isLoading ? (
                            <Spinner size="sm"/>
                        ) : expanded ? (
                            <ChevronDown className="h-3 w-3"/>
                        ) : (
                            <ChevronRight className="h-3 w-3"/>
                        )}
                    </button>
                ) : (
                    <MapPin className="h-3 w-3 shrink-0 text-gray-300"/>
                )}

                <span className="flex-1 truncate font-medium">{node.name}</span>
                <Badge variant="default" className="shrink-0">{node.level}</Badge>
                {hasChildren && (
                    <span className="shrink-0 rounded-full bg-gray-100 px-1.5 text-xs text-gray-500">
                        {node.children_count}
                    </span>
                )}
            </div>

            {expanded && children && children.length > 0 && (
                <div>
                    {children.map((child) => (
                        <GeoTreeNode
                            key={child.id}
                            node={child}
                            depth={depth + 1}
                            selectedId={selectedId}
                            onSelect={onSelect}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}


interface Props {
    roots: GeographyNode[];
    isLoading: boolean;
    selectedId: number | null;
    onSelect: (node: GeographyNode) => void;
}

export function GeographyTree({roots, isLoading, selectedId, onSelect}: Props) {
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
                No geography nodes yet. Add a top-level node to get started.
            </p>
        );
    }
    return (
        <div className="py-2">
            {roots.map((root) => (
                <GeoTreeNode
                    key={root.id}
                    node={root}
                    depth={0}
                    selectedId={selectedId}
                    onSelect={onSelect}
                />
            ))}
        </div>
    );
}
