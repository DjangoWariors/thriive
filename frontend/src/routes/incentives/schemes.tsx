import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { Award, Pencil, Plus, Search, ShieldCheck, Trash2 } from 'lucide-react';
import { useDeactivateScheme, useSchemes } from '../../hooks/useIncentives';
import { useRBAC } from '../../hooks/useRBAC';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { EmptyState } from '../../components/ui/EmptyState';
import { Input } from '../../components/ui/Input';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import type { IncentiveSchemeListItem } from '../../types/incentive';

export default function SchemesPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState<IncentiveSchemeListItem | null>(null);

  const { canWrite } = useRBAC();
  const writable = canWrite('scheme_management');
  const { data: resp, isLoading } = useSchemes();
  const deactivate = useDeactivateScheme();

  const schemes = useMemo(() => {
    const all = resp?.results ?? [];
    if (!search) return all;
    const q = search.toLowerCase();
    return all.filter(
      (s) => s.name.toLowerCase().includes(q) || s.code.toLowerCase().includes(q),
    );
  }, [resp, search]);

  const confirmDelete = () => {
    if (!deleting) return;
    deactivate.mutate(deleting.id, {
      onSuccess: () => {
        notify.success(`“${deleting.name}” has been retired`);
        setDeleting(null);
      },
      onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, we couldn’t retire that scheme')),
    });
  };

  return (
    <div className="p-6">
      <PageHeader
          title="Incentive Schemes"
          description="How your field force earns: KPI weightages, multiplier grids, gatekeepers and caps. Editing a scheme creates a new version — past payouts are never rewritten."
          actions={<>{writable && (
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => navigate('/incentives/schemes/builder')}>
            New Scheme
          </Button>
        )}</>}
      />

      <div className="mb-4 w-64">
        <Input
          placeholder="Search schemes…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          leftIcon={<Search className="h-4 w-4" />}
        />
      </div>

      {isLoading ? (
        <TableSkeleton/>
      ) : schemes.length === 0 ? (
        <Card>
          <EmptyState
            icon={Award}
            title="No incentive schemes yet"
            description="Create your first scheme to start computing payouts: pick the entity type it pays, weigh its KPIs, and set the multiplier grid."
            actionLabel={writable ? 'New Scheme' : undefined}
            onAction={writable ? () => navigate('/incentives/schemes/builder') : undefined}
          />
        </Card>
      ) : (
        <Card padding="none">
          <SimpleTable
            rows={schemes}
            rowKey={(s) => s.id}
            columns={[
              {header: 'Code', render: (s) => (
                <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{s.code}</code>
              )},
              {header: 'Name', render: (s) => <span className="font-medium text-gray-900">{s.name}</span>},
              {header: 'Pays', render: (s) => <span className="text-gray-600">{s.entity_type_name}</span>},
              {header: 'Channel', render: (s) => <span className="text-gray-500">{s.channel_code ?? 'All'}</span>},
              {header: 'KPIs', align: 'center', render: (s) => <span className="text-gray-600">{s.kpi_count}</span>},
              {header: 'Gates', render: (s) => (
                s.has_gatekeeper ? (
                  <Badge variant="warning">
                    <span className="inline-flex items-center gap-1">
                      <ShieldCheck size={12} /> Gated
                    </span>
                  </Badge>
                ) : (
                  <span className="text-gray-400">—</span>
                )
              )},
              {header: 'Cap', render: (s) => (
                <span className="text-gray-600">{s.overall_cap_pct ? `${s.overall_cap_pct}%` : '—'}</span>
              )},
              {header: 'Version', align: 'center', render: (s) => <span className="text-gray-500">v{s.version}</span>},
              ...(writable ? [{
                header: 'Actions', align: 'right' as const,
                render: (s: IncentiveSchemeListItem) => (
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="sm" aria-label={`Edit ${s.code}`}
                            onClick={() => navigate(`/incentives/schemes/builder/${s.id}`)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="sm" aria-label={`Retire ${s.code}`}
                            onClick={() => setDeleting(s)}>
                      <Trash2 className="h-4 w-4 text-danger" />
                    </Button>
                  </div>
                ),
              }] : []),
            ]}
          />
        </Card>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={confirmDelete}
        title="Retire this scheme?"
        message={`“${deleting?.name ?? ''}” will stop being available for new payout runs. Existing runs and payouts stay exactly as they were.`}
        confirmLabel="Retire Scheme"
        variant="danger"
      />
    </div>
  );
}
