import { useNavigate } from 'react-router';
import { Gauge, IndianRupee, AlertTriangle, Users, Target, Play } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useRBAC } from '../../hooks/useRBAC';
import { usePeriodSelector } from '../../hooks/usePeriodSelector';
import { useDashboard, useComputeAchievements, useAcknowledgeAlert, useAcknowledgeAllAlerts } from '../../hooks/useAchievements';
import { StatCard } from '../../components/data/StatCard';
import { KPICard } from '../../components/charts/KPICard';
import { TrendChart } from '../../components/charts/TrendChart';
import { ChannelMixChart } from '../../components/charts/ChannelMixChart';
import { Leaderboard } from '../../components/charts/Leaderboard';
import { AlertList } from '../../components/charts/AlertList';
import { TerritorySnapshotCard } from '../../components/charts/TerritorySnapshotCard';
import { PayoutCycleCard } from '../../components/charts/PayoutCycleCard';
import { Skeleton } from '../../components/ui/Skeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import { Button } from '../../components/ui/Button';
import { PageHeader } from '../../components/ui/PageHeader';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import { formatCurrency, formatPct } from '../../utils/format';

export default function Dashboard() {
  const { user } = useAuth();
  const { can } = useRBAC();
  const navigate = useNavigate();
  const { selectedPeriodId } = usePeriodSelector();
  const { data, isLoading, isError, refetch } = useDashboard(selectedPeriodId);
  const compute = useComputeAchievements();
  const ack = useAcknowledgeAlert();
  const ackAll = useAcknowledgeAllAlerts();

  const name = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || 'there';
  const canCompute = can('achievement_compute');

  function runCompute() {
    if (!selectedPeriodId) return;
    compute.mutate(selectedPeriodId, {
      onSuccess: () => notify.success('Achievement computation started.'),
      onError: (e) => notify.error(apiErrorMessage(e, 'Could not start computation.')),
    });
  }

  if (!selectedPeriodId) {
    return (
      <EmptyState
        icon={Target}
        title="Select a period"
        description="Choose a target period from the selector in the header to view the dashboard."
      />
    );
  }

  if (isLoading) return <DashboardSkeleton />;

  if (isError || !data) {
    return (
      <div className="flex flex-col items-center">
        <EmptyState
          icon={AlertTriangle}
          title="Couldn't load the dashboard"
          description="Something went wrong while fetching this period's data."
          actionLabel="Retry"
          onAction={() => void refetch()}
        />
        {canCompute && (
          <Button variant="outline" size="sm" icon={<Play size={14} />} loading={compute.isPending} onClick={runCompute}>
            Run computation
          </Button>
        )}
      </div>
    );
  }

  const { summary, kpi_cards, child_ranking, trend, channel_mix, alerts, modules } = data;
  const hasData = kpi_cards.length > 0 || (child_ranking?.length ?? 0) > 0;

  return (
    <div className="space-y-6">
      <PageHeader
        className="mb-0"
        title={`Welcome back, ${name} 👋`}
        // An unscoped admin is shown the root node's numbers; naming that person here
        // read as if the admin were looking at someone else's scorecard.
        description={`${data.entity ? `${data.entity.is_own ? data.entity.name : 'Organisation-wide'} · ` : ''}Performance for the selected period.`}
        actions={canCompute && (
          <Button variant="outline" size="sm" icon={<Play size={14} />} loading={compute.isPending} onClick={runCompute}>
            Recompute
          </Button>
        )}
      />

      {!hasData ? (
        <EmptyState
          icon={Target}
          title="No achievements yet"
          description="No achievements have been computed for this period."
          {...(canCompute ? { actionLabel: 'Run computation', onAction: runCompute } : {})}
        />
      ) : (
        <>
          {/* Row 1 — summary cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <StatCard
              label="Overall Achievement" borderColor="red" icon={Gauge}
              value={formatPct(summary.overall_achievement_pct)}
              subtitle={`Projected ${formatPct(summary.projected_pct)}`}
            />
            <StatCard
              label={summary.primary_kpi_name ?? 'Primary Sales'} borderColor="red" icon={Target}
              value={formatCurrency(summary.primary_achieved)}
              subtitle={`of ${formatCurrency(summary.primary_target)}`}
            />
            {modules.incentives ? (
              <StatCard
                label={summary.payout_kind === 'final' ? 'Payout' : 'Estimated Payout'}
                borderColor="green" icon={IndianRupee}
                value={summary.estimated_payout ? formatCurrency(summary.estimated_payout) : '—'}
                subtitle={
                  summary.payout_kind === 'final' ? 'Finalized for this period'
                  : summary.payout_kind === 'estimate' ? 'Estimate — updates nightly'
                  : 'Awaiting payout run'
                }
                onClick={() => navigate('/incentives/payouts')}
              />
            ) : (
              <StatCard
                label="Projected %" borderColor="green" icon={Gauge}
                value={formatPct(summary.projected_pct)} subtitle="Working-day run-rate"
              />
            )}
            <StatCard
              label="Open Alerts" borderColor="amber" icon={AlertTriangle}
              value={String(summary.open_alerts)} subtitle="Needs attention"
              onClick={() => navigate('/achievements')}
            />
            <StatCard
              label="Active Reps" borderColor="blue" icon={Users}
              value={String(summary.active_entities)} subtitle="In your network"
            />
          </div>

          {/* Row 2 — KPI cards */}
          {kpi_cards.length > 0 && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {kpi_cards.map((card) => (
                <KPICard
                  key={card.id} card={card} showMultiplier={modules.incentives}
                  onClick={() => navigate(`/achievements/${card.id}`)}
                />
              ))}
            </div>
          )}

          {/* Row 3 — trend + channel mix + leaderboard */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TrendChart data={trend} />
            <div className="space-y-4">
              <ChannelMixChart data={channel_mix} />
              {child_ranking && (
                <Leaderboard
                  rows={child_ranking}
                  title="Team Leaderboard"
                  showPayout={modules.incentives}
                  onRowClick={(r) => navigate(`/achievements?entity=${r.entity_id}&period=${selectedPeriodId}`)}
                />
              )}
            </div>
          </div>

          {/* Row 4 — territory plan tracking + payout cycle status */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TerritorySnapshotCard periodId={selectedPeriodId} />
            {can('final_payout') && <PayoutCycleCard periodId={selectedPeriodId} />}
          </div>

          {/* Row 5 — alerts */}
          <AlertList alerts={alerts}
                     totalOpen={summary.open_alerts}
                     onOpen={(a) => navigate(
                       `/achievements?period=${selectedPeriodId}&entity=${a.entity_id}`
                       + (a.kpi_id ? `&kpi=${a.kpi_id}` : ''))}
                     onAcknowledge={(id) => ack.mutate(id)}
                     onAcknowledgeAll={() => ackAll.mutate(selectedPeriodId, {
                       onSuccess: (r) => notify.success(
                         r.acknowledged > 0
                           ? `${r.acknowledged} alert${r.acknowledged === 1 ? '' : 's'} marked as seen`
                           : 'Nothing left to mark — all alerts were already seen'),
                       onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, that didn’t go through')),
                     })} />
        </>
      )}
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton variant="text" width={260} height={28} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} variant="rect" height={110} />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} variant="rect" height={180} />
        ))}
      </div>
      <Skeleton variant="rect" height={300} />
    </div>
  );
}
