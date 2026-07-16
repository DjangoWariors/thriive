import {create} from 'zustand';
import type {EntityStatus} from '../types/entity';

interface HierarchyState {
    /** Which tree node IDs are expanded. */
    expanded: Record<number, boolean>;
    /** Currently selected entity ID (shown in right panel). */
    selectedId: number | null;
    /** Multi-selected entity IDs for bulk actions. */
    selectedIds: Set<number>;
    /** Status of each checked entity, so the bulk bar can be status-aware. */
    selectedStatuses: Record<number, EntityStatus>;
    toggle: (id: number) => void;
    select: (id: number | null) => void;
    toggleChecked: (id: number, status: EntityStatus) => void;
    clearChecked: () => void;
    reset: () => void;
}

export const useHierarchyStore = create<HierarchyState>()((set) => ({
    expanded: {},
    selectedId: null,
    selectedIds: new Set<number>(),
    selectedStatuses: {},

    toggle: (id) =>
        set((state) => ({
            expanded: {...state.expanded, [id]: !state.expanded[id]},
        })),

    select: (id) => set({selectedId: id}),

    toggleChecked: (id, status) =>
        set((state) => {
            const next = new Set(state.selectedIds);
            const statuses = {...state.selectedStatuses};
            if (next.has(id)) {
                next.delete(id);
                delete statuses[id];
            } else {
                next.add(id);
                statuses[id] = status;
            }
            return {selectedIds: next, selectedStatuses: statuses};
        }),

    clearChecked: () => set({selectedIds: new Set<number>(), selectedStatuses: {}}),

    reset: () =>
        set({expanded: {}, selectedId: null, selectedIds: new Set<number>(), selectedStatuses: {}}),
}));
