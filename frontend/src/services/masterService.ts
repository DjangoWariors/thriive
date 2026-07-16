import axios from 'axios';
import api from './api';
import type { PaginatedResponse } from '../types/api';
import type { BulkJob } from '../types/jobs';
import type {
  BulkImportResult,
  GroupPreviewPayload,
  GroupPreviewResult,
  SKU,
  SKUBulkSubmitResult,
  SKUFacets,
  SKUGroup,
  SKUGroupPayload,
  SKUListParams,
  SKUPayload,
  UOMConversion,
  UOMConversionPayload,
} from '../types/master';

export const masterService = {

  async listSKUs(params?: SKUListParams): Promise<PaginatedResponse<SKU>> {
    const { data } = await api.get<PaginatedResponse<SKU>>('/api/v1/master/skus/', { params });
    return data;
  },

  async createSKU(payload: SKUPayload): Promise<SKU> {
    const { data } = await api.post<SKU>('/api/v1/master/skus/', payload);
    return data;
  },

  async updateSKU(id: number, payload: SKUPayload): Promise<SKU> {
    const { data } = await api.patch<SKU>(`/api/v1/master/skus/${id}/`, payload);
    return data;
  },

  async deactivateSKU(id: number): Promise<void> {
    await api.delete(`/api/v1/master/skus/${id}/`);
  },

  async getSKUFacets(): Promise<SKUFacets> {
    const { data } = await api.get<SKUFacets>('/api/v1/master/skus/facets/');
    return data;
  },

  async bulkImportSKUs(csvText: string, runAsync = false): Promise<SKUBulkSubmitResult> {
    try {
      const resp = await api.post('/api/v1/master/skus/bulk/', { data: csvText, run_async: runAsync });
      if (resp.status === 202) {
        return { async: true, job: resp.data as BulkJob };
      }
      return { async: false, result: resp.data as BulkImportResult };
    } catch (err) {
      // A validation failure (422) is an expected outcome, not a transport error.
      if (
        axios.isAxiosError(err) &&
        err.response?.status === 422 &&
        (err.response.data as BulkImportResult | undefined)?.status === 'validation_failed'
      ) {
        return { async: false, result: err.response.data as BulkImportResult };
      }
      throw err;
    }
  },


  async listSKUGroups(params?: { search?: string; page?: number }): Promise<PaginatedResponse<SKUGroup>> {
    const { data } = await api.get<PaginatedResponse<SKUGroup>>('/api/v1/master/sku-groups/', {
      params,
    });
    return data;
  },

  async createSKUGroup(payload: SKUGroupPayload): Promise<SKUGroup> {
    const { data } = await api.post<SKUGroup>('/api/v1/master/sku-groups/', payload);
    return data;
  },

  async updateSKUGroup(id: number, payload: Partial<SKUGroupPayload>): Promise<SKUGroup> {
    const { data } = await api.patch<SKUGroup>(`/api/v1/master/sku-groups/${id}/`, payload);
    return data;
  },

  async deactivateSKUGroup(id: number): Promise<void> {
    await api.delete(`/api/v1/master/sku-groups/${id}/`);
  },

  async getSKUGroupSKUs(id: number): Promise<SKU[]> {
    const { data } = await api.get<SKU[]>(`/api/v1/master/sku-groups/${id}/skus/`);
    return data;
  },

  async previewSKUGroup(payload: GroupPreviewPayload): Promise<GroupPreviewResult> {
    const { data } = await api.post<GroupPreviewResult>('/api/v1/master/sku-groups/preview/', payload);
    return data;
  },


  async listUOMConversions(params?: { search?: string; sku_code?: string; page?: number }): Promise<PaginatedResponse<UOMConversion>> {
    const { data } = await api.get<PaginatedResponse<UOMConversion>>('/api/v1/master/uom-conversions/', { params });
    return data;
  },

  async createUOMConversion(payload: UOMConversionPayload): Promise<UOMConversion> {
    const { data } = await api.post<UOMConversion>('/api/v1/master/uom-conversions/', payload);
    return data;
  },

  async updateUOMConversion(id: number, payload: Partial<UOMConversionPayload>): Promise<UOMConversion> {
    const { data } = await api.patch<UOMConversion>(`/api/v1/master/uom-conversions/${id}/`, payload);
    return data;
  },

  async deactivateUOMConversion(id: number): Promise<void> {
    await api.delete(`/api/v1/master/uom-conversions/${id}/`);
  },
};
