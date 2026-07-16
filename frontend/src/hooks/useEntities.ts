import {
    useInfiniteQuery,
    useMutation,
    useQuery,
    useQueryClient,
} from '@tanstack/react-query';
import {entityService} from '../services/entityService';
import type {
    BulkDeactivatePayload,
    BulkImportPayload,
    BulkMovePayload,
    BulkReactivatePayload,
    ChangeTypePayload,
    CreateChannelPayload,
    CreateEntityPayload,
    CreateGeographyNodePayload,
    CreateGeographyTypePayload,
    EntityListParams,
    EntityType,
    GeoNodeQueryParams,
    MoveEntityPayload,
    RelationshipQueryParams,
    TransferPersonPayload,
    UpdateChannelPayload,
    UpdateEntityPayload,
    UpdateGeographyNodePayload,
} from '../types/entity';



export const entityQueryKeys = {
    types: () => ['entity-types', 'list'] as const,
    blueprint: () => ['entity-types', 'blueprint'] as const,
    typeVersions: (id: number) => ['entity-types', 'versions', id] as const,

    lists: () => ['entities'] as const,
    list: (params: EntityListParams) => ['entities', 'list', params] as const,
    listInfinite: (params: EntityListParams) => ['entities', 'list-infinite', params] as const,
    detail: (id: number) => ['entities', 'detail', id] as const,
    counts: () => ['entities', 'counts'] as const,
    children: (id: number) => ['entities', 'children', id] as const,
    subtree: (id: number) => ['entities', 'subtree', id] as const,
    ancestors: (id: number) => ['entities', 'ancestors', id] as const,
    team: (id: number, types?: string[]) => ['entities', 'team', id, types] as const,
    search: (q: string, type?: string) => ['entities', 'search', q, type] as const,
    transferImpact: (id: number | null) => ['entities', 'transfer-impact', id] as const,

    relationships: (entityId: number, params?: RelationshipQueryParams) =>
        ['entity-relationships', entityId, params] as const,
    relTypes: () => ['relationship-types', 'list'] as const,

    geoTypes: () => ['geography-types', 'list'] as const,
    geoNodes: (params?: GeoNodeQueryParams) => ['geography-nodes', 'list', params] as const,
    geoChildren: (id: number) => ['geography-nodes', 'subtree', id] as const,
    geoTree: (typeCode: string) => ['geography-nodes', 'tree', typeCode] as const,
    geoNodeChildren: (id: number) => ['geography-nodes', 'children', id] as const,

    channels: () => ['channels', 'list'] as const,
};


const STALE_CONFIG = 5 * 60 * 1000;   // 5 min — config data changes rarely
const STALE_DATA = 60 * 1000;          // 1 min — operational data
const STALE_SEARCH = 30 * 1000;        // 30 sec — active user interaction


export function useEntityTypes() {
    return useQuery({
        queryKey: entityQueryKeys.types(),
        queryFn: () => entityService.listTypes(),
        staleTime: STALE_CONFIG,
    });
}

export function useBlueprint() {
    return useQuery({
        queryKey: entityQueryKeys.blueprint(),
        queryFn: () => entityService.getBlueprint(),
        staleTime: STALE_CONFIG,
    });
}


export function useCreateEntityType() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: Partial<EntityType>) => entityService.createType(payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.types()});
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.blueprint()});
        },
    });
}

export function useUpdateEntityType() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({id, payload}: { id: number; payload: Partial<EntityType> }) =>
            entityService.updateType(id, payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.types()});
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.blueprint()});
        },
    });
}


export function useEntities(params: EntityListParams = {}) {
    return useQuery({
        queryKey: entityQueryKeys.list(params),
        queryFn: () => entityService.list(params),
        staleTime: STALE_DATA,
    });
}

/**
 * Paginated entity list that loads every page progressively — for virtualized,
 * large filtered lists (e.g. all retailers of a type). page_size respects the
 * backend max (200).
 */
export function useEntitiesInfinite(params: EntityListParams = {}) {
    return useInfiniteQuery({
        queryKey: entityQueryKeys.listInfinite(params),
        queryFn: ({pageParam}) => entityService.list({...params, page: pageParam, page_size: 200}),
        initialPageParam: 1,
        getNextPageParam: (lastPage, allPages) =>
            lastPage.next ? allPages.length + 1 : undefined,
        staleTime: STALE_DATA,
    });
}

export function useEntity(id: number) {
    return useQuery({
        queryKey: entityQueryKeys.detail(id),
        queryFn: () => entityService.get(id),
        staleTime: STALE_DATA,
        enabled: id > 0,
    });
}

export function useEntityChildren(id: number) {
    return useInfiniteQuery({
        queryKey: entityQueryKeys.children(id),
        queryFn: ({pageParam}) => entityService.children(id, pageParam),
        initialPageParam: 1,
        getNextPageParam: (lastPage, allPages) => (lastPage.next ? allPages.length + 1 : undefined),
        staleTime: STALE_DATA,
        enabled: id > 0,
    });
}

export function useEntitySubtree(id: number) {
    return useQuery({
        queryKey: entityQueryKeys.subtree(id),
        queryFn: () => entityService.subtree(id),
        staleTime: STALE_DATA,
        enabled: id > 0,
    });
}

export function useEntityCounts() {
    return useQuery({
        queryKey: entityQueryKeys.counts(),
        queryFn: () => entityService.entityCounts(),
        staleTime: STALE_DATA,
    });
}

export function useEntityAncestors(id: number) {
    return useQuery({
        queryKey: entityQueryKeys.ancestors(id),
        queryFn: () => entityService.ancestors(id),
        staleTime: STALE_DATA,
        enabled: id > 0,
    });
}


export function useEntitySearch(q: string, type?: string) {
    return useQuery({
        queryKey: entityQueryKeys.search(q, type),
        queryFn: () => entityService.search(q, type),
        staleTime: STALE_SEARCH,
        enabled: q.trim().length > 0,
    });
}


export function useCreateEntity() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: CreateEntityPayload) => entityService.create(payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
        },
    });
}

export function useUpdateEntity() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({id, data}: { id: number; data: UpdateEntityPayload }) =>
            entityService.update(id, data),
        onSuccess: (_result, {id}) => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.detail(id)});
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
        },
    });
}

export function useMoveEntity() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({id, data}: { id: number; data: MoveEntityPayload }) =>
            entityService.move(id, data),
        onSuccess: (_result, {id}) => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.detail(id)});
            // Move changes paths across the tree — invalidate all list caches
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
        },
    });
}

export function useTransferPerson() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({id, payload}: { id: number; payload: TransferPersonPayload }) =>
            entityService.transfer(id, payload),
        onSuccess: (_result, {id}) => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.detail(id)});
            // Promoting reports + relocating the incumbent shifts paths — refresh all lists.
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
            // Territory handover changes owners — refresh assignment views too.
            void queryClient.invalidateQueries({queryKey: ['assignments']});
        },
    });
}

export function useTransferImpact(id: number | null) {
    return useQuery({
        queryKey: entityQueryKeys.transferImpact(id),
        queryFn: () => entityService.transferImpact(id!),
        enabled: id !== null,
        staleTime: STALE_DATA,
    });
}

export function useDeactivateEntity() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => entityService.deactivate(id),
        onSuccess: (_result, id) => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.detail(id)});
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
        },
    });
}

export function useChangeEntityType() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({id, payload}: { id: number; payload: ChangeTypePayload }) =>
            entityService.changeType(id, payload),
        onSuccess: (_result, {id}) => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.detail(id)});
            // Type/parent change can move subtrees — refresh all lists.
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
        },
    });
}

export function useReactivateEntity() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => entityService.reactivate(id),
        onSuccess: (_result, id) => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.detail(id)});
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
        },
    });
}

export function useBulkMoveEntities() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: BulkMovePayload) => entityService.bulkMove(payload),
        onSuccess: (res) => {
            if (res.status === 'success') {
                void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
            }
        },
    });
}

export function useBulkDeactivateEntities() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: BulkDeactivatePayload) => entityService.bulkDeactivate(payload),
        onSuccess: (res) => {
            if (res.status === 'success') {
                void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
            }
        },
    });
}

export function useBulkReactivateEntities() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: BulkReactivatePayload) => entityService.bulkReactivate(payload),
        onSuccess: (res) => {
            if (res.status === 'success') {
                void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
            }
        },
    });
}

export function useBulkImport() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: BulkImportPayload | FormData) => entityService.bulkImport(payload),
        onSuccess: (res) => {

            if (!res.async && res.result.status === 'success') {
                void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
            }
        },
    });
}


export function useEntityRelationships(entityId: number, params?: RelationshipQueryParams) {
    return useQuery({
        queryKey: entityQueryKeys.relationships(entityId, params),
        queryFn: () => entityService.getRelationships(entityId, params),
        staleTime: STALE_DATA,
        enabled: entityId > 0,
    });
}



export function useEndRelationship() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => entityService.endRelationship(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({queryKey: ['entity-relationships']});
        },
    });
}


export function useGeographyTypes() {
    return useQuery({
        queryKey: entityQueryKeys.geoTypes(),
        queryFn: () => entityService.listGeoTypes(),
        staleTime: STALE_CONFIG,
    });
}

export function useGeographyNodes(params?: GeoNodeQueryParams) {
    return useQuery({
        queryKey: entityQueryKeys.geoNodes(params),
        queryFn: () => entityService.listGeoNodes(params),
        staleTime: STALE_CONFIG,
    });
}



// ── Channels ────────────────────────────────────────────────────────────────

export function useChannels() {
    return useQuery({
        queryKey: entityQueryKeys.channels(),
        queryFn: () => entityService.listChannels(),
        staleTime: STALE_CONFIG,
    });
}

export function useCreateChannel() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: CreateChannelPayload) => entityService.createChannel(payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.channels()});
        },
    });
}

export function useUpdateChannel() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({id, payload}: {id: number; payload: UpdateChannelPayload}) =>
            entityService.updateChannel(id, payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.channels()});
        },
    });
}

export function useDeactivateChannel() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => entityService.deactivateChannel(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.channels()});
        },
    });
}


// ── Geography management ──────────────────────────────────────────────────────

/** Root nodes for a geography type — the tree's initial load. */
export function useGeographyTree(typeCode: string) {
    return useQuery({
        queryKey: entityQueryKeys.geoTree(typeCode),
        queryFn: () => entityService.geoTree(typeCode),
        staleTime: STALE_CONFIG,
        enabled: typeCode.length > 0,
    });
}

/** Direct children of a node — lazy tree expansion. */
export function useGeographyNodeChildren(id: number, enabled = true) {
    return useQuery({
        queryKey: entityQueryKeys.geoNodeChildren(id),
        queryFn: () => entityService.geoChildren(id),
        staleTime: STALE_CONFIG,
        enabled: enabled && id > 0,
    });
}

function invalidateGeography(queryClient: ReturnType<typeof useQueryClient>) {
    void queryClient.invalidateQueries({queryKey: ['geography-nodes']});
}

export function useCreateGeoType() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: CreateGeographyTypePayload) => entityService.createGeoType(payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({queryKey: entityQueryKeys.geoTypes()});
        },
    });
}

export function useCreateGeoNode() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: CreateGeographyNodePayload) => entityService.createGeoNode(payload),
        onSuccess: () => invalidateGeography(queryClient),
    });
}

export function useUpdateGeoNode() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({id, payload}: {id: number; payload: UpdateGeographyNodePayload}) =>
            entityService.updateGeoNode(id, payload),
        onSuccess: () => invalidateGeography(queryClient),
    });
}

export function useMoveGeoNode() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({id, newParentId}: {id: number; newParentId: number | null}) =>
            entityService.moveGeoNode(id, newParentId),
        onSuccess: () => invalidateGeography(queryClient),
    });
}

export function useDeactivateGeoNode() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => entityService.deactivateGeoNode(id),
        onSuccess: () => invalidateGeography(queryClient),
    });
}
