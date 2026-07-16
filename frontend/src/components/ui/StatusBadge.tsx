import { Badge } from './Badge';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'purple';

interface StatusConfig {
  variant: BadgeVariant;
  label: string;
}

interface StatusBadgeProps {
  status: string;
  className?: string;
}

const STATUS_MAP: Record<string, StatusConfig> = {
  active: { variant: 'success', label: 'Active' },
  inactive: { variant: 'default', label: 'Inactive' },
  pending: { variant: 'warning', label: 'Pending' },
  approved: { variant: 'success', label: 'Approved' },
  rejected: { variant: 'danger', label: 'Rejected' },
  computed: { variant: 'info', label: 'Computed' },
  locked: { variant: 'purple', label: 'Locked' },
  draft: { variant: 'default', label: 'Draft' },
  disputed: { variant: 'danger', label: 'Disputed' },
  suspended: { variant: 'danger', label: 'Suspended' },
  onboarding: { variant: 'warning', label: 'Onboarding' },
  vacant: { variant: 'purple', label: 'Vacant' },
  in_review: { variant: 'info', label: 'In Review' },
  escalated: { variant: 'warning', label: 'Escalated' },
  auto_approved: { variant: 'success', label: 'Auto-approved' },
  cancelled: { variant: 'default', label: 'Cancelled' },
  skipped: { variant: 'default', label: 'Skipped' },
  queued: { variant: 'info', label: 'Queued' },
  running: { variant: 'info', label: 'Running' },
  completed: { variant: 'success', label: 'Completed' },
  failed: { variant: 'danger', label: 'Failed' },
  published: { variant: 'success', label: 'Published' },
  closed: { variant: 'default', label: 'Closed' },
  // Payout runs & gatekeeper
  computing: { variant: 'info', label: 'Computing' },
  under_review: { variant: 'warning', label: 'Under Review' },
  paid: { variant: 'success', label: 'Paid' },
  superseded: { variant: 'default', label: 'Superseded' },
  passed: { variant: 'success', label: 'Passed' },
  exempted: { variant: 'purple', label: 'Exempted' },
  not_applicable: { variant: 'default', label: '—' },
  // Integration batches
  accepted: { variant: 'success', label: 'Accepted' },
  partial: { variant: 'warning', label: 'Partial' },
  // Payout cycles
  open: { variant: 'info', label: 'Open' },
  finalizing: { variant: 'warning', label: 'Finalizing' },
  disbursed: { variant: 'success', label: 'Disbursed' },
  // Payout hold status
  held: { variant: 'warning', label: 'Held' },
  released: { variant: 'info', label: 'Released' },
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config: StatusConfig = STATUS_MAP[status.toLowerCase()] ?? {
    variant: 'default',
    label: status,
  };

  return (
    <Badge variant={config.variant} className={className}>
      {config.label}
    </Badge>
  );
}
