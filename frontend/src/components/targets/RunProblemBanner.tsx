import { AlertTriangle } from 'lucide-react';
import type { PlanRun } from '../../types/target';
import { isRunStalled } from '../../utils/planRun';

/** A run that failed or stopped reporting has no other voice in the workspace: the stage
 * panel only ever renders staged results, so without this the button would just quietly
 * re-enable and the admin would retry blind. The stage's own action button is the retry. */
export function RunProblemBanner({ run }: { run: PlanRun }) {
  const stalled = isRunStalled(run);
  return (
    <div className="mt-3 flex items-start gap-2 rounded-md border border-danger-100 bg-danger-50 p-3">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
      <div>
        <p className="text-sm font-medium text-danger">
          {stalled ? 'This run stopped responding' : 'This run failed'}
        </p>
        <p className="mt-0.5 text-xs text-gray-600">
          {stalled
            ? 'No result came back from the background worker. Start it again — if it stalls '
              + 'a second time, ask your administrator to check the worker processes.'
            : run.error || 'The background worker reported an error. Start the run again.'}
        </p>
      </div>
    </div>
  );
}
