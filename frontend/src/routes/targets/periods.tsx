import { useState } from 'react';
import { useNavigate } from 'react-router';
import { ArrowLeft, CalendarPlus, CalendarRange } from 'lucide-react';
import { usePlanYears, usePeriodTree, useGenerateYear } from '../../hooks/useTargets';
import { useAuth } from '../../hooks/useAuth';
import { useRBAC } from '../../hooks/useRBAC';
import type { TargetPeriod, TargetPeriodNode } from '../../types/target';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Card } from '../../components/ui/Card';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Modal } from '../../components/ui/Modal';
import { Spinner } from '../../components/ui/Spinner';
import { EmptyState } from '../../components/ui/EmptyState';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import { TreeTable, type TreeColumn } from '../../components/data/TreeTable';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

const MONTHS = [
  ['1', 'January (calendar year)'], ['2', 'February'], ['3', 'March'],
  ['4', 'April (India FMCG default)'], ['5', 'May'], ['6', 'June'],
  ['7', 'July'], ['8', 'August'], ['9', 'September'],
  ['10', 'October'], ['11', 'November'], ['12', 'December'],
];

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

export default function PlanningCalendarPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { canWrite } = useRBAC();
  // Calendar mutations are a planning-admin act (HO user, not placed in the org tree).
  const writable = canWrite('target_management') && !user?.entity_info;
  const { data: yearsResp, isLoading } = usePlanYears();
  const years = yearsResp?.results ?? [];
  const [genOpen, setGenOpen] = useState(false);

  return (
    <div className="p-6">
      <button onClick={() => navigate('/targets')} className="mb-3 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-primary">
        <ArrowLeft className="h-4 w-4" /> Back to targets
      </button>
      <PageHeader
        className="mb-5"
        title="Planning calendar"
        description="Your plan years — each a fiscal year of 12 months. Targets are always set against the months. A month's status moves on its own: Published when a target plan goes live, Locked when its payout cycle is finalized, Closed when the cycle closes."
        actions={writable && (
          <Button icon={<CalendarPlus className="h-4 w-4" />} onClick={() => setGenOpen(true)}>New plan year</Button>
        )}
      />

      {isLoading ? (
        <TableSkeleton/>
      ) : years.length === 0 ? (
        <Card>
          <EmptyState
            icon={CalendarRange}
            title="No plan years yet"
            description="A plan year is the fiscal calendar your targets hang off — 12 months under one fiscal-year root. Create one to get started — you can set monthly targets against it next."
            actionLabel={writable ? 'Create your first plan year' : undefined}
            onAction={writable ? () => setGenOpen(true) : undefined}
          />
        </Card>
      ) : (
        <div className="space-y-5">
          {years.map((year) => <PlanYearCard key={year.id} year={year} />)}
        </div>
      )}

      <GenerateYearModal open={genOpen} onClose={() => setGenOpen(false)} />
    </div>
  );
}

function PlanYearCard({ year }: { year: TargetPeriod }) {
  const { data: tree, isLoading } = usePeriodTree(year.id);

  const columns: TreeColumn<TargetPeriodNode>[] = [
    {
      key: 'period', header: 'Period',
      render: (n) => (
        <span className="flex items-center gap-2">
          <span className="font-medium text-gray-900">{n.name}</span>
          <code className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-500">{n.code}</code>
        </span>
      ),
    },
    { key: 'type', header: 'Type', render: (n) => <span className="capitalize text-gray-600">{n.period_type}</span> },
    {
      key: 'dates', header: 'Dates',
      render: (n) => <span className="text-gray-500">{fmtDate(n.start_date)} – {fmtDate(n.end_date)}</span>,
    },
    {
      key: 'wd', header: 'Working days', align: 'center',
      render: (n) => <span className="text-gray-500">{n.working_days ?? '—'}</span>,
    },
    {
      // Derived, read-only: plan publish → published, cycle finalize → locked, cycle close → closed.
      key: 'status', header: 'Status', align: 'center',
      render: (n) => n.period_type === 'annual' ? null : <StatusBadge status={n.status}/>,
    },
  ];

  return (
    <Card padding="none">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <div className="flex items-center gap-2">
          <CalendarRange className="h-4 w-4 text-primary" />
          <span className="font-semibold text-gray-900">{year.name}</span>
          {year.fiscal_year && <span className="text-sm text-gray-400">FY {year.fiscal_year}</span>}
        </div>
      </div>
      {isLoading || !tree ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <TreeTable roots={[tree]} getId={(n) => n.id} getChildren={(n) => n.children} columns={columns} defaultExpandedDepth={1} />
      )}
    </Card>
  );
}

function GenerateYearModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const generate = useGenerateYear();
  const [fiscalYear, setFiscalYear] = useState('');
  const [startMonth, setStartMonth] = useState('4');
  const [workingDays, setWorkingDays] = useState('26');

  function submit() {
    generate.mutate(
      { fiscal_year: fiscalYear.trim(), start_month: Number(startMonth), working_days_per_month: Number(workingDays) },
      {
        onSuccess: () => { notify.success('Plan year created — 12 months under the fiscal-year root'); onClose(); setFiscalYear(''); },
        onError: (e) => notify.error(apiErrorMessage(e, 'Could not create the plan year')),
      },
    );
  }

  return (
    <Modal open={open} onClose={onClose} title="New plan year" size="md">
      <div className="space-y-4">
        <p className="text-sm text-gray-500">
          This creates the whole calendar in one go: the fiscal-year root and its 12 months.
        </p>
        <Input label="Fiscal year" value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value)}
          placeholder="e.g. 2026-27" hint="A label for the year. The start year is read from the first four digits." />
        <Select label="Fiscal year starts in" value={startMonth} onChange={(e) => setStartMonth(e.target.value)}
          options={MONTHS.map(([v, l]) => ({ value: v, label: l }))} />
        <Input label="Working days per month" type="number" value={workingDays} onChange={(e) => setWorkingDays(e.target.value)}
          hint="Used for run-rate and pro-rated eligibility maths. Defaults to 26 (six-day week)." />
        <div className="flex justify-end gap-2 border-t border-gray-100 pt-4">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} loading={generate.isPending} disabled={!fiscalYear.trim()}>Create plan year</Button>
        </div>
      </div>
    </Modal>
  );
}
