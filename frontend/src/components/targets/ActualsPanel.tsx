import { ChevronRight, Info, Play } from 'lucide-react';
import { useComputeAchievements } from '../../hooks/useAchievements';
import { useKpiDefinitions } from '../../hooks/useKpi';
import { useRBAC } from '../../hooks/useRBAC';
import type { TargetPlan } from '../../types/target';
import { isLive } from './plan-stages';
import { TerritoryActualsGrid } from '../data/TerritoryActualsGrid';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/EmptyState';
import { Tabs } from '../ui/Tabs';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

/** The plan-tracking tab: target vs actual per territory, with the compute trigger right
 * here — no trip to the dashboard. Compute runs for the plan's own month. */
export function ActualsPanel({ plan, kpiId, setKpiId }: {
  plan: TargetPlan; kpiId: number; setKpiId: (id: number) => void;
}) {
  const { can } = useRBAC();
  const compute = useComputeAchievements();
  const { data: kpiDefs } = useKpiDefinitions({ page_size: 200 });
  const kpiDef = kpiDefs?.results?.find((k) => k.id === kpiId);

  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <Tabs activeTab={String(kpiId)} onChange={(v) => setKpiId(Number(v))}
              tabs={plan.kpis.map((k) => ({ value: String(k.kpi), label: k.kpi_name }))} />
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">Target vs actual per territory · {plan.period_code}</span>
          {can('achievement_compute') && (
            <Button variant="outline" size="sm" icon={<Play className="h-3.5 w-3.5" />}
                    loading={compute.isPending}
                    onClick={() => compute.mutate(plan.period, {
                      onSuccess: () => notify.success(
                        `Computing actuals for ${plan.period_code} — numbers refresh shortly.`),
                      onError: (e) => notify.error(apiErrorMessage(e, 'Could not start the compute')),
                    })}>
              Run compute
            </Button>
          )}
        </div>
      </div>
      {!isLive(plan) && (
        <p className="mb-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          This plan isn't published yet — its targets stay out of this view until it goes live.
          Only already-live numbers for {plan.period_code} appear below.
        </p>
      )}
      {kpiId > 0 ? (
        <TerritoryActualsGrid kpi={kpiId} period={plan.period}
          channelId={plan.channel ?? undefined}
          rootId={plan.root_geography} rootLabel={plan.root_geography_name}
          unit={kpiDef?.unit} decimalPlaces={kpiDef?.decimal_places}
          key={`${kpiId}-${plan.channel ?? 0}`} />
      ) : (
        <EmptyState icon={ChevronRight} title="No KPIs" description="This plan has no KPIs to track." />
      )}
    </div>
  );
}
