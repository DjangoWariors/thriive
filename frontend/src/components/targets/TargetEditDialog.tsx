import { useAdjustMine, useModifyAllocation } from '../../hooks/useTargets';
import type { GridRow, TargetPlan } from '../../types/target';
import { AdjustTargetModal } from './AdjustTargetModal';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

/** The one target-edit dialog for both personas. `mode` picks the endpoint: an admin
 * override hits the allocation directly; a reviewer's edit goes through the review path so
 * their task flips to adjusted/escalated. Governance (change caps, escalation) is server-side
 * either way; AdjustTargetModal supplies the live preflight. */
export function TargetEditDialog({ plan, row, mode, onClose }: {
  plan: TargetPlan;
  row: GridRow | null;
  mode: 'admin' | 'reviewer';
  onClose: () => void;
}) {
  const adjust = useAdjustMine();
  const modify = useModifyAllocation();

  function submit(value: string, reason: string, rebalance: boolean) {
    const done = {
      onSuccess: () => { notify.success('Target updated'); onClose(); },
      onError: (e: unknown) => notify.error(apiErrorMessage(e, 'Could not update the target')),
    };
    if (mode === 'reviewer') {
      adjust.mutate({ plan_id: plan.id, allocation_id: row!.allocation_id!,
                      override_value: value, reason, rebalance }, done);
    } else {
      modify.mutate({ id: row!.allocation_id!, body: { override_value: value, reason, rebalance } }, done);
    }
  }

  return (
    <AdjustTargetModal key={row?.allocation_id ?? 'closed'} open={row !== null} row={row}
                       submitting={adjust.isPending || modify.isPending}
                       onClose={onClose} onSubmit={submit} />
  );
}
