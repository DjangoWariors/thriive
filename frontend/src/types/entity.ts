import type { BulkJob } from './jobs';


export interface AttributeField {
  key: string;
  label: string;
  type: 'string' | 'integer' | 'decimal' | 'date' | 'boolean' | 'choice' | 'email' | 'phone';
  required: boolean;
  unique: boolean;
  options?: string[];
  min?: number;
  max?: number;
  pattern?: string;
  encrypted?: boolean;
}


export interface DisplayConfig {
  icon?: string;
  color?: string;
  show_in_tree?: boolean;
  portal_type?: 'admin' | 'partner';
  login_method?: 'password_and_otp' | 'otp_only' | 'password_only';
  card_fields?: string[];
}


export interface Channel {
  id: number;
  name: string;
  code: string;
  description: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

/** Compact channel shape embedded in entity / entity-type responses. */
export interface ChannelRef {
  id: number;
  code: string;
  name: string;
}

/** A territory the entity currently owns (open owner assignment). */
export interface OwnedScope {
  id: number;
  name: string;
  code: string;
  level: string;
  since: string;
}


export interface EntityType {
  id: number;
  name: string;
  code: string;
  description: string;
  level_order: number;
  allowed_parent_types: string[];
  allowed_child_types: string[];
  attribute_schema: AttributeField[];
  is_loginable: boolean;
  incentive_eligible: boolean;
  is_leaf: boolean;
  is_root_type: boolean;
  default_role: number | null;
  channel: ChannelRef | null;
  /** Write-only: set the channel by id (the API returns `channel` as a nested object). */
  channel_id?: number | null;
  display_config: DisplayConfig;
  version: number;
  effective_from: string;
  effective_to: string | null;
  is_current: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}



export type EntityStatus = 'active' | 'inactive' | 'suspended' | 'onboarding' | 'vacant';


export interface EntityListItem {
  id: number;
  name: string;
  code: string;
  entity_type_code: string | null;
  entity_type_name: string | null;
  parent: number | null;
  parent_name: string | null;
  status: EntityStatus;
  channel: ChannelRef | null;
  depth: number;
  path: string;
  is_current: boolean;
  version: number;
  is_active: boolean;
}


export interface LinkedUser {
  id: number;
  email: string | null;
  mobile: string | null;
  is_active: boolean;
}

/** Subtree row: a flat entity plus its linked user (if the type is loginable). */
export interface EntitySubtreeItem extends EntityListItem {
  linked_user: LinkedUser | null;
}

export interface ParentInfo {
  id: number;
  name: string;
  code: string;
  type: string | null;
}


export interface Entity {
  id: number;
  name: string;
  code: string;
  /** Computed role+geography label (e.g. "ASM-DL") from the primary owned territory
   *  (via assignments) — updates automatically on transfer, unlike the immutable `code`. */
  display_code: string;
  entity_type: EntityType;
  parent: number | null;
  parent_info: ParentInfo | null;
  attributes: Record<string, unknown>;
  channel: ChannelRef | null;
  /** Territories this entity currently owns, resolved through the Assignment bridge. */
  owned_scopes: OwnedScope[];
  path: string;
  depth: number;
  status: EntityStatus;
  linked_user: LinkedUser | null;
  children_count: number;
  version: number;
  effective_from: string;
  effective_to: string | null;
  is_current: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}


export interface RelationshipType {
  id: number;
  name: string;
  code: string;
  from_entity_type: number;
  to_entity_type: number;
  allows_multiple: boolean;
  is_active: boolean;
}


export interface EntityRelationship {
  id: number;
  relationship_type: number;
  type_name: string;
  from_entity: number;
  from_entity_name: string;
  to_entity: number;
  to_entity_name: string;
  effective_from: string;
  effective_to: string | null;
  is_active: boolean;
}


export interface GeographyType {
  id: number;
  name: string;
  code: string;
  levels: string[];
  is_active: boolean;
}

/** Compact geography-type shape embedded in node responses. */
export interface GeographyTypeRef {
  id: number;
  code: string;
  name: string;
  levels: string[];
}

export interface GeographyNode {
  id: number;
  geography_type: GeographyTypeRef;
  name: string;
  code: string;
  level: string;
  parent: number | null;
  parent_name: string | null;
  children_count: number;
  path: string;
  depth: number;
  is_active: boolean;
}

export interface CreateGeographyTypePayload {
  name: string;
  code: string;
  levels: string[];
}

export interface CreateGeographyNodePayload {
  geography_type_id: number;
  name: string;
  code: string;
  level: string;
  parent?: number | null;
}

export type UpdateGeographyNodePayload = Partial<CreateGeographyNodePayload>;

export interface CreateChannelPayload {
  name: string;
  code: string;
  description?: string;
}

export type UpdateChannelPayload = Partial<CreateChannelPayload>;


export interface EntityListParams {
  type?: string;
  channel?: string;
  geography?: string;
  status?: string;
  parent?: number;
  root?: boolean;
  ordering?: string;
  page?: number;
  page_size?: number;
}

export interface CreateEntityPayload {
  entity_type_id: number;
  name: string;
  code: string;
  parent_id?: number | null;
  attributes?: Record<string, unknown>;
  channel_id?: number | null;
  /** Territories the entity will own from day one (opens owner assignments). */
  owned_scope_ids?: number[];
  email?: string | null;
  mobile?: string | null;
  employee_id?: string | null;
  /** Initial password for the auto-created login; on update, blank keeps the current one. */
  password?: string;
  effective_from?: string;
  status?: string;
}

export type UpdateEntityPayload = Partial<CreateEntityPayload>;

export interface MoveEntityPayload {
  new_parent_id: number;
  reason: string;
  effective_date: string;
}

export interface BulkMovePayload {
  entity_ids: number[];
  new_parent_id: number;
  reason: string;
  effective_date: string;
}

/**
 * Transfer a person AND settle their territories in one atomic call. Reports are
 * promoted to the departing entity's parent (or `reassign_reports_to`); the person
 * lands in a new seat (`new_parent_id`) or an existing vacant seat
 * (`target_entity_id`); their owned territories follow `territory_handover`.
 * Distinct from a structural move.
 */
export interface TransferPersonPayload {
  mode: 'new_seat' | 'occupy_vacant';
  reason: string;
  effective_date: string;
  new_parent_id?: number;
  target_entity_id?: number;
  territory_handover: 'successor' | 'release' | 'keep';
  successor_id?: number | null;
  reassign_reports_to?: number | null;
}

/** Read-only preview of what a transfer would touch (GET .../transfer-impact/). */
export interface TransferImpact {
  entity: { id: number; name: string; code: string; type: string | null; status: string };
  current_parent: { id: number; name: string; code: string } | null;
  owned_territories: {
    assignment_id: number; scope_id: number; name: string;
    code: string; level: string; since: string;
  }[];
  direct_reports: { id: number; name: string; code: string; type: string | null }[];
}

export interface BulkDeactivatePayload {
  entity_ids: number[];
  reason: string;
  cascade: boolean;
}

export interface BulkReactivatePayload {
  entity_ids: number[];
  reason?: string;
}

export interface ChangeTypePayload {
  new_type_id: number;
  new_parent_id?: number | null;
  attributes?: Record<string, unknown>;
  reason: string;
  effective_date?: string;
  reassign_reports_to?: number | null;
}


export interface BulkOpResult {
  status: 'success' | 'validation_failed';
  moved?: number;
  deactivated?: number;
  reactivated?: number;
  errors?: Array<{ id: number; errors: string[] }>;
}

export interface BulkImportPayload {
  format: 'csv' | 'json';
  data?: string;
  dry_run?: boolean;
  run_async?: boolean;
}

export interface BulkImportResult {
  status: 'success' | 'valid' | 'validation_failed' | 'processing';
  created?: number;
  users_created?: number;
  rows?: number;
  would_create?: number;
  would_create_users?: number;
  task_id?: string;
  errors?: Array<{ row: number; errors: string[] }>;
}


export type EntityBulkSubmitResult =
  | { async: true; job: BulkJob }
  | { async: false; result: BulkImportResult };

export interface CreateRelationshipPayload {
  relationship_type: number;
  from_entity: number;
  to_entity: number;
  effective_from: string;
  effective_to?: string | null;
}

export interface RelationshipQueryParams {
  type?: string;
  direction?: 'from' | 'to' | 'both';
}

export interface GeoNodeQueryParams {
  type?: string;
  level?: string;
  /** CSV of level names — level-constrained pickers. */
  levels?: string;
  parent?: number;
  q?: string;
  page_size?: number;
}
