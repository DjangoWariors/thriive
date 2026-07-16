import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {masterService} from '../services/masterService';
import type {
    GroupPreviewPayload,
    SKUGroupPayload,
    SKUListParams,
    SKUPayload,
    UOMConversionPayload,
} from '../types/master';


export interface SKUGroupListParams {
    search?: string;
    page?: number;
    page_size?: number;
}

export interface UOMListParams {
    search?: string;
    sku_code?: string;
    page?: number;
}

const masterKeys = {
    skus: (params?: SKUListParams) => ['master', 'skus', params ?? {}] as const,
    facets: () => ['master', 'sku-facets'] as const,
    skuGroups: (params?: SKUGroupListParams) => ['master', 'sku-groups', params ?? {}] as const,
    groupSkus: (id: number) => ['master', 'sku-group-skus', id] as const,
    groupPreview: (payload: GroupPreviewPayload) => ['master', 'sku-group-preview', payload] as const,
    uom: (params?: UOMListParams) => ['master', 'uom-conversions', params ?? {}] as const,
};



export function useSKUs(params?: SKUListParams) {
    return useQuery({
        queryKey: masterKeys.skus(params),
        queryFn: () => masterService.listSKUs(params),
    });
}

export function useCreateSKU() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload: SKUPayload) => masterService.createSKU(payload),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'skus']}),
    });
}

export function useUpdateSKU() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({id, payload}: { id: number; payload: SKUPayload }) =>
            masterService.updateSKU(id, payload),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'skus']}),
    });
}

export function useDeactivateSKU() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => masterService.deactivateSKU(id),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'skus']}),
    });
}

export function useSKUFacets() {
    return useQuery({
        queryKey: masterKeys.facets(),
        queryFn: () => masterService.getSKUFacets(),
    });
}

export function useBulkImportSKUs() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({csvText, runAsync}: {csvText: string; runAsync?: boolean}) =>
            masterService.bulkImportSKUs(csvText, runAsync),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'skus']}),
    });
}



export function useSKUGroups(params?: SKUGroupListParams) {
    return useQuery({
        queryKey: masterKeys.skuGroups(params),
        queryFn: () => masterService.listSKUGroups(params),
    });
}

export function useCreateSKUGroup() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload: SKUGroupPayload) => masterService.createSKUGroup(payload),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'sku-groups']}),
    });
}

export function useUpdateSKUGroup() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({id, payload}: { id: number; payload: Partial<SKUGroupPayload> }) =>
            masterService.updateSKUGroup(id, payload),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'sku-groups']}),
    });
}

export function useDeactivateSKUGroup() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => masterService.deactivateSKUGroup(id),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'sku-groups']}),
    });
}

/** Backend-authoritative preview of an unsaved group. `enabled` gates the rule case. */
export function useGroupPreview(payload: GroupPreviewPayload, enabled: boolean) {
    return useQuery({
        queryKey: masterKeys.groupPreview(payload),
        queryFn: () => masterService.previewSKUGroup(payload),
        enabled,
        placeholderData: (prev) => prev,
    });
}



export function useUOMConversions(params?: UOMListParams) {
    return useQuery({
        queryKey: masterKeys.uom(params),
        queryFn: () => masterService.listUOMConversions(params),
    });
}

export function useCreateUOMConversion() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (payload: UOMConversionPayload) => masterService.createUOMConversion(payload),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'uom-conversions']}),
    });
}

export function useUpdateUOMConversion() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: ({id, payload}: {id: number; payload: Partial<UOMConversionPayload>}) =>
            masterService.updateUOMConversion(id, payload),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'uom-conversions']}),
    });
}

export function useDeactivateUOMConversion() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => masterService.deactivateUOMConversion(id),
        onSuccess: () => void qc.invalidateQueries({queryKey: ['master', 'uom-conversions']}),
    });
}
