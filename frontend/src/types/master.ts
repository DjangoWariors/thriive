import type { BulkJob } from './jobs';

export interface SKU {
  id: number;
  code: string;
  name: string;
  brand: string;
  category: string;
  sub_category: string;
  mrp: string | null;
  is_focus: boolean;
  is_npi: boolean;
  attributes: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SKUPayload {
  code: string;
  name: string;
  brand?: string;
  category?: string;
  sub_category?: string;
  mrp?: string | null;
  is_focus?: boolean;
  is_npi?: boolean;
}

export type SKUFilterType = 'explicit' | 'rule';

export interface SKURuleFilters {
  brand?: string;
  category?: string;
  sub_category?: string;
  is_focus?: boolean;
  is_npi?: boolean;
  /** Filter on arbitrary SKU Master attributes, e.g. { pack_size: 'large' }. */
  attributes?: Record<string, string>;
}

export interface SKUGroup {
  id: number;
  name: string;
  code: string;
  filter_type: SKUFilterType;
  filter_rules: SKURuleFilters;
  skus: number[];
  resolved_sku_count: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SKUGroupPayload {
  name: string;
  code: string;
  filter_type: SKUFilterType;
  filter_rules?: SKURuleFilters;
  skus?: number[];
}

export interface SKUListParams {
  search?: string;
  brand?: string;
  category?: string;
  is_focus?: boolean;
  page?: number;
  page_size?: number;
}

export interface BulkImportResult {
  status: 'success' | 'validation_failed';
  created: number;
  updated: number;
  errors: { row: number; error: string }[];
}

/** Bulk import either completes synchronously or returns a job to poll (large files). */
export type SKUBulkSubmitResult =
  | { async: false; result: BulkImportResult }
  | { async: true; job: BulkJob };

/** Distinct values across all active SKUs — for filter dropdowns (not page-limited). */
export interface SKUFacets {
  brands: string[];
  categories: string[];
}

/** Backend-authoritative resolution of an unsaved group definition. */
export interface GroupPreviewResult {
  count: number;
  sample: SKU[];
}

export interface GroupPreviewPayload {
  filter_type: SKUFilterType;
  filter_rules?: SKURuleFilters;
  skus?: number[];
}

export interface UOMConversion {
  id: number;
  sku_code: string;
  from_uom: string;
  to_uom: string;
  factor: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface UOMConversionPayload {
  sku_code?: string;
  from_uom: string;
  to_uom: string;
  factor: string;
}
