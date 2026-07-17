import { useState } from 'react';
import { useRealign } from '../../hooks/useTargets';
import { useGeographyTypes } from '../../hooks/useEntities';
import type { TargetPlan } from '../../types/target';
import { GeoNodeCombobox, type GeoSelection } from '../entity/GeoNodeCombobox';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

/** Mid-period territory realignment: re-split only the changed subtree. Its committed
 * total stays fixed; the rest of the plan is untouched. */
export function RealignDialog({ plan, open, onClose }: {
  plan: TargetPlan; open: boolean; onClose: () => void;
}) {
  const realign = useRealign();
  const { data: geoTypes } = useGeographyTypes();
  const geoTypeCode = geoTypes?.results?.[0]?.code ?? '';
  const [scope, setScope] = useState<GeoSelection | null>(null);

  return (
    <Modal open={open} onClose={onClose} title="Realign a changed subtree" size="md">
      <div className="space-y-4">
        <p className="text-sm text-gray-500">
          Re-split only the affected subtree — after a territory change mid-period. The
          committed total stays unchanged, the rest of the plan is untouched, and manual
          overrides are surfaced before anything applies.
        </p>
        <GeoNodeCombobox typeCode={geoTypeCode} value={scope} onChange={setScope} label="Changed subtree root" />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button loading={realign.isPending} disabled={!scope}
                  onClick={() => realign.mutate({ planId: plan.id, scopeNodeId: scope!.id }, {
                    onSuccess: () => {
                      notify.success('Realignment ready to review — apply it from the card above the grid.');
                      onClose();
                    },
                    onError: (e) => notify.error(apiErrorMessage(e, 'Could not realign')),
                  })}>
            Generate realignment
          </Button>
        </div>
      </div>
    </Modal>
  );
}
