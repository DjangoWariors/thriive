import { useEffect, useRef, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { useDiscardRun, useSetPlanTop, useStartRun } from '../../hooks/useTargets';
import { useKpiDefinitions } from '../../hooks/useKpi';
import type { PlanRun, TargetPlan } from '../../types/target';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { Input } from '../ui/Input';
import { notify } from '../../utils/notify';
import { makeUnitFormatter } from '../../utils/format';
import { apiErrorMessage } from '../../utils/apiError';

/** "571000.0000" → "571000": inputs shouldn't echo the column's storage precision. */
function trimZeros(v: string | null): string {
  if (v === null || v === '') return '';
  const n = Number(v);
  return Number.isNaN(n) ? v : String(n);
}

/** Stage 1 — set the number each KPI cascades from. "Calculate suggestion" runs the
 * baseline behind the scenes: the suggestion lands on the plan the moment the run stages,
 * so the staged run itself is settled (discarded) silently instead of surfacing a banner. */
export function TopNumbersStage({ plan, stagedBaseline, calculating, editable }: {
  plan: TargetPlan;
  stagedBaseline: PlanRun | null;
  calculating: boolean;
  editable: boolean;
}) {
  const startRun = useStartRun();
  const discard = useDiscardRun();
  const setTop = useSetPlanTop();
  const { data: kpiDefs } = useKpiDefinitions({ page_size: 200 });
  const fmtFor = (kpiId: number) => {
    const def = kpiDefs?.results?.find((k) => k.id === kpiId);
    return makeUnitFormatter(def?.unit, def?.decimal_places);
  };
  const [values, setValues] = useState<Record<number, string>>({});

  const settledRef = useRef<number | null>(null);
  useEffect(() => {
    if (stagedBaseline && settledRef.current !== stagedBaseline.id) {
      settledRef.current = stagedBaseline.id;
      discard.mutate(stagedBaseline.id);
    }
  }, [stagedBaseline, discard]);

  const busy = calculating || startRun.isPending || (stagedBaseline !== null);
  const hasSuggestions = plan.kpis.some((k) => k.derived_top_value !== null);

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">Top numbers</h3>
          <p className="mt-0.5 text-xs text-gray-500">
            Set the number each KPI cascades from. The suggestion (last year's history × growth)
            is your sanity anchor — you can type any number.
          </p>
        </div>
        {editable && (
          <Button variant="outline" size="sm" icon={<Sparkles className="h-4 w-4" />} loading={busy}
                  onClick={() => startRun.mutate({ planId: plan.id, kind: 'baseline' }, {
                    onError: (e) => notify.error(apiErrorMessage(e, 'Could not calculate a suggestion')),
                  })}>
            {busy ? 'Calculating…' : hasSuggestions ? 'Recalculate suggestion' : 'Calculate suggestion'}
          </Button>
        )}
      </div>

      <div className="mt-4 max-w-xl space-y-3">
        {plan.kpis.map((k) => (
          <div key={k.id} className="flex items-end gap-3">
            <div className="flex-1">
              <Input label={k.kpi_name} type="number" disabled={!editable}
                     value={values[k.kpi] ?? trimZeros(k.top_value)}
                     onChange={(e) => setValues({ ...values, [k.kpi]: e.target.value })}
                     hint={k.derived_top_value !== null
                       ? `Suggested: ${fmtFor(k.kpi)(k.derived_top_value)}`
                       : 'Calculate a suggestion, or type the AOP number directly'} />
            </div>
            {editable && (
              <Button variant="outline" size="sm" loading={setTop.isPending}
                      disabled={!(values[k.kpi] ?? k.top_value)}
                      onClick={() => setTop.mutate(
                        { id: plan.id, kpiId: k.kpi, value: values[k.kpi] ?? trimZeros(k.top_value) },
                        { onSuccess: () => notify.success(`${k.kpi_code} top number saved`),
                          onError: (e) => notify.error(apiErrorMessage(e, 'Could not save')) })}>
                Save
              </Button>
            )}
          </div>
        ))}
      </div>
      {!editable && (
        <p className="mt-3 text-xs text-gray-400">Top numbers are set while the plan is a draft.</p>
      )}
    </Card>
  );
}
