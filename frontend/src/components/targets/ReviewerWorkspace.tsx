import { useState } from 'react';
import { ArrowLeft, ClipboardCheck } from 'lucide-react';
import { useAcceptTask, useReviewTasks } from '../../hooks/useTargets';
import type { ReviewTask, TargetPlan } from '../../types/target';
import { PlanGridPanel } from './PlanGridPanel';
import { ActualsPanel } from './ActualsPanel';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { PageHeader } from '../ui/PageHeader';
import { SimpleTable, type SimpleColumn } from '../ui/SimpleTable';
import { StatusBadge } from '../ui/StatusBadge';
import { Tabs } from '../ui/Tabs';
import { notify } from '../../utils/notify';

/** The field reviewer's plan screen: their review tasks with inline Accept on top, their
 * territory grid (inline edit → the review path) and actuals below. Everything a reviewer
 * does lives here — no stepper, no admin controls, no tab-bouncing. */
export function ReviewerWorkspace({ plan, onBack }: { plan: TargetPlan; onBack: () => void }) {
  const [tab, setTab] = useState<'territory' | 'actuals'>('territory');
  const [kpiId, setKpiId] = useState<number>(plan.kpis[0]?.kpi ?? 0);
  const tasks = useReviewTasks({ plan: plan.id });
  const accept = useAcceptTask();
  const myTasks = tasks.data?.results ?? [];
  const openCount = myTasks.filter((t) => t.status === 'pending').length;

  const columns: SimpleColumn<ReviewTask>[] = [
    { header: 'Territory', render: (t) => <span className="font-medium text-gray-900">{t.node_name}</span> },
    { header: 'Level', render: (t) => <Badge variant="default">{t.node_level}</Badge> },
    { header: 'Status', align: 'center', render: (t) => <StatusBadge status={t.status} /> },
    {
      header: '', align: 'right',
      render: (t) => (t.status === 'pending' ? (
        <Button variant="ghost" size="sm" loading={accept.isPending}
                onClick={() => accept.mutate({ taskId: t.id }, {
                  onSuccess: () => notify.success('Accepted — thank you'),
                })}>
          Accept
        </Button>
      ) : null),
    },
  ];

  return (
    <div className="p-6">
      <PageHeader
        className="mb-5"
        title={plan.name}
        description={`${plan.period_code} · ${plan.root_geography_name} · ${plan.kpis.length} KPI(s)`}
        actions={<>
          <Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} onClick={onBack}>All plans</Button>
          <StatusBadge status={plan.status} />
        </>}
      />

      {myTasks.length > 0 && (
        <Card className="mb-4 border-amber-200 bg-amber-50/40">
          <div className="mb-2 flex items-center gap-2">
            <ClipboardCheck className="h-4 w-4 text-amber-600" />
            <h3 className="text-sm font-semibold text-gray-800">Your review</h3>
            {openCount > 0 && <Badge variant="warning" size="sm">{openCount} open</Badge>}
          </div>
          <p className="mb-3 text-xs text-gray-600">
            Check the numbers for your territory below. Edit any number — within the change cap
            it applies immediately; bigger moves go to your manager. Accept when the numbers work.
          </p>
          <SimpleTable columns={columns} rows={myTasks} rowKey={(t) => t.id} />
        </Card>
      )}

      <Card padding="none">
        <div className="px-4 pt-2">
          <Tabs activeTab={tab} onChange={(v) => setTab(v as 'territory' | 'actuals')}
                tabs={[{ value: 'territory', label: 'My territory' },
                       { value: 'actuals', label: 'Actuals' }]} />
        </div>
        {tab === 'territory'
          ? <PlanGridPanel plan={plan} kpiId={kpiId} setKpiId={setKpiId} isAdmin={false} />
          : <ActualsPanel plan={plan} kpiId={kpiId} setKpiId={setKpiId} />}
      </Card>
    </div>
  );
}
