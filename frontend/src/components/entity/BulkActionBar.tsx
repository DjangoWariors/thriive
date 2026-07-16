import {FolderTree, UserX, RotateCcw, X} from 'lucide-react';

interface Props {
    count: number;
    /** How many of the selected entities are currently active vs not. */
    activeCount: number;
    inactiveCount: number;
    /** Bulk parent move (reporting-line change) — NOT a territory transfer. */
    onMove: () => void;
    onDeactivate: () => void;
    onReactivate: () => void;
    onClear: () => void;
}

export function BulkActionBar({
    count,
    activeCount,
    inactiveCount,
    onMove,
    onDeactivate,
    onReactivate,
    onClear,
}: Props) {
    if (count === 0) return null;

    return (
        <div className="flex items-center gap-2 border-t border-gray-200 bg-primary-50 px-3 py-2">
            <span className="text-sm font-medium text-primary">{count} selected</span>
            <div className="ml-auto flex items-center gap-1">
                <button
                    type="button"
                    onClick={onMove}
                    className="flex items-center gap-1 rounded-lg border border-primary/30 bg-white px-2 py-1 text-xs font-medium text-primary hover:bg-primary hover:text-white transition-colors"
                >
                    <FolderTree className="h-3.5 w-3.5"/>
                    Move to new manager
                </button>
                {activeCount > 0 && (
                    <button
                        type="button"
                        onClick={onDeactivate}
                        className="flex items-center gap-1 rounded-lg border border-danger/30 bg-white px-2 py-1 text-xs font-medium text-danger hover:bg-danger hover:text-white transition-colors"
                    >
                        <UserX className="h-3.5 w-3.5"/>
                        Deactivate{inactiveCount > 0 ? ` (${activeCount})` : ''}
                    </button>
                )}
                {inactiveCount > 0 && (
                    <button
                        type="button"
                        onClick={onReactivate}
                        className="flex items-center gap-1 rounded-lg border border-success/30 bg-white px-2 py-1 text-xs font-medium text-success hover:bg-success hover:text-white transition-colors"
                    >
                        <RotateCcw className="h-3.5 w-3.5"/>
                        Activate{activeCount > 0 ? ` (${inactiveCount})` : ''}
                    </button>
                )}
                <button
                    type="button"
                    onClick={onClear}
                    title="Clear selection"
                    className="rounded-lg p-1 text-gray-400 hover:text-gray-600"
                >
                    <X className="h-4 w-4"/>
                </button>
            </div>
        </div>
    );
}
