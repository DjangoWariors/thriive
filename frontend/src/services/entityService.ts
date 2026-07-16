import axios from 'axios';
import api from './api';
import type {PaginatedResponse} from '../types/api';
import type {BulkJob} from '../types/jobs';
import type {
    BulkDeactivatePayload,
    BulkImportPayload,
    BulkImportResult,
    BulkMovePayload,
    BulkOpResult,
    BulkReactivatePayload,
    Channel,
    ChangeTypePayload,
    CreateChannelPayload,
    CreateGeographyNodePayload,
    CreateGeographyTypePayload,
    EntityBulkSubmitResult,
    CreateEntityPayload,
    CreateRelationshipPayload,
    Entity,
    EntityListItem,
    EntityListParams,
    EntityRelationship,
    EntitySubtreeItem,
    EntityType,
    GeoNodeQueryParams,
    GeographyNode,
    GeographyType,
    MoveEntityPayload,
    RelationshipQueryParams,
    RelationshipType,
    TransferImpact,
    TransferPersonPayload,
    UpdateChannelPayload,
    UpdateEntityPayload,
    UpdateGeographyNodePayload,
} from '../types/entity';


async function postBulkOp(url: string, payload: unknown): Promise<BulkOpResult> {
    try {
        const {data} = await api.post<BulkOpResult>(url, payload);
        return data;
    } catch (err) {
        if (
            axios.isAxiosError(err) &&
            err.response?.status === 422 &&
            (err.response.data as BulkOpResult | undefined)?.status === 'validation_failed'
        ) {
            return err.response.data as BulkOpResult;
        }
        throw err;
    }
}

export const entityService = {

    async listTypes(): Promise<PaginatedResponse<EntityType>> {
        const {data} = await api.get<PaginatedResponse<EntityType>>('/api/v1/entity-types/');
        return data;
    },

    async getBlueprint(): Promise<EntityType[]> {
        const {data} = await api.get<EntityType[]>('/api/v1/entity-types/blueprint/');
        return data;
    },

    async createType(payload: Partial<EntityType>): Promise<EntityType> {
        const {data} = await api.post<EntityType>('/api/v1/entity-types/', payload);
        return data;
    },

    async updateType(id: number, payload: Partial<EntityType>): Promise<EntityType> {
        const {data} = await api.put<EntityType>(`/api/v1/entity-types/${id}/`, payload);
        return data;
    },

    async getVersions(id: number): Promise<EntityType[]> {
        const {data} = await api.get<EntityType[]>(`/api/v1/entity-types/${id}/versions/`);
        return data;
    },


    async list(params?: EntityListParams): Promise<PaginatedResponse<EntityListItem>> {
        const {data} = await api.get<PaginatedResponse<EntityListItem>>('/api/v1/entities/', {params});
        return data;
    },

    async create(payload: CreateEntityPayload): Promise<Entity> {
        const {data} = await api.post<Entity>('/api/v1/entities/', payload);
        return data;
    },

    async get(id: number): Promise<Entity> {
        const {data} = await api.get<Entity>(`/api/v1/entities/${id}/`);
        return data;
    },

    async update(id: number, payload: UpdateEntityPayload): Promise<Entity> {
        const {data} = await api.put<Entity>(`/api/v1/entities/${id}/`, payload);
        return data;
    },

    async deactivate(id: number): Promise<void> {
        await api.delete(`/api/v1/entities/${id}/`);
    },

    async reactivate(id: number, reason?: string): Promise<Entity> {
        const {data} = await api.post<Entity>(
            `/api/v1/entities/${id}/reactivate/`,
            reason ? {reason} : {},
        );
        return data;
    },

    async changeType(id: number, payload: ChangeTypePayload): Promise<Entity> {
        const {data} = await api.post<Entity>(`/api/v1/entities/${id}/change-type/`, payload);
        return data;
    },


    // children/subtree/team are paginated server-side — a high node can sit above
    // tens of thousands of rows, so callers page through them.
    async children(id: number, page = 1): Promise<PaginatedResponse<EntityListItem>> {
        const {data} = await api.get<PaginatedResponse<EntityListItem>>(
            `/api/v1/entities/${id}/children/`, {params: {page}},
        );
        return data;
    },

    async subtree(id: number, pageSize = 200): Promise<PaginatedResponse<EntitySubtreeItem>> {
        // One bounded page (count + up to pageSize rows). The detail table browses
        // this set with its own client-side search/pagination; for very large
        // subtrees it shows a "first N of M" note rather than streaming everything.
        const {data} = await api.get<PaginatedResponse<EntitySubtreeItem>>(
            `/api/v1/entities/${id}/subtree/`, {params: {page_size: pageSize}},
        );
        return data;
    },

    async ancestors(id: number): Promise<EntityListItem[]> {
        const {data} = await api.get<EntityListItem[]>(`/api/v1/entities/${id}/ancestors/`);
        return data;
    },

    async team(id: number, types?: string[]): Promise<EntityListItem[]> {
        const {data} = await api.get<PaginatedResponse<EntityListItem>>(`/api/v1/entities/${id}/team/`, {
            params: types && types.length > 0 ? {types: types.join(',')} : undefined,
        });
        return data.results;
    },

    async entityCounts(): Promise<{counts: Record<string, number>; total: number}> {
        const {data} = await api.get<{counts: Record<string, number>; total: number}>(
            '/api/v1/entities/counts/',
        );
        return data;
    },


    async move(id: number, payload: MoveEntityPayload): Promise<Entity> {
        const {data} = await api.post<Entity>(`/api/v1/entities/${id}/move/`, payload);
        return data;
    },

    async transfer(id: number, payload: TransferPersonPayload): Promise<Entity> {
        const {data} = await api.post<Entity>(`/api/v1/entities/${id}/transfer/`, payload);
        return data;
    },

    async transferImpact(id: number): Promise<TransferImpact> {
        const {data} = await api.get<TransferImpact>(`/api/v1/entities/${id}/transfer-impact/`);
        return data;
    },

    async bulkMove(payload: BulkMovePayload): Promise<BulkOpResult> {
        return postBulkOp('/api/v1/entities/bulk-move/', payload);
    },

    async bulkDeactivate(payload: BulkDeactivatePayload): Promise<BulkOpResult> {
        return postBulkOp('/api/v1/entities/bulk-deactivate/', payload);
    },

    async bulkReactivate(payload: BulkReactivatePayload): Promise<BulkOpResult> {
        return postBulkOp('/api/v1/entities/bulk-reactivate/', payload);
    },

    async bulkImport(payload: BulkImportPayload | FormData): Promise<EntityBulkSubmitResult> {
        try {
            const resp = await api.post('/api/v1/entities/bulk/', payload);
            if (resp.status === 202) {
                return {async: true, job: resp.data as BulkJob};
            }
            return {async: false, result: resp.data as BulkImportResult};
        } catch (err) {

            if (
                axios.isAxiosError(err) &&
                err.response?.status === 422 &&
                (err.response.data as BulkImportResult | undefined)?.status === 'validation_failed'
            ) {
                return {async: false, result: err.response.data as BulkImportResult};
            }
            throw err;
        }
    },

    async search(q: string, type?: string): Promise<EntityListItem[]> {
        const {data} = await api.get<EntityListItem[]>('/api/v1/entities/search/', {
            params: {q, ...(type ? {type} : {})},
        });
        return data;
    },

    async export(params?: EntityListParams): Promise<Blob> {
        const {data} = await api.get('/api/v1/entities/export/', {
            params,
            responseType: 'blob',
        });
        return data as Blob;
    },

    async importTemplate(entityTypeCode: string): Promise<Blob> {
        const {data} = await api.get('/api/v1/entities/import-template/', {
            params: {entity_type: entityTypeCode},
            responseType: 'blob',
        });
        return data as Blob;
    },



    async listRelTypes(): Promise<PaginatedResponse<RelationshipType>> {
        const {data} = await api.get<PaginatedResponse<RelationshipType>>(
            '/api/v1/entities/relationship-types/',
        );
        return data;
    },

    async getRelationships(
        entityId: number,
        params?: RelationshipQueryParams,
    ): Promise<PaginatedResponse<EntityRelationship>> {
        const {data} = await api.get<PaginatedResponse<EntityRelationship>>(
            '/api/v1/entities/entity-relationships/',
            {params: {entity: entityId, ...params}},
        );
        return data;
    },

    async createRelationship(payload: CreateRelationshipPayload): Promise<EntityRelationship> {
        const {data} = await api.post<EntityRelationship>(
            '/api/v1/entities/entity-relationships/',
            payload,
        );
        return data;
    },

    async endRelationship(id: number): Promise<void> {
        await api.delete(`/api/v1/entities/entity-relationships/${id}/`);
    },


    //Channels

    async listChannels(): Promise<PaginatedResponse<Channel>> {
        const {data} = await api.get<PaginatedResponse<Channel>>('/api/v1/channels/');
        return data;
    },

    async createChannel(payload: CreateChannelPayload): Promise<Channel> {
        const {data} = await api.post<Channel>('/api/v1/channels/', payload);
        return data;
    },

    async updateChannel(id: number, payload: UpdateChannelPayload): Promise<Channel> {
        const {data} = await api.patch<Channel>(`/api/v1/channels/${id}/`, payload);
        return data;
    },

    async deactivateChannel(id: number): Promise<void> {
        await api.delete(`/api/v1/channels/${id}/`);
    },


    //Geography

    async listGeoTypes(): Promise<PaginatedResponse<GeographyType>> {
        const {data} = await api.get<PaginatedResponse<GeographyType>>('/api/v1/geography/types/');
        return data;
    },

    async createGeoType(payload: CreateGeographyTypePayload): Promise<GeographyType> {
        const {data} = await api.post<GeographyType>('/api/v1/geography/types/', payload);
        return data;
    },

    async listGeoNodes(params?: GeoNodeQueryParams): Promise<PaginatedResponse<GeographyNode>> {
        const {data} = await api.get<PaginatedResponse<GeographyNode>>('/api/v1/geography/nodes/', {
            params,
        });
        return data;
    },

    /** Root nodes for a geography type — the tree's initial load. */
    async geoTree(typeCode: string): Promise<GeographyNode[]> {
        const {data} = await api.get<PaginatedResponse<GeographyNode>>('/api/v1/geography/nodes/tree/', {
            params: {type: typeCode, page_size: 200},
        });
        return data.results;
    },

    /** Direct children of a node (lazy tree expansion). */
    async geoChildren(parentId: number): Promise<GeographyNode[]> {
        const {data} = await api.get<PaginatedResponse<GeographyNode>>('/api/v1/geography/nodes/', {
            params: {parent: parentId},
        });
        return data.results;
    },

    /** All descendants of a node (paginated server-side). */
    async geoSubtree(id: number): Promise<GeographyNode[]> {
        const {data} = await api.get<PaginatedResponse<GeographyNode>>(
            `/api/v1/geography/nodes/${id}/subtree/`,
        );
        return data.results;
    },

    async createGeoNode(payload: CreateGeographyNodePayload): Promise<GeographyNode> {
        const {data} = await api.post<GeographyNode>('/api/v1/geography/nodes/', payload);
        return data;
    },

    /** All-or-nothing territory CSV import. Returns a BulkJob to poll via /api/v1/jobs/{id}/. */
    async bulkImportGeoNodes(csvText: string): Promise<BulkJob> {
        const {data} = await api.post<BulkJob>('/api/v1/geography/nodes/bulk/', {
            format: 'csv', data: csvText, run_async: true,
        });
        return data;
    },

    async updateGeoNode(id: number, payload: UpdateGeographyNodePayload): Promise<GeographyNode> {
        const {data} = await api.patch<GeographyNode>(`/api/v1/geography/nodes/${id}/`, payload);
        return data;
    },

    async moveGeoNode(id: number, newParentId: number | null): Promise<GeographyNode> {
        const {data} = await api.post<GeographyNode>(`/api/v1/geography/nodes/${id}/move/`, {
            new_parent_id: newParentId,
        });
        return data;
    },

    async deactivateGeoNode(id: number): Promise<void> {
        await api.delete(`/api/v1/geography/nodes/${id}/`);
    },
};
