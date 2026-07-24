import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import type { ColumnDef } from '@tanstack/react-table';
import { BellRing, Map, TrendingUp, Users } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { usePeriodSelector } from '../../hooks/usePeriodSelector';
import { useAchievements } from '../../hooks/useAchievements';
import { useChannels } from '../../hooks/useEntities';
import { useKpiDefinitions } from '../../hooks/useKpi';
import { PageHeader } from '../../components/ui/PageHeader';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Select } from '../../components/ui/Select';
import { ProgressBar } from '../../components/ui/ProgressBar';
import { EmptyState } from '../../components/ui/EmptyState';
import { DataTable } from '../../components/data/DataTable';
import { TerritoryActualsGrid } from '../../components/data/TerritoryActualsGrid';
import { formatPct, formatUnitCompact } from '../../utils/format';
import type { AchievementListItem } from '../../types/achievement';

export default function AchievementsList() {
  const navigate = useNavigate();
  const { selectedPeriodId } = usePeriodSelector();
  const [params] = useSearchParams();
  const entityParam = params.get('entity');
  const entity = entityParam ? Number(entityParam) : undefined;

  const { data, isLoading } = useAchievements(
    selectedPeriodId ? { period: selectedPeriodId, ...(entity ? { entity } : {}) } : undefined,
  );

  const columns = useMemo<ColumnDef<AchievementListItem, unknown>[]>(() => [
    { accessorKey: 'entity_name', header: 'Entity', cell: (c) => (
      <div>
        <p className="text-sm font-medium text-gray-900">{c.row.original.entity_name}</p>
        <p className="text-xs text-gray-500">{c.row.original.entity_code}</p>
      </div>
    ) },
    { accessorKey: 'kpi_name', header: 'KPI' },
    { accessorKey: 'channel_code', header: 'Channel', cell: (c) => c.getValue<string>() ?? '—' },
    { accessorKey: 'target_value', header: 'Target',
      cell: (c) => formatUnitCompact(c.getValue<string>(), c.row.original.kpi_unit) },
    { accessorKey: 'achieved_value', header: 'Achieved',
      cell: (c) => formatUnitCompact(c.getValue<string>(), c.row.original.kpi_unit) },
    {
      accessorKey: 'achievement_pct', header: 'Achievement',
      cell: (c) => (
        <div className="w-28">
          <p className="text-sm font-semibold text-gray-800">{formatPct(c.getValue<string>())}</p>
          <ProgressBar value={Number(c.getValue<string>())} size="sm" />
        </div>
      ),
    },
    { accessorKey: 'projected_pct', header: 'Projected', cell: (c) => formatPct(c.getValue<string>()) },
    {
      id: 'flag', header: '',
      cell: (c) => c.row.original.is_provisional
        ? <Badge variant="warning" size="sm">Provisional</Badge>
        : <Badge variant="success" size="sm">Final</Badge>,
    },
    {
      id: 'actions', header: '',
      cell: (c) => (
        <Button variant="ghost" size="sm" onClick={() => navigate(`/achievements/${c.row.original.id}`)}>
          View
        </Button>
      ),
    },
  ], [navigate]);

  return <AchievementsBody
    selectedPeriodId={selectedPeriodId} columns={columns}
    data={data?.results ?? []} isLoading={isLoading} entity={entity}
    initialView={params.get('view') === 'territory' ? 'territory' : 'person'} />;
}

function AchievementsBody({ selectedPeriodId, columns, data, isLoading, entity, initialView }: {
  selectedPeriodId: number | null;
  columns: ColumnDef<AchievementListItem, unknown>[];
  data: AchievementListItem[];
  isLoading: boolean;
  entity: number | undefined;
  initialView: 'person' | 'territory';
}) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [view, setView] = useState<'person' | 'territory'>(initialView);
  const [kpiId, setKpiId] = useState<number | null>(null);
  const [channelId, setChannelId] = useState<number | null>(null);
  const { data: kpisResp } = useKpiDefinitions();
  const { data: channelsResp } = useChannels();
  const kpis = useMemo(() => kpisResp?.results ?? [], [kpisResp]);
  const channels = useMemo(() => channelsResp?.results ?? [], [channelsResp]);
  const effectiveKpi = kpiId ?? kpis[0]?.id ?? null;

  if (!selectedPeriodId) {
    return <EmptyState icon={TrendingUp} title="Select a period" description="Choose a period from the header to view achievements." />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Achievement"
        description="Actuals vs targets across your network for the selected period."
        actions={
          <>
            {!user?.entity_info && (
              <Button size="sm" variant="ghost" icon={<BellRing size={14} />}
                onClick={() => navigate('/achievements/alert-rules')}>Alert rules</Button>
            )}
            <div className="inline-flex rounded-lg border border-gray-200 p-0.5">
              <Button size="sm" variant={view === 'person' ? 'primary' : 'ghost'}
                icon={<Users size={14} />} onClick={() => setView('person')}>By person</Button>
              <Button size="sm" variant={view === 'territory' ? 'primary' : 'ghost'}
                icon={<Map size={14} />} onClick={() => setView('territory')}>By territory</Button>
            </div>
          </>
        }
      />

      {view === 'person' ? (
        <Card padding="none">
          <div className="p-4">
            <DataTable
              columns={columns}
              data={data}
              isLoading={isLoading}
              searchPlaceholder="Search entity or KPI…"
              emptyTitle="No achievements"
              emptyDescription="No achievements computed for this period yet."
            />
          </div>
        </Card>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <div className="w-72">
              <Select
                aria-label="KPI"
                value={effectiveKpi ? String(effectiveKpi) : ''}
                onChange={(e) => setKpiId(e.target.value ? Number(e.target.value) : null)}
                options={kpis.map((k) => ({ value: String(k.id), label: k.name }))}
                placeholder="Choose a KPI…"
              />
            </div>
            <div className="w-56">
              <Select
                aria-label="Channel"
                value={channelId ? String(channelId) : ''}
                onChange={(e) => setChannelId(e.target.value ? Number(e.target.value) : null)}
                options={[{ value: '', label: 'All channels' },
                          ...channels.map((c) => ({ value: String(c.id), label: c.name }))]}
                placeholder="All channels"
              />
            </div>
          </div>
          {effectiveKpi === null ? (
            <EmptyState icon={Map} title="Pick a KPI"
              description="Choose a KPI to track its committed targets vs actuals down the geography tree." />
          ) : (
            <TerritoryActualsGrid kpi={effectiveKpi} period={selectedPeriodId}
              channelId={channelId ?? undefined}
              unit={kpis.find((k) => k.id === effectiveKpi)?.unit}
              decimalPlaces={kpis.find((k) => k.id === effectiveKpi)?.decimal_places}
              key={`${effectiveKpi}-${channelId ?? 0}-${entity ?? 0}`} />
          )}
        </div>
      )}
    </div>
  );
}
