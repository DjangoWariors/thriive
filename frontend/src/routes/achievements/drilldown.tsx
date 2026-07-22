import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowLeft, Search, X } from 'lucide-react';
import { useDrilldown } from '../../hooks/useAchievements';
import { Breadcrumb } from '../../components/ui/Breadcrumb';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Skeleton } from '../../components/ui/Skeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import { Pagination } from '../../components/ui/Pagination';
import { DataTable } from '../../components/data/DataTable';
import { formatCurrency, formatDate, formatPct } from '../../utils/format';
import type { KPITransaction } from '../../types/kpi';

export default function AchievementDrilldown() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [outlet, setOutlet] = useState('');
  const [sku, setSku] = useState('');
  // Debounce the text filters so we hit the server after typing settles, not per keystroke.
  const [applied, setApplied] = useState<{ outlet: string; sku: string }>({ outlet: '', sku: '' });
  useEffect(() => {
    const t = setTimeout(() => {
      setApplied({ outlet: outlet.trim(), sku: sku.trim() });
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [outlet, sku]);

  const achievementId = id ? Number(id) : null;
  const { data, isLoading, isError } = useDrilldown(achievementId, page, applied);
  const showFilters = data?.breakdown.row_kind !== 'metric_values';
  const filtersActive = applied.outlet !== '' || applied.sku !== '';

  const columns = useMemo<ColumnDef<KPITransaction, unknown>[]>(() => [
    { accessorKey: 'transaction_date', header: 'Date', cell: (c) => formatDate(c.getValue<string>()) },
    { accessorKey: 'outlet_code', header: 'Outlet' },
    { accessorKey: 'sku_code', header: 'SKU' },
    { accessorKey: 'channel_code', header: 'Channel' },
    { accessorKey: 'net_amount', header: 'Amount', cell: (c) => formatCurrency(c.getValue<string>()) },
    {
      accessorKey: 'transaction_type', header: 'Type',
      cell: (c) => {
        const t = c.getValue<string>();
        return <Badge variant={t === 'sale' ? 'success' : 'danger'} size="sm">{t}</Badge>;
      },
    },
  ], []);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton variant="text" width={220} height={24} />
        <Skeleton variant="rect" height={120} />
        <Skeleton variant="rect" height={300} />
      </div>
    );
  }

  if (isError || !data) {
    return <EmptyState icon={ArrowLeft} title="Achievement not found" actionLabel="Back to dashboard" onAction={() => navigate('/')} />;
  }

  const ach = data.breakdown.achievement;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <Breadcrumb
            items={[
              { label: 'Dashboard', onClick: () => navigate('/') },
              { label: 'Achievements', onClick: () => navigate('/achievements') },
              { label: ach.kpi_name },
            ]}
          />
          <h2 className="mt-1 text-xl font-semibold text-gray-900">
            {ach.kpi_name} · {ach.entity_name}
          </h2>
        </div>
        <Button variant="outline" size="sm" icon={<ArrowLeft size={14} />} onClick={() => navigate(-1)}>
          Back
        </Button>
      </div>

      {/* Summary */}
      <Card padding="md">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Metric label="Target" value={formatCurrency(ach.target_value)} />
          <Metric label="Achieved" value={formatCurrency(ach.achieved_value)} />
          <Metric label="Achievement" value={formatPct(ach.achievement_pct)} />
          <Metric label="Projected" value={formatPct(ach.projected_pct)} />
          <Metric label="Req. run-rate" value={formatCurrency(ach.required_run_rate)} />
          <Metric
            label="Growth vs LY"
            value={ach.growth_pct !== null ? formatPct(ach.growth_pct) : '—'}
          />
        </div>
      </Card>

      {/* Gross / returns / net */}
      <Card title="Net Sales Breakdown" padding="md">
        <div className="grid grid-cols-3 gap-4">
          <Metric label="Gross" value={formatCurrency(data.breakdown.gross_value)} />
          <Metric label="Returns" value={formatCurrency(data.breakdown.returns_value)} />
          <Metric label="Net" value={formatCurrency(data.breakdown.net_value)} />
        </div>
      </Card>

      {/* Transactions */}
      <Card title="Transactions"
            subtitle={filtersActive ? `${data.count} records match the filters` : `${data.count} records`}
            padding="none">
        <div className="space-y-4 p-4">
          {showFilters && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="w-48">
                <Input placeholder="Filter by outlet…" value={outlet}
                       onChange={(e) => setOutlet(e.target.value)}
                       leftIcon={<Search className="h-4 w-4" />} />
              </div>
              <div className="w-48">
                <Input placeholder="Filter by SKU…" value={sku}
                       onChange={(e) => setSku(e.target.value)}
                       leftIcon={<Search className="h-4 w-4" />} />
              </div>
              {filtersActive && (
                <Button variant="ghost" size="sm" icon={<X className="h-4 w-4" />}
                        onClick={() => { setOutlet(''); setSku(''); }}>
                  Clear
                </Button>
              )}
            </div>
          )}
          <DataTable columns={columns} data={data.results} hideSearch
                     emptyTitle={filtersActive ? 'No transactions match those filters' : 'No transactions'}
                     pageSize={25} />
          <Pagination count={data.count} page={page} pageSize={25} onPageChange={setPage} />
        </div>
      </Card>

      <p className="text-xs text-gray-400">
        Computed {ach.computed_at ? formatDate(ach.computed_at) : '—'}
        {ach.computation_id ? ` (ID: ${ach.computation_id})` : ''} ·{' '}
        <Badge variant={ach.is_provisional ? 'warning' : 'success'} size="sm">
          {ach.is_provisional ? 'Provisional' : 'Final'}
        </Badge>
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-gray-800">{value}</p>
    </div>
  );
}
