import { useEffect, useState } from 'react';
import { usePreflight } from '../../hooks/useTargets';
import type { GridRow } from '../../types/target';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Modal } from '../ui/Modal';
import { Textarea } from '../ui/Textarea';
import { cn } from '../../utils/cn';

/** One edit dialog for both paths: an admin override and a reviewer adjustment. The page
 * decides which endpoint the submit lands on; governance (change caps, escalation to the
 * manager) is applied server-side either way. A live preflight shows what the change would
 * do before it is saved. */
export function AdjustTargetModal({ open, row, submitting, onClose, onSubmit }: {
  open: boolean;
  row: GridRow | null;
  submitting: boolean;
  onClose: () => void;
  onSubmit: (value: string, reason: string, rebalance: boolean) => void;
}) {
  const [value, setValue] = useState('');
  const [reason, setReason] = useState('');
  const [rebalance, setRebalance] = useState(false);
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), 350);
    return () => clearTimeout(t);
  }, [value]);

  const { data: preflight } = usePreflight(row?.allocation_id ?? null, debounced);
  const needsReason = Boolean(preflight?.requires_reason) && !reason.trim();
  const blocked = preflight?.outcome === 'blocked';

  if (!row) return null;
  return (
    <Modal open={open} onClose={onClose} title={`Adjust target — ${row.name}`} size="sm">
      <div className="space-y-4">
        <p className="text-sm text-gray-500">
          Current: {Number(row.target ?? 0).toLocaleString('en-IN')}. Within the change cap the
          adjustment applies immediately; beyond it, it routes to your manager for approval.
        </p>
        <Input label="New target" type="number" value={value}
               onChange={(e) => setValue(e.target.value)} placeholder={row.target ?? '0'} />
        {preflight && debounced === value && value !== '' && (
          <p className={cn('rounded-lg px-3 py-2 text-sm', {
            'bg-green-50 text-green-700': preflight.outcome === 'auto',
            'bg-amber-50 text-amber-700': preflight.outcome === 'escalate',
            'bg-red-50 text-red-700': blocked,
          })}>
            {blocked
              ? preflight.message ?? 'This change is blocked by the revision policy.'
              : preflight.outcome === 'escalate'
                ? `Beyond the change cap${preflight.delta_pct ? ` (${preflight.delta_pct}% move)` : ''} — will go to your manager for approval.`
                : `Within the change cap${preflight.delta_pct ? ` (${preflight.delta_pct}% move)` : ''} — applies immediately.`}
          </p>
        )}
        <Textarea label={preflight?.requires_reason ? 'Reason (required)' : 'Reason'}
                  value={reason} onChange={(e) => setReason(e.target.value)}
                  placeholder="Why this number is changing…" rows={2} />
        {needsReason && (
          <p className="text-xs text-red-600">The revision policy requires a reason for this change.</p>
        )}
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input type="checkbox" checked={rebalance} onChange={(e) => setRebalance(e.target.checked)} />
          Rebalance siblings so the parent total stays unchanged
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button loading={submitting} disabled={!value || blocked || needsReason}
                  onClick={() => onSubmit(value, reason, rebalance)}>
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}
