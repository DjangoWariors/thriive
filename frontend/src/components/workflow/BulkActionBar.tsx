import { Check, X } from 'lucide-react';
import { Button } from '../ui/Button';

interface BulkActionBarProps {
  count: number;
  onApprove: () => void;
  onReject: () => void;
  onClear: () => void;
  busy?: boolean;
}

/** Sticky action bar shown when one or more approvals are selected (month-end close). */
export function BulkActionBar({ count, onApprove, onReject, onClear, busy }: BulkActionBarProps) {
  if (count === 0) return null;
  return (
    <div className="sticky bottom-4 z-10 mx-auto flex max-w-2xl items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-lg">
      <p className="text-sm font-medium text-gray-700">
        {count} selected
        <button type="button" className="ml-2 text-xs text-gray-400 hover:text-gray-600" onClick={onClear}>
          Clear
        </button>
      </p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" icon={<X className="h-4 w-4" />} onClick={onReject} disabled={busy}>
          Reject all
        </Button>
        <Button size="sm" icon={<Check className="h-4 w-4" />} onClick={onApprove} loading={busy}>
          Approve all
        </Button>
      </div>
    </div>
  );
}
