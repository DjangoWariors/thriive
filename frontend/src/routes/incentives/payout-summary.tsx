import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { AlertTriangle, ArrowRight, Eye, IndianRupee, ShieldX, Users } from 'lucide-react';
import { usePeriodSelector } from '../../hooks/usePeriodSelector';
import { useRBAC } from '../../hooks/useRBAC';
import { useTargetPeriods } from '../../hooks/useTargets';
import { usePayoutRuns, usePayouts, usePayoutSummary, useSchemes } from '../../hooks/useIncentives';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { EmptyState } from '../../components/ui/EmptyState';
import { Pagination } from '../../components/ui/Pagination';
import { Select } from '../../components/ui/Select';
import { SimpleTable } from '../../components/ui/SimpleTable';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { PageHeader } from '../../components/ui/PageHeader';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { StatCard } from '../../components/data/StatCard';
import { formatCurrency } from '../../utils/format';
import type { PayoutRun } from '../../types/incentive';

/** Display preference: the run whose numbers this register shows. */
const KIND_ORDER: Record<PayoutRun['kind'], number> = { final: 0, adjustment: 1, estimate: 2 };

export default function PayoutSummaryPage() {
  const navigate = useNavigate();
  const { selectedPeriodId } = usePeriodSelector();
  // Payout runs are org-wide (scheme-level totals) → view_all+ only. own_only holders
  // still see their own scoped payout table/summary below, just not the run banner.
  const { canAtLeast } = useRBAC();
  const isPayoutAdmin = canAtLeast('final_payout', 'view_all');

  const [schemeId, setSchemeId] = useState<number | null>(null);
  const [page, setPage] = useState(1);

  const { data: periodsResp } = useTargetPeriods();
  const period = periodsResp?.results.find((p) => p.id === selectedPeriodId);
  const periodOpen = period ? period.status !== 'locked' && period.status !== 'closed' : false;

  const { data: schemesResp } = useSchemes();
  const schemes = schemesResp?.results ?? [];
  const effectiveSchemeId = schemeId ?? schemes[0]?.id ?? null;

  const runParams = isPayoutAdmin && selectedPeriodId !== null && effectiveSchemeId !== null
    ? { period: selectedPeriodId, scheme: effectiveSchemeId } : undefined;
  const { data: runsResp } = usePayoutRuns(runParams);
  const liveRun: PayoutRun | undefined = useMemo(
    () => (runsResp?.results ?? [])
      .filter((r) => r.status !== 'superseded' && r.status !== 'failed')
      .sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind])[0],
    [runsResp],
  );

  const payoutParams = selectedPeriodId !== null
    ? { period: selectedPeriodId, ...(effectiveSchemeId ? { scheme: effectiveSchemeId } : {}), page }
    : undefined;
  const { data: payoutsResp, isLoading: loadingPayouts } =
    usePayouts(payoutParams, selectedPeriodId !== null);
  const { data: summary } = usePayoutSummary(
    selectedPeriodId !== null
      ? { period: selectedPeriodId, ...(effectiveSchemeId ? { scheme: effectiveSchemeId } : {}) }
      : undefined,
    selectedPeriodId !== null,
  );

  const payouts = payoutsResp?.results ?? [];

  return (
    <div className="p-6">
      <PageHeader
          title={period ? `Payouts — ${period.name}` : 'Payouts'}
          description="The register: computed incentives per person for the selected period. Computing, review and disbursement happen in Payout Cycles — this page shows the resulting money."
          actions={
            <div className="w-72">
              <Select
                aria-label="Scheme"
                value={effectiveSchemeId ? String(effectiveSchemeId) : ''}
                onChange={(e) => { setSchemeId(e.target.value ? Number(e.target.value) : null); setPage(1); }}
                options={schemes.map((s) => ({ value: String(s.id), label: `${s.name} (v${s.version})` }))}
                placeholder="Choose a scheme…"
              />
            </div>
          }
      />

      {selectedPeriodId === null ? (
        <Card>
          <EmptyState icon={IndianRupee} title="Pick a period"
                      description="Choose a period from the selector in the header to see payouts." />
        </Card>
      ) : (
        <>
          {/* Where these numbers come from — org-wide run detail, payout admins only. */}
          {isPayoutAdmin && (
          <Card className="mb-4">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-700">Latest run:</span>
                {liveRun ? (
                  <>
                    <Badge variant={liveRun.kind === 'estimate' ? 'info' : 'purple'}>{liveRun.kind}</Badge>
                    <StatusBadge status={liveRun.status} />
                  </>
                ) : (
                  <Badge variant="default">Not computed</Badge>
                )}
              </div>
              {!liveRun && (
                <span className="text-xs text-gray-500">
                  {periodOpen
                    ? 'This month is still open — payouts are computed when its cycle is closed (finalize → compute).'
                    : 'No payout run yet — run this period’s month-close in Payout Cycles.'}
                </span>
              )}
              {liveRun && (
                <span className="text-xs text-gray-500">
                  {liveRun.entities_processed} entities · {formatCurrency(liveRun.total_payout)} total
                  {liveRun.error_count > 0 && (
                    <span className="text-danger"> · {liveRun.error_count} skipped</span>
                  )}
                  {liveRun.status === 'paid' && liveRun.payment_ref && ` · ref ${liveRun.payment_ref}`}
                </span>
              )}
              {liveRun?.kind === 'estimate' && (
                <span className="text-xs text-gray-500">
                  Nightly estimate — final numbers come from the month-close.
                </span>
              )}
              <div className="ml-auto">
                <Button size="sm" variant="outline" iconRight={<ArrowRight size={14} />}
                        onClick={() => navigate(`/incentives/cycles?period=${selectedPeriodId}`)}>
                  Manage in Payout Cycles
                </Button>
              </div>
            </div>

            {liveRun && liveRun.error_count > 0 && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                <p className="font-medium">
                  {liveRun.error_count} eligible {liveRun.error_count === 1 ? 'person was' : 'people were'} skipped:
                </p>
                <ul className="mt-1 space-y-0.5">
                  {liveRun.errors.slice(0, 8).map((e) => (
                    <li key={e.entity_id}>
                      {e.entity_name ?? `#${e.entity_id}`} — {e.error}
                    </li>
                  ))}
                  {liveRun.errors.length > 8 && <li>…and {liveRun.errors.length - 8} more</li>}
                </ul>
              </div>
            )}
          </Card>
          )}

          {/* Summary cards */}
          {summary && (
            <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-5">
              <StatCard label="Total payout" value={formatCurrency(summary.total_payout)}
                        borderColor="green" icon={IndianRupee} />
              <StatCard label="People paid" value={String(summary.entities)}
                        borderColor="blue" icon={Users} />
              <StatCard label="Capped" value={String(summary.capped_count)}
                        subtitle="Hit the overall cap" borderColor="amber" icon={AlertTriangle} />
              <StatCard label="Gatekeeper failed" value={String(summary.gatekeeper_failed_count)}
                        subtitle="Zeroed by the hurdle" borderColor="red" icon={ShieldX} />
              <StatCard label="With exception" value={String(summary.exception_count)}
                        borderColor="purple" icon={AlertTriangle} />
            </div>
          )}

          {/* Payout table */}
          {loadingPayouts ? (
            <TableSkeleton/>
          ) : payouts.length === 0 ? (
            <Card>
              <EmptyState icon={IndianRupee} title="No payouts yet"
                          description={periodOpen
                            ? 'This month is still open. Payouts appear after its cycle is finalized and computed — a mid-month compute would pay near zero (achievements below the paying floor).'
                            : "Payouts appear once this period's cycle computes them — run the month-close from Payout Cycles."} />
            </Card>
          ) : (
            <Card padding="none">
              <SimpleTable
                rows={payouts}
                rowKey={(p) => p.id}
                onRowClick={(p) => navigate(`/incentives/payouts/${p.id}`)}
                columns={[
                  {header: 'Person', render: (p) => (
                    <>
                      <p className="font-medium text-gray-900">{p.entity_name}</p>
                      <p className="text-xs text-gray-500">{p.entity_code} · {p.entity_type_code}</p>
                    </>
                  )},
                  {header: 'Eligible VP', align: 'right', render: (p) => (
                    <span className="text-gray-600">
                      {formatCurrency(p.eligible_vp)}
                      {parseFloat(p.proration_factor) < 1 && (
                        <p className="text-xs text-amber-600">
                          prorated ×{parseFloat(p.proration_factor).toFixed(2)}
                        </p>
                      )}
                    </span>
                  )},
                  {header: 'Multiplier', align: 'right', render: (p) => (
                    <span className="text-gray-600">{parseFloat(p.total_multiplier).toFixed(2)}×</span>
                  )},
                  {header: 'Gates', render: (p) => <StatusBadge status={p.gatekeeper_status} />},
                  {header: 'Gross', align: 'right', render: (p) => (
                    <span className="text-gray-500">{formatCurrency(p.gross_payout)}</span>
                  )},
                  {header: 'Payout', align: 'right', render: (p) => (
                    <span className="font-semibold text-gray-900">{formatCurrency(p.total_payout)}</span>
                  )},
                  {header: 'Flags', render: (p) => (
                    <div className="flex gap-1">
                      {p.capped && <Badge variant="warning">Capped</Badge>}
                      {p.has_exception && <Badge variant="purple">Exception</Badge>}
                    </div>
                  )},
                  {header: 'Actions', align: 'right', render: (p) => (
                    <Button variant="ghost" size="sm" aria-label={`View breakdown for ${p.entity_name}`}
                            onClick={(e) => { e.stopPropagation(); navigate(`/incentives/payouts/${p.id}`); }}>
                      <Eye className="h-4 w-4" />
                    </Button>
                  )},
                ]}
              />
              <Pagination count={payoutsResp?.count ?? 0} page={page} onPageChange={setPage} />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
