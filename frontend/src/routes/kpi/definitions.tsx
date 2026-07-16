import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { Plus, Pencil, Trash2, Search, Target, Upload, Copy } from 'lucide-react';
import { useKpiDefinitions, useDeactivateKpi, useKpiBlueprint } from '../../hooks/useKpi';
import { useRBAC } from '../../hooks/useRBAC';
import type { KPIDefinitionListItem, KpiType } from '../../types/kpi';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { EmptyState } from '../../components/ui/EmptyState';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { Pagination } from '../../components/ui/Pagination';
import { InfoTooltip } from '../../components/ui/InfoTooltip';
import { PageHeader } from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import { KpiDetailDrawer } from '../../components/kpi/KpiDetailDrawer';
import { kpiFormula } from './kpiFormula';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

const TYPE_META: Record<KpiType, { label: string; variant: 'default' | 'success' | 'info' | 'warning' | 'purple' | 'danger' }> = {
  value: { label: 'Total amount', variant: 'info' },
  count: { label: 'Count', variant: 'default' },
  count_distinct: { label: 'Unique count', variant: 'default' },
  ratio: { label: 'Ratio', variant: 'purple' },
  growth: { label: 'Growth', variant: 'success' },
  composite: { label: 'Blended', variant: 'warning' },
  boolean: { label: 'Met / not-met', variant: 'danger' },
  external: { label: 'External feed', variant: 'info' },
};

const TYPE_OPTIONS = [
  { value: '', label: 'All' },
  ...Object.entries(TYPE_META).map(([value, m]) => ({ value, label: m.label })),
];

export default function KpiDefinitionsPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [kpiType, setKpiType] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const [deleting, setDeleting] = useState<{ id: number; code: string; name: string } | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  const params = useMemo(
    () => ({
      page,
      ...(search ? { search } : {}),
      ...(kpiType ? { kpi_type: kpiType as KpiType } : {}),
      ...(category ? { category } : {}),
    }),
    [page, search, kpiType, category],
  );

  const { canWrite } = useRBAC();
  const writable = canWrite('kpi_definitions');
  const { data: resp, isLoading } = useKpiDefinitions(params);
  const { data: blueprint } = useKpiBlueprint();
  const deactivate = useDeactivateKpi();
  const kpis = resp?.results ?? [];

  const categoryOptions = useMemo(() => {
    const groups = Array.from(new Set((blueprint ?? []).map((k) => k.category).filter(Boolean))).sort();
    return [{ value: '', label: 'All groups' }, ...groups.map((g) => ({ value: g, label: g }))];
  }, [blueprint]);

  const confirmDelete = () => {
    if (!deleting) return;
    deactivate.mutate(deleting.id, {
      onSuccess: () => {
        notify.success(`KPI “${deleting.name}” retired.`);
        setDeleting(null);
      },
      onError: (e) => notify.error(apiErrorMessage(e, 'Failed to retire KPI.')),
    });
  };

  return (
    <div className="p-6">
      <PageHeader
        title="KPIs"
        description="Metrics used by targets, scorecards and payouts. A KPI returns 0 until matching data exists."
        actions={
          writable && (
            <>
              <Button variant="outline" icon={<Upload className="h-4 w-4" />} onClick={() => navigate('/kpi/transactions')}>
                Sales data
              </Button>
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => navigate('/kpi/builder')}>
                New KPI
              </Button>
            </>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-64">
          <Input
            placeholder="Search KPIs by name or code…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            leftIcon={<Search className="h-4 w-4" />}
          />
        </div>
        <div className="w-48">
          <Select
            value={kpiType}
            onChange={(e) => {
              setKpiType(e.target.value);
              setPage(1);
            }}
            options={TYPE_OPTIONS}
          />
        </div>
        <div className="w-48">
          <Select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              setPage(1);
            }}
            options={categoryOptions}
          />
        </div>
      </div>

      {isLoading ? (
        <TableSkeleton/>
      ) : kpis.length === 0 ? (
        <Card>
          <EmptyState icon={Target} title="No KPIs defined" description="Create a KPI to begin measuring performance." />
        </Card>
      ) : (
        <Card padding="none">
          <SimpleTable
            rows={kpis}
            rowKey={(k) => k.id}
            onRowClick={(k) => setOpenId(k.id)}
            columns={[
              {header: 'Code', render: (k) => (
                <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{k.code}</code>
              )},
              {header: 'Name', render: (k) => <span className="font-medium text-primary hover:underline">{k.name}</span>},
              {header: (
                <span className="inline-flex items-center gap-1.5">
                  Type
                  <InfoTooltip content="The shape of the calculation: total value, transaction count, unique (distinct) count, ratio (value per value), growth vs a prior period, composite (weighted KPIs), a met/not-met flag, or an external metric feed." />
                </span>
              ), render: (k) => (
                <Badge variant={TYPE_META[k.kpi_type].variant}>{TYPE_META[k.kpi_type].label}</Badge>
              )},
              {header: (
                <span className="inline-flex items-center gap-1.5">
                  Formula
                  <InfoTooltip content="A compact view of the calculation, e.g. SUM(NSV) ÷ COUNT(DISTINCT bills). NSV = sales net of returns; a · suffix shows the channel or product scope." />
                </span>
              ), render: (k) => (
                <code className="rounded bg-gray-50 px-1.5 py-0.5 text-xs text-gray-700">{kpiFormula(k)}</code>
              )},
              {header: 'Category', render: (k) => <span className="text-gray-600">{k.category || '—'}</span>},
              {header: 'Unit', render: (k) => <span className="text-gray-600">{k.unit || '—'}</span>},
              {header: (
                <span className="inline-flex items-center gap-1.5">
                  Scope
                  <InfoTooltip content="Roles and channels this KPI is scoped to. 'All' = no restriction." />
                </span>
              ), render: (k) => (
                <span className="text-gray-500">
                  {k.applicable_entity_types.length ? k.applicable_entity_types.join(', ') : 'All'}
                  {k.channel_filter.length ? ` · ${k.channel_filter.join(', ')}` : ''}
                </span>
              )},
              {header: (
                <span className="inline-flex items-center gap-1.5">
                  Version
                  <InfoTooltip content="Increments on each edit. Prior versions are retained so historical targets, achievements and payouts stay reproducible." />
                </span>
              ), align: 'center', render: (k) => <span className="text-gray-500">v{k.version}</span>},
              ...(writable ? [{
                header: 'Actions', align: 'right' as const,
                render: (k: KPIDefinitionListItem) => (
                  <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                    <Button variant="ghost" size="sm" aria-label={`Edit ${k.code}`} onClick={() => navigate(`/kpi/builder/${k.id}`)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="sm" aria-label={`Duplicate ${k.code}`} onClick={() => navigate(`/kpi/builder?clone=${k.id}`)}>
                      <Copy className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="sm" aria-label={`Retire ${k.code}`} onClick={() => setDeleting(k)}>
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

      <KpiDetailDrawer
        id={openId}
        onClose={() => setOpenId(null)}
        onEdit={(id) => navigate(`/kpi/builder/${id}`)}
        onRetire={(kpi) => { setOpenId(null); setDeleting(kpi); }}
        onDuplicate={(id) => navigate(`/kpi/builder?clone=${id}`)}
        canWrite={writable}
      />

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={confirmDelete}
        title="Retire this KPI?"
        message={`“${deleting?.name ?? ''}” will be hidden from new configurations. Historical results are unaffected.`}
        confirmLabel="Retire KPI"
        variant="danger"
      />
    </div>
  );
}
