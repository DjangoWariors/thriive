import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { useForm, useFieldArray, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus, Pencil, Trash2, Layers, Search } from 'lucide-react';
import {
  useSKUGroups,
  useCreateSKUGroup,
  useUpdateSKUGroup,
  useDeactivateSKUGroup,
  useSKUs,
  useSKUFacets,
  useGroupPreview,
} from '../../hooks/useMasterData';
import { useRBAC } from '../../hooks/useRBAC';
import type { SKU, SKUGroup, SKUGroupPayload, SKURuleFilters, GroupPreviewPayload } from '../../types/master';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Modal } from '../../components/ui/Modal';
import { EmptyState } from '../../components/ui/EmptyState';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { Pagination } from '../../components/ui/Pagination';
import {PageHeader} from '../../components/ui/PageHeader';
import { SimpleTable } from '../../components/ui/SimpleTable';
import {TableSkeleton} from '../../components/ui/Skeleton';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

const groupSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  code: z.string().min(1, 'Code is required'),
  filter_type: z.enum(['explicit', 'rule']),
  filter_rules: z.object({
    brand: z.string().optional(),
    category: z.string().optional(),
    sub_category: z.string().optional(),
    is_focus: z.boolean().optional(),
    is_npi: z.boolean().optional(),
  }),
  attributes: z.array(z.object({ key: z.string(), value: z.string() })),
  skus: z.array(z.number()),
});

type GroupFormValues = z.infer<typeof groupSchema>;

/** Build the filter_rules object from form values, dropping empty entries. */
function buildRuleFilters(values: GroupFormValues): SKURuleFilters {
  const fr: SKURuleFilters = {};
  const r = values.filter_rules;
  if (r.brand) fr.brand = r.brand;
  if (r.category) fr.category = r.category;
  if (r.sub_category?.trim()) fr.sub_category = r.sub_category.trim();
  if (r.is_focus) fr.is_focus = true;
  if (r.is_npi) fr.is_npi = true;
  const attrs: Record<string, string> = {};
  for (const row of values.attributes) {
    if (row.key.trim() && row.value.trim()) attrs[row.key.trim()] = row.value.trim();
  }
  if (Object.keys(attrs).length) fr.attributes = attrs;
  return fr;
}

export default function SKUGroupsPage() {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<SKUGroup | null>(null);
  const [deleting, setDeleting] = useState<SKUGroup | null>(null);

  const { canWrite } = useRBAC();
  const writable = canWrite('master_data');

  // Allow deep-linking straight to the create form (e.g. the KPI builder shortcut).
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    if (writable && searchParams.get('create') === '1') {
      setEditing(null);
      setFormOpen(true);
      searchParams.delete('create');
      setSearchParams(searchParams, { replace: true });
    }
  }, [writable, searchParams, setSearchParams]);

  const { data: resp, isLoading } = useSKUGroups({ page, ...(search ? { search } : {}) });
  const deactivate = useDeactivateSKUGroup();
  const groups = resp?.results ?? [];

  const confirmDelete = () => {
    if (!deleting) return;
    deactivate.mutate(deleting.id, {
      onSuccess: () => {
        notify.success(`Group "${deleting.code}" deactivated`);
        setDeleting(null);
      },
      onError: (e) => notify.error(apiErrorMessage(e, 'Could not deactivate group')),
    });
  };

  return (
    <div className="p-6">
      <PageHeader
          title="SKU Groups"
          description="Bundle products into reusable groups — a fixed list or a live rule."
          actions={<>{writable && (
          <Button
            icon={<Plus className="h-4 w-4" />}
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            Create Group
          </Button>
        )}</>}
      />

      <div className="mb-4 w-64">
        <Input
          placeholder="Search by code or name…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          leftIcon={<Search className="h-4 w-4" />}
        />
      </div>

      {isLoading ? (
        <TableSkeleton/>
      ) : groups.length === 0 ? (
        <Card>
          <EmptyState icon={Layers} title="No SKU groups yet" description="Create a group to bundle products together." />
        </Card>
      ) : (
        <Card padding="none">
          <SimpleTable
            rows={groups}
            rowKey={(g) => g.id}
            columns={[
              {header: 'Code', render: (g) => (
                <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{g.code}</code>
              )},
              {header: 'Name', render: (g) => <span className="font-medium text-gray-900">{g.name}</span>},
              {header: 'Type', render: (g) => (
                <Badge variant={g.filter_type === 'rule' ? 'purple' : 'info'}>
                  {g.filter_type === 'rule' ? 'Rule' : 'Fixed list'}
                </Badge>
              )},
              {header: 'Products', align: 'right', render: (g) => (
                <span className="font-medium text-gray-700">{g.resolved_sku_count}</span>
              )},
              ...(writable ? [{
                header: 'Actions', align: 'right' as const,
                render: (g: SKUGroup) => (
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Edit ${g.code}`}
                      onClick={() => {
                        setEditing(g);
                        setFormOpen(true);
                      }}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="sm" aria-label={`Deactivate ${g.code}`}
                            onClick={() => setDeleting(g)}>
                      <Trash2 className="h-4 w-4 text-danger" />
                    </Button>
                  </div>
                ),
              }] : []),
            ]}
          />
          <Pagination count={resp?.count ?? 0} page={page} onPageChange={setPage} />
        </Card>
      )}

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? `Edit ${editing.code}` : 'Create SKU Group'}
        size="xl"
      >
        <GroupForm existing={editing} onDone={() => setFormOpen(false)} />
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={confirmDelete}
        title="Deactivate group"
        message={`Deactivate group "${deleting?.name ?? ''}"? It will be hidden from active lists.`}
        confirmLabel="Deactivate"
        variant="danger"
      />
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════════
// Group create / edit form
// ════════════════════════════════════════════════════════════════════════════════

function GroupForm({ existing, onDone }: { existing: SKUGroup | null; onDone: () => void }) {
  const create = useCreateSKUGroup();
  const update = useUpdateSKUGroup();
  const [serverError, setServerError] = useState<string | null>(null);
  const [skuSearch, setSkuSearch] = useState('');

  // Brand/category options come from the facets endpoint (all SKUs, not page-limited).
  const { data: facets } = useSKUFacets();
  const brandOptions = facets?.brands ?? [];
  const categoryOptions = facets?.categories ?? [];

  // Picker is search-backed: query the API as the user types instead of capping at a flat list.
  const { data: skuResp } = useSKUs({ ...(skuSearch.trim() ? { search: skuSearch.trim() } : {}), page_size: 50 });
  const visibleSKUs = useMemo(() => skuResp?.results ?? [], [skuResp]);

  const {
    register,
    handleSubmit,
    control,
    watch,
    formState: { errors },
  } = useForm<GroupFormValues>({
    resolver: zodResolver(groupSchema),
    defaultValues: {
      name: existing?.name ?? '',
      code: existing?.code ?? '',
      filter_type: existing?.filter_type ?? 'explicit',
      filter_rules: {
        brand: existing?.filter_rules?.brand ?? '',
        category: existing?.filter_rules?.category ?? '',
        sub_category: existing?.filter_rules?.sub_category ?? '',
        is_focus: existing?.filter_rules?.is_focus ?? false,
        is_npi: existing?.filter_rules?.is_npi ?? false,
      },
      attributes: Object.entries(existing?.filter_rules?.attributes ?? {}).map(
        ([key, value]) => ({ key, value: String(value) }),
      ),
      skus: existing?.skus ?? [],
    },
  });

  const { fields: attrFields, append: appendAttr, remove: removeAttr } = useFieldArray({
    control,
    name: 'attributes',
  });

  const filterType = watch('filter_type');
  const selectedSkus = watch('skus');
  const formValues = watch();

  // Live preview is backend-authoritative for rules so it can never diverge from get_skus().
  const previewPayload = useMemo<GroupPreviewPayload>(
    () => ({ filter_type: 'rule', filter_rules: buildRuleFilters(formValues) }),
    [formValues],
  );
  const { data: rulePreview, isFetching: previewLoading } = useGroupPreview(
    previewPayload,
    filterType === 'rule',
  );
  const previewCount = filterType === 'explicit' ? selectedSkus.length : rulePreview?.count;

  const onSubmit = handleSubmit((values) => {
    setServerError(null);
    const payload: SKUGroupPayload = {
      name: values.name.trim(),
      code: values.code.trim(),
      filter_type: values.filter_type,
    };
    if (values.filter_type === 'rule') {
      payload.filter_rules = buildRuleFilters(values);
      payload.skus = [];
    } else {
      payload.skus = values.skus;
      payload.filter_rules = {};
    }

    const onError = (e: unknown) => setServerError(apiErrorMessage(e, 'Could not save group'));
    if (existing) {
      update.mutate(
        { id: existing.id, payload },
        { onSuccess: () => { notify.success('Group updated'); onDone(); }, onError },
      );
    } else {
      create.mutate(payload, {
        onSuccess: () => { notify.success('Group created'); onDone(); },
        onError,
      });
    }
  });

  const pending = create.isPending || update.isPending;

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <Input label="Name" {...register('name')} error={errors.name?.message} placeholder="e.g. Focus SKUs" />
        <Input
          label="Code"
          {...register('code')}
          error={errors.code?.message}
          placeholder="e.g. focus_skus"
          disabled={!!existing}
          hint={existing ? 'Code cannot be changed.' : undefined}
        />
      </div>

      {/* Filter type toggle */}
      <Controller
        control={control}
        name="filter_type"
        render={({ field }) => (
          <div>
            <p className="mb-2 text-sm font-medium text-gray-700">How is this group defined?</p>
            <div className="grid grid-cols-2 gap-3">
              {([
                { v: 'explicit', t: 'Fixed list', d: 'Hand-pick specific products.' },
                { v: 'rule', t: 'Rule', d: 'Auto-include products matching criteria.' },
              ] as const).map((opt) => (
                <button
                  type="button"
                  key={opt.v}
                  onClick={() => field.onChange(opt.v)}
                  className={
                    'rounded-lg border px-3 py-2 text-left text-sm transition-colors ' +
                    (field.value === opt.v
                      ? 'border-primary bg-primary-50 text-primary'
                      : 'border-gray-200 hover:border-primary')
                  }
                >
                  <span className="block font-medium">{opt.t}</span>
                  <span className="block text-xs text-gray-500">{opt.d}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      />

      {/* Explicit: SKU multi-select */}
      {filterType === 'explicit' && (
        <Controller
          control={control}
          name="skus"
          render={({ field }) => (
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">Pick products</p>
              <Input
                placeholder="Search products…"
                value={skuSearch}
                onChange={(e) => setSkuSearch(e.target.value)}
                leftIcon={<Search className="h-4 w-4" />}
              />
              <div className="mt-2 max-h-60 overflow-y-auto rounded-lg border border-gray-200 divide-y divide-gray-100">
                {visibleSKUs.length === 0 ? (
                  <p className="px-3 py-4 text-center text-xs text-gray-400">No products match.</p>
                ) : (
                  visibleSKUs.map((s: SKU) => {
                    const checked = field.value.includes(s.id);
                    return (
                      <label key={s.id} className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            field.onChange(
                              checked ? field.value.filter((id) => id !== s.id) : [...field.value, s.id],
                            )
                          }
                          className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                        />
                        <code className="rounded bg-gray-100 px-1 text-xs">{s.code}</code>
                        <span className="text-gray-700">{s.name}</span>
                      </label>
                    );
                  })
                )}
              </div>
            </div>
          )}
        />
      )}

      {/* Rule: filter builder */}
      {filterType === 'rule' && (
        <div className="space-y-3 rounded-lg bg-gray-50 p-4">
          <p className="text-sm font-medium text-gray-700">Include products where…</p>
          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Brand"
              {...register('filter_rules.brand')}
              options={[{ value: '', label: 'Any brand' }, ...brandOptions.map((b) => ({ value: b, label: b }))]}
            />
            <Select
              label="Category"
              {...register('filter_rules.category')}
              options={[{ value: '', label: 'Any category' }, ...categoryOptions.map((c) => ({ value: c, label: c }))]}
            />
            <Input label="Sub-category" {...register('filter_rules.sub_category')} placeholder="Any sub-category" />
          </div>
          <div className="flex gap-6">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" {...register('filter_rules.is_focus')} className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary" />
              Focus products only
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" {...register('filter_rules.is_npi')} className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary" />
              New products (NPI) only
            </label>
          </div>
          <div className="border-t border-gray-200 pt-3 hidden">
            <div className="mb-1 flex items-center justify-between">
              <p className="text-sm font-medium text-gray-700">Custom attributes</p>
              <button
                type="button"
                onClick={() => appendAttr({ key: '', value: '' })}
                className="flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <Plus className="h-3.5 w-3.5" /> Add attribute
              </button>
            </div>
            {attrFields.length === 0 ? (
              <p className="text-xs text-gray-400">No attribute filters. Add one to match a custom field from the SKU Master.</p>
            ) : (
              <div className="space-y-2">
                {attrFields.map((row, i) => (
                  <div key={row.id} className="flex items-end gap-2">
                    <div className="flex-1">
                      <Input label={i === 0 ? 'Attribute key' : undefined} {...register(`attributes.${i}.key`)} placeholder="e.g. pack_size" />
                    </div>
                    <div className="flex-1">
                      <Input label={i === 0 ? 'Value' : undefined} {...register(`attributes.${i}.value`)} placeholder="e.g. large" />
                    </div>
                    <Button type="button" variant="ghost" size="sm" onClick={() => removeAttr(i)}>
                      <Trash2 className="h-4 w-4 text-danger" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
            <p className="mt-1 text-xs text-gray-400">All filters above combine with AND. Blank rows are ignored.</p>
          </div>
        </div>
      )}

      {/* Live preview */}
      <div className="flex items-center justify-between rounded-lg border border-blue-100 bg-blue-50 px-4 py-2.5 text-sm">
        <span className="text-blue-800">This group currently resolves to</span>
        <span className="font-semibold text-blue-900">
          {previewCount === undefined ? (previewLoading ? '…' : '—') : `${previewCount} product(s)`}
        </span>
      </div>

      {serverError && <p className="text-sm text-danger">{serverError}</p>}

      <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={pending}>
          {existing ? 'Save changes' : 'Create group'}
        </Button>
      </div>
    </form>
  );
}
