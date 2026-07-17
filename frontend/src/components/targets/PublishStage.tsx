import { useState } from 'react';
import { Check, Rocket, X } from 'lucide-react';
import { useCostPreview, useTransitionPlan } from '../../hooks/useTargets';
import type { TargetPlan } from '../../types/target';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { notify } from '../../utils/notify';
import { formatInr as inr } from '../../utils/format';
import { apiErrorCode, apiErrorMessage } from '../../utils/apiError';
import { isLive } from './plan-stages';

/** Stage 5 — the gates and the button. Cost of plan lives here because it IS the budget
 * gate; the over-budget publish stays possible but explicit and audited. */
export function PublishStage({ plan }: { plan: TargetPlan }) {
  const transition = useTransitionPlan();
  const hasBudget = plan.settings?.payout_budget != null;
  const { data: cost } = useCostPreview(plan.id, hasBudget);
  const [overBudgetMsg, setOverBudgetMsg] = useState<string | null>(null);

  const openTasks = plan.progress.review.open;
  const live = isLive(plan);

  function publish(force = false) {
    transition.mutate({ id: plan.id, status: 'published', force }, {
      onSuccess: () => notify.success('Plan published — targets are live.'),
      onError: (e) => {
        // The budget gate is recoverable: offer an explicit, audited over-budget publish.
        if (apiErrorCode(e) === 'over_budget') {
          setOverBudgetMsg(apiErrorMessage(e, 'Projected payout exceeds the plan budget.'));
        } else {
          notify.error(apiErrorMessage(e, 'Publish blocked'));
        }
      },
    });
  }

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">Publish</h3>
          <p className="mt-0.5 text-xs text-gray-500">
            Publishing makes these targets live for the field, achievements and payouts.
          </p>
        </div>
        {!live && (
          <Button size="sm" icon={<Rocket className="h-4 w-4" />} loading={transition.isPending}
                  onClick={() => publish()}>
            Publish
          </Button>
        )}
      </div>

      <ul className="mt-4 space-y-2">
        <Gate ok={plan.progress.review.total === 0 || openTasks === 0}
              okText={plan.progress.review.total === 0 ? 'No field review on this plan' : 'Field review answered'}
              failText={`${openTasks} review task(s) still open — wait for the field, or close them from the review stage`} />
        {hasBudget && (
          <Gate ok={!cost?.over_budget_at_100}
                okText="Projected payout is within the plan budget"
                failText="Projected payout at 100% achievement exceeds the budget — publishing needs an explicit override" />
        )}
      </ul>

      {hasBudget && cost && (
        <div className="mt-4 border-t border-gray-100 pt-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Cost of plan</h4>
          <dl className="space-y-1 text-sm">
            {Object.entries(cost.scenarios).map(([pct, total]) => (
              <div key={pct} className="flex justify-between">
                <dt className="text-gray-500">At {pct}% achievement</dt>
                <dd className="font-medium text-gray-800">₹{inr(total)}</dd>
              </div>
            ))}
            <div className="flex justify-between border-t border-gray-100 pt-1">
              <dt className="text-gray-500">Budget</dt>
              <dd className={cost.over_budget_at_100 ? 'font-semibold text-red-600' : 'font-medium text-gray-800'}>
                ₹{inr(cost.budget)}{cost.over_budget_at_100 && ' — exceeded'}
              </dd>
            </div>
          </dl>
        </div>
      )}

      {live && (
        <p className="mt-4 text-sm font-medium text-green-700">
          Published — targets are live for this month.
        </p>
      )}

      <ConfirmDialog open={overBudgetMsg !== null} onClose={() => setOverBudgetMsg(null)}
                     title="Publish over budget?" variant="warning"
                     message={`${overBudgetMsg ?? ''} Publishing anyway is recorded in the audit trail.`}
                     confirmLabel="Publish anyway"
                     onConfirm={() => publish(true)} />
    </Card>
  );
}

function Gate({ ok, okText, failText }: { ok: boolean; okText: string; failText: string }) {
  return (
    <li className="flex items-start gap-2 text-sm">
      {ok
        ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
        : <X className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />}
      <span className={ok ? 'text-gray-600' : 'text-amber-700'}>{ok ? okText : failText}</span>
    </li>
  );
}
