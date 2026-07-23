import { Check, ChevronRight, Clock, X } from 'lucide-react';
import { cn } from '../../utils/cn';
import { Avatar } from '../ui/Avatar';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { formatCurrency, formatDate, formatRelative } from '../../utils/format';
import type { PendingApproval } from '../../types/workflow';

interface ApprovalCardProps {
  item: PendingApproval;
  selected: boolean;
  onToggleSelect: () => void;
  onOpen: () => void;
  onApprove: () => void;
  onReject: () => void;
  canDecide: boolean;
}

export function ApprovalCard({
  item, selected, onToggleSelect, onOpen, onApprove, onReject, canDecide,
}: ApprovalCardProps) {
  const s = item.subject_summary;
  const title = (item.context_data.title as string) || s.entity_name || `Request #${item.id}`;
  const impact = item.context_data.impact_amount;

  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-xl border bg-white p-3 transition-colors',
        selected ? 'border-primary ring-1 ring-primary' : 'border-gray-200 hover:border-gray-300',
      )}
    >
      {canDecide && (
        <input
          type="checkbox"
          className="h-4 w-4 shrink-0 accent-primary"
          checked={selected}
          onChange={onToggleSelect}
          aria-label="Select for bulk action"
        />
      )}

      <button type="button" onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-3 text-left">
        <Avatar name={s.entity_name || title} size="md" />
        <div className="min-w-0">
          <p className="truncate font-medium text-gray-900">{title}</p>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
            {s.category && <Badge variant="purple" size="sm">{s.category}</Badge>}
            <span>{item.current_step_name ?? item.definition_code}</span>
            {item.initiated_by_name && <span>· by {item.initiated_by_name}</span>}
            <span>· {formatRelative(item.created_at)}</span>
          </div>
        </div>
      </button>

      <div className="hidden shrink-0 text-right sm:block">
        {impact != null && impact !== '' && (
          <p className="text-sm font-semibold text-gray-900">{formatCurrency(impact)}</p>
        )}
        <SlaChip sla={item.sla_due_at} overdue={item.is_overdue} />
      </div>

      <div className="flex shrink-0 gap-1">
        {/* The card body opens the detail too, but a click target with no affordance reads
            as decoration — approvers were deciding without ever seeing the request. */}
        <Button variant="ghost" size="sm" aria-label="View details" onClick={onOpen}>
          <ChevronRight className="h-4 w-4 text-gray-400" />
        </Button>
        {canDecide && (
          <>
            <Button variant="ghost" size="sm" aria-label="Approve" onClick={onApprove}>
              <Check className="h-4 w-4 text-success" />
            </Button>
            <Button variant="ghost" size="sm" aria-label="Reject" onClick={onReject}>
              <X className="h-4 w-4 text-danger" />
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

function SlaChip({ sla, overdue }: { sla: string | null; overdue: boolean }) {
  if (!sla) return null;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium',
        overdue ? 'bg-danger/10 text-danger' : 'bg-gray-100 text-gray-500',
      )}
    >
      <Clock className="h-3 w-3" />
      {overdue ? 'Overdue' : `Due ${formatDate(sla)}`}
    </span>
  );
}
