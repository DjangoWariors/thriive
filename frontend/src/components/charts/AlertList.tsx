import { AlertTriangle, AlertCircle, ChevronRight, Info } from 'lucide-react';
import { Card } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/EmptyState';
import { cn } from '../../utils/cn';
import type { DashboardAlert } from '../../types/achievement';

const SEVERITY = {
  critical: { variant: 'danger' as const, icon: AlertCircle, ring: 'border-l-danger' },
  warning: { variant: 'warning' as const, icon: AlertTriangle, ring: 'border-l-warning' },
  info: { variant: 'info' as const, icon: Info, ring: 'border-l-blue-400' },
};

interface AlertListProps {
  alerts: DashboardAlert[];
  /** Total open alerts for the period. When it exceeds the list, say so — otherwise the
   *  panel silently disagrees with the "open alerts" metric card. */
  totalOpen?: number;
  onAcknowledge?: (id: number) => void;
  onAcknowledgeAll?: () => void;
  onOpen?: (alert: DashboardAlert) => void;
}

export function AlertList({ alerts, totalOpen, onAcknowledge, onAcknowledgeAll, onOpen }: AlertListProps) {
  const hidden = Math.max((totalOpen ?? alerts.length) - alerts.length, 0);

  return (
    <Card title="Alerts" subtitle="Target-at-risk, no-sale & coverage signals" padding="none"
          actions={onAcknowledgeAll && alerts.length > 1 ? (
            <Button variant="ghost" size="sm" onClick={onAcknowledgeAll}>
              Mark all as seen
            </Button>
          ) : undefined}>
      {alerts.length === 0 ? (
        <EmptyState icon={Info} title="No open alerts" description="Everything is on track." />
      ) : (
        <>
          <div className="divide-y divide-gray-100">
            {alerts.map((a) => {
              const cfg = SEVERITY[a.severity];
              const Icon = cfg.icon;
              return (
                <div key={a.id} className={cn('flex items-center gap-3 border-l-4 px-4 py-3', cfg.ring)}>
                  <Icon className={cn('shrink-0', a.severity === 'critical' ? 'text-danger' : a.severity === 'warning' ? 'text-warning' : 'text-blue-500')} size={18} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium text-gray-900">{a.entity_name}</p>
                      <Badge variant={cfg.variant} size="sm">{a.rule_code}</Badge>
                      {/* Alerts are raised per KPI — without the code, one person's rows
                          all read as duplicates of each other. */}
                      {a.kpi_code && (
                        <span className="shrink-0 text-[11px] uppercase tracking-wide text-gray-400">
                          {a.kpi_code}
                        </span>
                      )}
                    </div>
                    <p className="truncate text-xs text-gray-500">{a.message}</p>
                  </div>
                  {onOpen && (
                    <Button variant="ghost" size="sm" iconRight={<ChevronRight className="h-3.5 w-3.5" />}
                            onClick={() => onOpen(a)}
                            title="Open the achievement behind this alert">
                      View
                    </Button>
                  )}
                  {onAcknowledge && (
                    <Button variant="ghost" size="sm" onClick={() => onAcknowledge(a.id)}
                            title="Mark as seen — it stays in the register and resolves on its own when the number recovers">
                      Mark as seen
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
          {hidden > 0 && (
            <p className="border-t border-gray-100 px-4 py-2 text-xs text-gray-400">
              Showing {alerts.length} of {totalOpen} open alerts.
            </p>
          )}
        </>
      )}
    </Card>
  );
}
