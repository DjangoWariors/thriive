import { GitBranchPlus, Package } from 'lucide-react';
import { useStartRun } from '../../hooks/useTargets';
import type { PlanRun, TargetPlan } from '../../types/target';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { StagedRunReview } from './StagedRunReview';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

const COPY = {
  spatial: {
    title: 'Territory split',
    body: 'Cascade each top number down the geography tree using the KPI\'s split recipe. '
      + 'The result stages first — nothing changes until you apply it.',
    button: 'Generate split',
  },
  product: {
    title: 'Product split',
    body: 'Split each territory\'s number across the plan\'s product groups: fixed shares off '
      + 'the top, the remainder by local product mix. Stages first, applies on your say-so.',
    button: 'Generate product split',
  },
} as const;

/** Stages 2/3 — generate a split and review/apply it in the same panel. */
export function SplitStage({ plan, kind, stagedRun, running, editable, done }: {
  plan: TargetPlan;
  kind: 'spatial' | 'product';
  stagedRun: PlanRun | null;
  running: boolean;
  editable: boolean;
  done: boolean;
}) {
  const startRun = useStartRun();
  const copy = COPY[kind];
  const busy = running || startRun.isPending;

  return (
    <div className="space-y-3">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-800">{copy.title}</h3>
            <p className="mt-0.5 text-xs text-gray-500">{copy.body}</p>
            {done && !stagedRun && (
              <p className="mt-1 text-xs font-medium text-green-700">
                Applied — the numbers are on the plan. Generate again to re-split.
              </p>
            )}
          </div>
          {editable && !stagedRun && (
            <Button variant={done ? 'outline' : 'primary'} size="sm"
                    icon={kind === 'spatial' ? <GitBranchPlus className="h-4 w-4" /> : <Package className="h-4 w-4" />}
                    loading={busy}
                    onClick={() => startRun.mutate({ planId: plan.id, kind }, {
                      onError: (e) => notify.error(apiErrorMessage(e, `Could not generate the ${copy.title.toLowerCase()}`)),
                    })}>
            {busy ? 'Generating…' : copy.button}
            </Button>
          )}
        </div>
        {!editable && !done && (
          <p className="mt-2 text-xs text-gray-400">Splits are generated while the plan is a draft.</p>
        )}
      </Card>
      {stagedRun && <StagedRunReview run={stagedRun} />}
    </div>
  );
}
