import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  AlertTriangle, CalendarDays, ChevronRight, ClipboardCheck, Crosshair, GitBranchPlus, Plus,
  ShieldCheck, SlidersHorizontal, Users, type LucideIcon,
} from 'lucide-react';
import { usePeriodTree, usePlanYears, usePlans, usePersonView, useReviewTasks } from '../../hooks/useTargets';
import { useKpiDefinitions } from '../../hooks/useKpi';
import { useAuth } from '../../hooks/useAuth';
import { useRBAC } from '../../hooks/useRBAC';
import type { TargetPlan } from '../../types/target';
import { EntityCombobox, type EntitySelection } from '../../components/entity/EntityCombobox';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { EmptyState } from '../../components/ui/EmptyState';
import { PageHeader } from '../../components/ui/PageHeader';
import { Pagination } from '../../components/ui/Pagination';
import { ProgressBar } from '../../components/ui/ProgressBar';
import { Select } from '../../components/ui/Select';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Tabs } from '../../components/ui/Tabs';
import { CardGridSkeleton, TableSkeleton } from '../../components/ui/Skeleton';
import { defaultMonthId, flattenPeriods } from '../../utils/periods';

function inr(value: string | null): string {
  if (value === null || value === '') return '—';
  return Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

export default function TargetsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { canWrite } = useRBAC();
  const writable = canWrite('target_management');
  const isAdmin = writable && !user?.entity_info;
  const [tab, setTab] = useState<'plans' | 'person' | 'setup'>('plans');

  return (
    <div className="p-6">
      <PageHeader
        className="mb-5"
        title="Target plans"
        description="Each plan is one monthly exercise: top number → split → review → publish. Targets live on territories; every person's number is derived from what they own."
        actions={isAdmin && (
          <>
            <Button variant="outline" icon={<CalendarDays className="h-4 w-4" />} onClick={() => navigate('/targets/periods')}>
              Planning calendar
            </Button>
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => navigate('/targets/new')}>New plan</Button>
          </>
        )}
      />

      {!isAdmin && <MyReviews onOpen={(planId) => navigate(`/targets/${planId}`)} />}

      <Tabs className="mb-4" activeTab={tab} onChange={(v) => setTab(v as 'plans' | 'person' | 'setup')}
            tabs={[{ value: 'plans', label: 'Plans' }, { value: 'person', label: 'By person' },
                   ...(isAdmin ? [{ value: 'setup', label: 'Setup' }] : [])]} />

      {tab === 'plans'
        ? <PlanList isAdmin={isAdmin} onOpen={(id) => navigate(`/targets/${id}`)} onNew={() => navigate('/targets/new')} />
        : tab === 'person'
          ? <TeamView onOpenCalendar={isAdmin ? () => navigate('/targets/periods') : undefined} />
          : <SetupTab onNavigate={navigate} />}
    </div>
  );
}

// ── setup (rarely-touched configuration) ──────────────────────────────────────
function SetupTab({ onNavigate }: { onNavigate: (path: string) => void }) {
  const cards: { icon: LucideIcon; title: string; body: string; path: string }[] = [
    {
      icon: CalendarDays, title: 'Planning calendar', path: '/targets/periods',
      body: 'The fiscal years and months plans anchor to. Generate a whole plan year in one go.',
    },
    {
      icon: SlidersHorizontal, title: 'Split recipes', path: '/targets/recipes',
      body: 'How system numbers are blended — the weight components, growth and rounding a split uses.',
    },
    {
      icon: ShieldCheck, title: 'Change caps', path: '/targets/revision-policies',
      body: 'Who may move a number, and by how much — auto-approve bands, hard ceilings, freezes.',
    },
  ];
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {cards.map((c) => (
        <button key={c.path} type="button" onClick={() => onNavigate(c.path)} className="text-left">
          <Card className="h-full transition-shadow hover:shadow-md">
            <div className="flex items-start justify-between gap-2">
              <c.icon className="h-5 w-5 text-primary" />
              <ChevronRight className="h-4 w-4 text-gray-300" />
            </div>
            <p className="mt-3 font-semibold text-gray-900">{c.title}</p>
            <p className="mt-1 text-xs leading-relaxed text-gray-500">{c.body}</p>
          </Card>
        </button>
      ))}
    </div>
  );
}

// ── plan list ─────────────────────────────────────────────────────────────────
function PlanList({ isAdmin, onOpen, onNew }: { isAdmin: boolean; onOpen: (id: number) => void; onNew: () => void }) {
  const [page, setPage] = useState(1);
  const { data, isLoading, error, refetch } = usePlans({ page });
  const plans = data?.results ?? [];

  if (isLoading) return <CardGridSkeleton />;
  if (error) {
    return (
      <Card>
        <EmptyState icon={AlertTriangle} title="Could not load plans"
                    description="Something went wrong fetching the plan list."
                    actionLabel="Retry" onAction={() => void refetch()} />
      </Card>
    );
  }
  if (plans.length === 0) {
    return (
      <Card>
        <EmptyState icon={GitBranchPlus} title="No plan yet"
                    description="A plan is one planning exercise — a period, a territory, and the KPIs with their split logic."
                    {...(isAdmin ? { actionLabel: 'Create the first plan', onAction: onNew } : {})} />
      </Card>
    );
  }
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {plans.map((plan) => <PlanCard key={plan.id} plan={plan} onOpen={() => onOpen(plan.id)} />)}
      </div>
      <Pagination count={data?.count ?? 0} page={page} onPageChange={setPage} className="mt-2 border-t-0" />
    </>
  );
}

function PlanCard({ plan, onOpen }: { plan: TargetPlan; onOpen: () => void }) {
  const stages = ['spatial', ...(plan.product_scope.length ? ['product'] : [])];
  const done = stages.filter((s) => plan.progress.committed_stages.includes(s as never)).length;
  const reviewTotal = plan.progress.review.total;
  const reviewDone = reviewTotal - plan.progress.review.open;

  return (
    <button type="button" onClick={onOpen} className="text-left">
      <Card className="h-full transition-shadow hover:shadow-md">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="font-semibold text-gray-900">{plan.name}</p>
            <p className="mt-0.5 text-xs text-gray-500">{plan.period_code} · {plan.root_geography_name}</p>
          </div>
          <StatusBadge status={plan.status} />
        </div>
        <div className="mt-3 flex flex-wrap gap-1">
          {plan.kpis.map((k) => <Badge key={k.id} variant="default">{k.kpi_code}</Badge>)}
        </div>
        <div className="mt-4 space-y-2">
          <div>
            <div className="mb-1 flex justify-between text-xs text-gray-500">
              <span>Pipeline</span><span>{done}/{stages.length} stages committed</span>
            </div>
            <ProgressBar value={stages.length ? (done / stages.length) * 100 : 0} />
          </div>
          {reviewTotal > 0 && (
            <div>
              <div className="mb-1 flex justify-between text-xs text-gray-500">
                <span>Field review</span><span>{reviewDone}/{reviewTotal} answered</span>
              </div>
              <ProgressBar value={(reviewDone / reviewTotal) * 100} />
            </div>
          )}
        </div>
      </Card>
    </button>
  );
}

// ── my review tasks (reviewers) ───────────────────────────────────────────────
function MyReviews({ onOpen }: { onOpen: (planId: number) => void }) {
  const { data } = useReviewTasks({ status: 'pending' });
  const tasks = data?.results ?? [];
  if (tasks.length === 0) return null;
  return (
    <Card className="mb-5 border-amber-200 bg-amber-50">
      <div className="flex items-start gap-3">
        <ClipboardCheck className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-amber-800">
            {tasks.length} territory target{tasks.length > 1 ? 's are' : ' is'} waiting for your review
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {tasks.map((t) => (
              <Button key={t.id} variant="outline" size="sm" onClick={() => onOpen(t.plan)}>
                {t.node_name} · {t.plan_code}
              </Button>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

// ── read-only person view (User × Retailer × SKU) ─────────────────────────────
function TeamView({ onOpenCalendar }: { onOpenCalendar?: () => void }) {
  const { data: yearsResp } = usePlanYears();
  const { data: kpisResp } = useKpiDefinitions({ page_size: 200 });
  const years = yearsResp?.results ?? [];
  const kpis = kpisResp?.results ?? [];
  const [yearId, setYearId] = useState<number | null>(null);
  const [periodId, setPeriodId] = useState<number | null>(null);
  const [kpiId, setKpiId] = useState<number | null>(null);
  const [person, setPerson] = useState<EntitySelection | null>(null);

  const effYear = yearId ?? years[0]?.id ?? null;
  const { data: yearTree } = usePeriodTree(effYear);
  const periodOptions = useMemo(() => flattenPeriods(yearTree), [yearTree]);
  // Targets are monthly — default to the month covering today, never the annual root.
  const effPeriod = periodId !== null && periodOptions.some((o) => Number(o.value) === periodId)
    ? periodId : defaultMonthId(yearTree);
  const effKpi = kpiId ?? kpis[0]?.id ?? null;

  const params = person && effPeriod && effKpi
    ? { entity_id: person.id, period_id: effPeriod, kpi_id: effKpi } : null;
  const { data, isLoading, error } = usePersonView(params);

  if (yearsResp && years.length === 0) {
    return (
      <Card>
        <EmptyState icon={CalendarDays} title="No plan years yet"
                    description="Person targets are read per period — generate a plan year in the Planning calendar first."
                    {...(onOpenCalendar ? { actionLabel: 'Open the Planning calendar', onAction: onOpenCalendar } : {})} />
      </Card>
    );
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-44">
          <Select label="Plan year" value={String(effYear ?? '')}
                  onChange={(e) => { setYearId(Number(e.target.value)); setPeriodId(null); }}
                  options={years.map((p) => ({ value: String(p.id), label: p.name }))} />
        </div>
        <div className="w-64">
          <Select label="Period" value={String(effPeriod ?? '')}
                  onChange={(e) => setPeriodId(Number(e.target.value))}
                  options={periodOptions} />
        </div>
        <div className="w-56">
          <Select label="KPI" value={String(effKpi ?? '')} onChange={(e) => setKpiId(Number(e.target.value))}
                  options={kpis.map((k) => ({ value: String(k.id), label: k.name }))} />
        </div>
        <div className="w-72">
          <EntityCombobox value={person} onChange={setPerson} label="Person" placeholder="Search a person or team…" />
        </div>
      </div>
      <p className="mb-4 text-xs text-gray-400">A person's target is derived from the territories they own — it is planned by territory, not edited here.</p>

      {!params ? (
        <Card><EmptyState icon={Users} title="Pick a person" description="See the target a person carries, rolled up from the retailers/territories they own." /></Card>
      ) : isLoading ? (
        <TableSkeleton />
      ) : error ? (
        <Card>
          <EmptyState icon={AlertTriangle} title="Could not load this person's targets"
                      description="They may be outside your area, or the request failed — try again." />
        </Card>
      ) : data ? (
        <>
          <div className="mb-5 grid grid-cols-2 gap-4 md:grid-cols-3">
            <SummaryCard label={`${data.entity} — total target`} value={`₹${inr(data.target)}`} color="border-t-primary" />
            <SummaryCard label="Territories owned" value={String(data.owned_node_count)} color="border-t-blue-500" />
            <SummaryCard label="Allocations" value={String(data.rows.length)} color="border-t-green-500" />
          </div>
          <Card>
            {data.rows.length === 0 ? (
              <EmptyState icon={Crosshair} title="No targets yet" description="No target has been planned on the territories this person owns." />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
                    <th className="py-2 pr-4 font-medium">Retailer / territory</th>
                    <th className="py-2 pr-4 font-medium">SKU group</th>
                    <th className="py-2 pr-4 font-medium">Channel</th>
                    <th className="py-2 pr-4 text-right font-medium">Target</th>
                    <th className="py-2 text-center font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.allocation_id} className="border-b border-gray-100">
                      <td className="py-2 pr-4 font-medium text-gray-900">{r.geography_node ?? r.geography_code ?? '—'}</td>
                      <td className="py-2 pr-4 text-gray-600">{r.sku_group ?? 'All'}</td>
                      <td className="py-2 pr-4 text-gray-600">{r.channel ?? 'All'}</td>
                      <td className="py-2 pr-4 text-right font-medium text-gray-800">₹{inr(r.target)}</td>
                      <td className="py-2 text-center"><StatusBadge status={r.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </>
      ) : (
        <Card><EmptyState icon={Users} title="No target" description="This person owns no territory with a target this period." /></Card>
      )}
    </>
  );
}

function SummaryCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className={`rounded-xl border border-gray-200 border-t-4 bg-white p-4 ${color}`}>
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-1 text-xl font-bold text-gray-900">{value}</p>
    </div>
  );
}
