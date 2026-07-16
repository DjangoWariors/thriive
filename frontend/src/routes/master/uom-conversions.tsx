import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus, Pencil, Trash2, Scale, Search } from 'lucide-react';
import {
  useUOMConversions,
  useCreateUOMConversion,
  useUpdateUOMConversion,
  useDeactivateUOMConversion,
} from '../../hooks/useMasterData';
import { useRBAC } from '../../hooks/useRBAC';
import type { UOMConversion, UOMConversionPayload } from '../../types/master';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
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

const uomSchema = z.object({
  sku_code: z.string(),
  from_uom: z.string().min(1, 'From unit is required'),
  to_uom: z.string().min(1, 'Base unit is required'),
  factor: z.string().regex(/^\d*\.?\d+$/, 'Factor must be a positive number'),
});

type UOMFormValues = z.infer<typeof uomSchema>;

export default function UOMConversionsPage() {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<UOMConversion | null>(null);
  const [deleting, setDeleting] = useState<UOMConversion | null>(null);

  const { canWrite } = useRBAC();
  const writable = canWrite('master_data');

  const { data: resp, isLoading } = useUOMConversions({ page, ...(search ? { search } : {}) });
  const deactivate = useDeactivateUOMConversion();
  const rows = resp?.results ?? [];

  const confirmDelete = () => {
    if (!deleting) return;
    deactivate.mutate(deleting.id, {
      onSuccess: () => {
        notify.success('Conversion removed');
        setDeleting(null);
      },
      onError: (e) => notify.error(apiErrorMessage(e, 'Could not remove conversion')),
    });
  };

  return (
    <div className="p-6">
      <PageHeader
          title="Unit Conversions"
          description="Normalise sold quantities into a base unit so volume KPIs sum across mixed packs (cases, inners, kg)."
          actions={<>{writable && (
          <Button
            icon={<Plus className="h-4 w-4" />}
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            Add Conversion
          </Button>
        )}</>}
      />

      <div className="mb-4 w-64">
        <Input
          placeholder="Search by SKU or unit…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          leftIcon={<Search className="h-4 w-4" />}
        />
      </div>

      {isLoading ? (
        <TableSkeleton/>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState icon={Scale} title="No conversions yet"
            description="Add a conversion, e.g. 1 case = 24 units, to normalise volume." />
        </Card>
      ) : (
        <Card padding="none">
          <SimpleTable
            rows={rows}
            rowKey={(c) => c.id}
            columns={[
              {header: 'Scope', render: (c) => (
                c.sku_code ? (
                  <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{c.sku_code}</code>
                ) : (
                  <Badge variant="info">Global</Badge>
                )
              )},
              {header: 'From', render: (c) => <span className="font-medium text-gray-900">{c.from_uom}</span>},
              {header: 'Base unit', render: (c) => <span className="text-gray-600">{c.to_uom}</span>},
              {header: 'Factor', align: 'right', render: (c) => (
                <span className="text-gray-700">1 {c.from_uom} = {Number(c.factor)} {c.to_uom}</span>
              )},
              ...(writable ? [{
                header: 'Actions', align: 'right' as const,
                render: (c: UOMConversion) => (
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="sm" aria-label={`Edit ${c.from_uom} conversion`}
                            onClick={() => { setEditing(c); setFormOpen(true); }}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="sm" aria-label={`Delete ${c.from_uom} conversion`}
                            onClick={() => setDeleting(c)}>
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
        title={editing ? 'Edit Conversion' : 'Add Conversion'}
        size="md"
      >
        <UOMForm existing={editing} onDone={() => setFormOpen(false)} />
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={confirmDelete}
        title="Remove conversion"
        message={`Remove the conversion for "${deleting?.from_uom ?? ''}"? Quantities in this unit will no longer be normalised.`}
        confirmLabel="Remove"
        variant="danger"
      />
    </div>
  );
}

function UOMForm({ existing, onDone }: { existing: UOMConversion | null; onDone: () => void }) {
  const create = useCreateUOMConversion();
  const update = useUpdateUOMConversion();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<UOMFormValues>({
    resolver: zodResolver(uomSchema),
    defaultValues: {
      sku_code: existing?.sku_code ?? '',
      from_uom: existing?.from_uom ?? '',
      to_uom: existing?.to_uom ?? '',
      factor: existing?.factor ?? '',
    },
  });

  const onSubmit = handleSubmit((values) => {
    setServerError(null);
    const payload: UOMConversionPayload = {
      sku_code: values.sku_code.trim(),
      from_uom: values.from_uom.trim(),
      to_uom: values.to_uom.trim(),
      factor: values.factor.trim(),
    };
    const onError = (e: unknown) => setServerError(apiErrorMessage(e, 'Could not save conversion'));

    if (existing) {
      update.mutate(
        { id: existing.id, payload: { to_uom: payload.to_uom, factor: payload.factor } },
        { onSuccess: () => { notify.success('Conversion updated'); onDone(); }, onError },
      );
    } else {
      create.mutate(payload, {
        onSuccess: () => { notify.success('Conversion created'); onDone(); },
        onError,
      });
    }
  });

  const pending = create.isPending || update.isPending;

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <Input
        label="SKU code"
        {...register('sku_code')}
        disabled={!!existing}
        hint={existing ? 'Scope cannot be changed.' : 'Leave blank for a global rule that applies to every SKU.'}
        placeholder="Blank = global"
      />
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="From unit"
          {...register('from_uom')}
          error={errors.from_uom?.message}
          disabled={!!existing}
          hint={existing ? 'Cannot be changed.' : undefined}
          placeholder="e.g. case"
        />
        <Input label="Base unit" {...register('to_uom')} error={errors.to_uom?.message} placeholder="e.g. unit" />
      </div>
      <Input
        label="Factor"
        {...register('factor')}
        error={errors.factor?.message}
        placeholder="e.g. 24 (1 case = 24 units)"
      />

      {serverError && <p className="text-sm text-danger">{serverError}</p>}

      <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
        <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
        <Button type="submit" loading={pending}>
          {existing ? 'Save changes' : 'Create conversion'}
        </Button>
      </div>
    </form>
  );
}
