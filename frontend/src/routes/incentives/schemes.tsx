import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { AlertCircle, Award, CheckCircle2, Pencil, Plus, Search, ShieldCheck, Trash2 } from 'lucide-react';
import { useDeactivateScheme, useSchemes } from '../../hooks/useIncentives';
import { useRBAC } from '../../hooks/useRBAC';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { EmptyState } from '../../components/ui/EmptyState';
import { HowThisWorks } from '../../components/ui/HowThisWorks';
import { Input } from '../../components/ui/Input';
import { PageHeader } from '../../components/ui/PageHeader';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { SimpleTable } from '../../components/ui/SimpleTable';
import { cn } from '../../utils/cn';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import type { IncentiveSchemeListItem } from '../../types/incentive';

/** One SIP: every current scheme paying the same entity type × channel. */
interface SipGroup {
  key: string;
  entityTypeName: string;
  entityTypeCode: string;
  channelCode: string | null;
  schemes: IncentiveSchemeListItem[];
  totalVpPct: number;
}

function groupSchemes(schemes: IncentiveSchemeListItem[]): SipGroup[] {
  const groups = new Map<string, SipGroup>();
  for (const s of schemes) {
    const key = `${s.entity_type_code}|${s.channel_code ?? ''}`;
    let g = groups.get(key);
    if (!g) {
      g = {
        key,
        entityTypeName: s.entity_type_name,
        entityTypeCode: s.entity_type_code,
        channelCode: s.channel_code,
        schemes: [],
        totalVpPct: 0,
      };
      groups.set(key, g);
    }
    g.schemes.push(s);
    g.totalVpPct += parseFloat(s.vp_basis_pct);
  }
  return [...groups.values()].sort((a, b) =>
    a.entityTypeName.localeCompare(b.entityTypeName) ||
    (a.channelCode ?? '').localeCompare(b.channelCode ?? ''),
  );
}

export default function SchemesPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState<IncentiveSchemeListItem | null>(null);

  const { canWrite } = useRBAC();
  const writable = canWrite('scheme_management');
  // Full list in one page so a group's monthly + annual components are never split.
  const { data: resp, isLoading } = useSchemes({ page_size: 200 });
  const deactivate = useDeactivateScheme();

  const groups = useMemo(() => {
    const all = resp?.results ?? [];
    const q = search.toLowerCase();
    const filtered = q
      ? all.filter((s) => s.name.toLowerCase().includes(q) || s.code.toLowerCase().includes(q))
      : all;
    return groupSchemes(filtered);
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
          description="Each role × channel gets one SIP, made of one or more schemes paying a share of variable pay — e.g. 80% against monthly KPIs + 20% against annual performance. Editing a scheme creates a new version — past payouts are never rewritten."
          actions={<>{writable && (
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => navigate('/incentives/schemes/builder')}>
            New Scheme
          </Button>
        )}</>}
      />

      <HowThisWorks storageKey="schemes-sip-help" className="mb-6">
        A Sales Incentive Plan (SIP) can pay variable pay in parts: a monthly scheme paying against
        monthly KPIs (say 80% of VP) and an annual scheme paying against full-year performance (the
        remaining 20%). Each part is an ordinary incentive scheme with its own KPIs, weightages and
        multiplier slabs — schemes below are grouped per role × channel with a check that the shares
        add up to 100%. A single scheme at 100% is equally valid.
      </HowThisWorks>

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
      ) : groups.length === 0 ? (
        <Card>
          <EmptyState
            icon={Award}
            title={search ? 'No schemes match your search' : 'No incentive schemes yet'}
            description={search
              ? 'Try a different name or code.'
              : 'Create your first scheme to start computing payouts: pick the entity type it pays, weigh its KPIs, and set the multiplier grid.'}
            actionLabel={writable && !search ? 'New Scheme' : undefined}
            onAction={writable && !search ? () => navigate('/incentives/schemes/builder') : undefined}
          />
        </Card>
      ) : (
        <div className="space-y-4">
          {groups.map((g) => (
            <SipGroupCard key={g.key} group={g} writable={writable}
                          onEdit={(s) => navigate(`/incentives/schemes/builder/${s.id}`)}
                          onRetire={setDeleting}/>
          ))}
        </div>
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

function SipGroupCard({ group, writable, onEdit, onRetire }: {
  group: SipGroup;
  writable: boolean;
  onEdit: (s: IncentiveSchemeListItem) => void;
  onRetire: (s: IncentiveSchemeListItem) => void;
}) {
  const isComplete = Math.abs(group.totalVpPct - 100) < 0.005;
  return (
    <Card padding="none">
      <div className="px-5 pt-4">
        <div className="mb-3 flex items-start justify-between">
          <div>
            <p className="font-semibold text-gray-900">{group.entityTypeName}</p>
            <p className="text-xs text-gray-500">
              {group.entityTypeCode} · {group.channelCode ?? 'All channels'}
            </p>
          </div>
          {isComplete ? (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-success">
              <CheckCircle2 className="h-4 w-4"/> Complete (100%)
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-warning"
                  title="Variable-pay shares don't sum to 100% — fine if intentional.">
              <AlertCircle className="h-4 w-4"/> {+group.totalVpPct.toFixed(2)}% of VP covered
            </span>
          )}
        </div>

        {/* VP split bar — segments are self-labelled; native title is only a fallback */}
        <div className="mb-3 flex h-5 w-full overflow-hidden rounded-full bg-gray-100">
          {group.schemes.map((s, i) => {
            const pct = Math.min(100, parseFloat(s.vp_basis_pct));
            return (
              <div key={s.id}
                   className={cn(
                     'flex items-center justify-center overflow-hidden whitespace-nowrap',
                     'text-[10px] font-medium leading-none text-white',
                     i % 2 === 0 ? 'bg-primary' : 'bg-primary-light',
                   )}
                   style={{width: `${pct}%`}}
                   title={`${s.name}: ${s.vp_basis_pct}%`}>
                {pct >= 25 ? `${s.payout_frequency} ${+pct.toFixed(2)}%`
                  : pct >= 10 ? `${+pct.toFixed(2)}%` : ''}
              </div>
            );
          })}
          {group.totalVpPct < 100 && (
            <div className="flex flex-1 items-center justify-center text-[10px] leading-none text-gray-500">
              {100 - group.totalVpPct >= 10 ? 'uncovered' : ''}
            </div>
          )}
        </div>
      </div>

      <SimpleTable
        rows={group.schemes}
        rowKey={(s) => s.id}
        columns={[
          {header: 'Code', render: (s) => (
            <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{s.code}</code>
          )},
          {header: 'Name', render: (s) => <span className="font-medium text-gray-900">{s.name}</span>},
          {header: 'Component', render: (s) => (
            <Badge variant={s.payout_frequency === 'annual' ? 'purple' : 'info'}>
              {s.payout_frequency}
            </Badge>
          )},
          {header: 'VP share', align: 'right', render: (s) => (
            <span className="font-semibold text-gray-900">{s.vp_basis_pct}%</span>
          )},
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
                <Button variant="ghost" size="sm" aria-label={`Edit ${s.code}`} onClick={() => onEdit(s)}>
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="sm" aria-label={`Retire ${s.code}`} onClick={() => onRetire(s)}>
                  <Trash2 className="h-4 w-4 text-danger" />
                </Button>
              </div>
            ),
          }] : []),
        ]}
      />
    </Card>
  );
}
