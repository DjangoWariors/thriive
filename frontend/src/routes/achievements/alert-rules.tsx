import { useState } from 'react';
import { useNavigate } from 'react-router';
import { ArrowLeft, Plus, Pencil, BellRing } from 'lucide-react';
import { useAlertRules, useSaveAlertRule } from '../../hooks/useAchievements';
import { useChannels, useEntityTypes } from '../../hooks/useEntities';
import { useKpiDefinitions } from '../../hooks/useKpi';
import type { AlertRule } from '../../types/achievement';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Modal } from '../../components/ui/Modal';
import { EmptyState } from '../../components/ui/EmptyState';
import { PageHeader } from '../../components/ui/PageHeader';
import { SimpleTable } from '../../components/ui/SimpleTable';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import { cn } from '../../utils/cn';

const METRICS: Array<{ value: AlertRule['metric']; label: string }> = [
  { value: 'achievement_pct', label: 'Achievement %' },
  { value: 'projected_pct', label: 'Projected month-end %' },
  { value: 'gap_to_target', label: 'Gap to target' },
  { value: 'required_run_rate', label: 'Required run rate' },
  { value: 'no_sale_days', label: 'Days since last sale' },
  { value: 'growth_pct', label: 'Growth vs last year' },
];

const COMPARATORS: Array<{ value: AlertRule['comparator']; label: string }> = [
  { value: 'lt', label: '< below' },
  { value: 'lte', label: '≤ at or below' },
  { value: 'gt', label: '> above' },
  { value: 'gte', label: '≥ at or above' },
  { value: 'eq', label: '= exactly' },
];

const SEVERITIES: Array<{ value: AlertRule['severity']; label: string }> = [
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'critical', label: 'Critical' },
];

function severityVariant(s: AlertRule['severity']): 'info' | 'warning' | 'danger' {
  return s === 'critical' ? 'danger' : s === 'warning' ? 'warning' : 'info';
}

function metricLabel(metric: AlertRule['metric']): string {
  return METRICS.find((m) => m.value === metric)?.label ?? metric;
}

export default function AlertRulesPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useAlertRules();
  const rules = data?.results ?? [];
  const [editing, setEditing] = useState<AlertRule | null>(null);
  const [open, setOpen] = useState(false);

  return (
    <div className="p-6">
      <button onClick={() => navigate('/achievements')} className="mb-3 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-primary">
        <ArrowLeft className="h-4 w-4" /> Back to achievements
      </button>
      <PageHeader
        className="mb-5"
        title="Alert rules"
        description="Threshold rules evaluated on every achievement run — target-at-risk, no-sale and coverage signals surface on the dashboard when a rule breaches."
        actions={
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => { setEditing(null); setOpen(true); }}>New rule</Button>
        }
      />

      {isLoading ? (
        <TableSkeleton rows={5} />
      ) : rules.length === 0 ? (
        <Card><EmptyState icon={BellRing} title="No alert rules yet" description="Add one to flag entities pacing below plan, going quiet, or losing ground vs last year." /></Card>
      ) : (
        <Card padding="none">
          <SimpleTable
            rows={rules}
            rowKey={(r) => r.id}
            columns={[
              {header: 'Code', render: (r) => <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs">{r.code}</code>},
              {header: 'Name', render: (r) => <span className="font-medium text-gray-900">{r.name}</span>},
              {header: 'Fires when', render: (r) => (
                <span className="text-gray-700">
                  {metricLabel(r.metric)} {COMPARATORS.find((c) => c.value === r.comparator)?.label.split(' ')[0]} {Number(r.threshold)}
                </span>
              )},
              {header: 'Severity', align: 'center', render: (r) => (
                <Badge variant={severityVariant(r.severity)} size="sm">{r.severity}</Badge>
              )},
              {header: 'Scope', render: (r) => (
                <span className="text-xs text-gray-500">
                  {[r.scope_entity_types.join(', '), r.scope_channels.join(', ')].filter(Boolean).join(' · ') || 'All'}
                </span>
              )},
              {header: 'Enabled', align: 'center', render: (r) => (
                r.is_enabled ? <Badge variant="success" size="sm">on</Badge> : <Badge variant="default" size="sm">off</Badge>
              )},
              {header: 'Ver', align: 'center', render: (r) => <span className="text-gray-500">v{r.version}</span>},
              {header: '', align: 'right', render: (r) => (
                <Button variant="ghost" size="sm" aria-label={`Edit ${r.code}`}
                        onClick={() => { setEditing(r); setOpen(true); }}><Pencil className="h-4 w-4" /></Button>
              )},
            ]}
          />
        </Card>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title={editing ? `Edit ${editing.code}` : 'New alert rule'} size="lg">
        <RuleForm existing={editing} onDone={() => setOpen(false)} />
      </Modal>
    </div>
  );
}

function ChipGroup({ options, selected, onToggle }: {
  options: Array<{ code: string; name: string }>;
  selected: string[];
  onToggle: (code: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const active = selected.includes(o.code);
        return (
          <button
            key={o.code}
            type="button"
            aria-pressed={active}
            onClick={() => onToggle(o.code)}
            className={cn(
              'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
              active ? 'border-primary bg-primary/10 text-primary' : 'border-gray-200 text-gray-600 hover:border-primary/40',
            )}
          >
            {o.name}
          </button>
        );
      })}
    </div>
  );
}

function RuleForm({ existing, onDone }: { existing: AlertRule | null; onDone: () => void }) {
  const save = useSaveAlertRule();
  const { data: kpisResp } = useKpiDefinitions();
  const { data: typesResp } = useEntityTypes();
  const { data: channelsResp } = useChannels();
  const kpis = kpisResp?.results ?? [];
  const entityTypes = typesResp?.results ?? [];
  const channels = channelsResp?.results ?? [];

  const [name, setName] = useState(existing?.name ?? '');
  const [code, setCode] = useState(existing?.code ?? '');
  const [metric, setMetric] = useState<AlertRule['metric']>(existing?.metric ?? 'projected_pct');
  const [comparator, setComparator] = useState<AlertRule['comparator']>(existing?.comparator ?? 'lt');
  const [threshold, setThreshold] = useState(existing ? String(Number(existing.threshold)) : '90');
  const [severity, setSeverity] = useState<AlertRule['severity']>(existing?.severity ?? 'warning');
  const [kpiId, setKpiId] = useState(existing?.kpi ? String(existing.kpi) : '');
  const [scopeTypes, setScopeTypes] = useState<string[]>(existing?.scope_entity_types ?? []);
  const [scopeChannels, setScopeChannels] = useState<string[]>(existing?.scope_channels ?? []);
  const [messageTemplate, setMessageTemplate] = useState(existing?.message_template ?? '{entity}: {metric} is {value}');
  const [isEnabled, setIsEnabled] = useState(existing?.is_enabled ?? true);

  const toggle = (list: string[], set: (v: string[]) => void) => (c: string) =>
    set(list.includes(c) ? list.filter((x) => x !== c) : [...list, c]);

  function submit() {
    save.mutate({ id: existing?.id ?? null, payload: {
      name: name.trim(), code: code.trim(),
      metric, comparator, threshold: threshold.trim() || '0',
      severity, kpi: kpiId ? Number(kpiId) : null,
      scope_entity_types: scopeTypes, scope_channels: scopeChannels,
      message_template: messageTemplate.trim(), is_enabled: isEnabled,
    } }, {
      onSuccess: () => { notify.success(existing ? 'Rule saved (new version)' : 'Alert rule created'); onDone(); },
      onError: (e) => notify.error(apiErrorMessage(e, 'Could not save the rule')),
    });
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Target at risk" />
        <Input label="Short code" value={code} disabled={!!existing}
               onChange={(e) => setCode(e.target.value.toUpperCase().replace(/\s+/g, '_'))} placeholder="AT_RISK" />
      </div>

      <p className="text-xs font-medium uppercase tracking-wide text-gray-400">Condition</p>
      <div className="grid grid-cols-3 gap-4">
        <Select label="Metric" value={metric} onChange={(e) => setMetric(e.target.value as AlertRule['metric'])}
          options={METRICS.map((m) => ({ value: m.value, label: m.label }))} />
        <Select label="Comparator" value={comparator} onChange={(e) => setComparator(e.target.value as AlertRule['comparator'])}
          options={COMPARATORS.map((c) => ({ value: c.value, label: c.label }))} />
        <Input label="Threshold" type="number" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Select label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value as AlertRule['severity'])}
          options={SEVERITIES.map((s) => ({ value: s.value, label: s.label }))} />
        <Select label="KPI (optional)" value={kpiId} onChange={(e) => setKpiId(e.target.value)}
          options={[{ value: '', label: 'Any KPI' }, ...kpis.map((k) => ({ value: String(k.id), label: k.name }))]} />
      </div>

      <p className="text-xs font-medium uppercase tracking-wide text-gray-400">Scope (leave blank for all)</p>
      {entityTypes.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs text-gray-500">Role types</p>
          <ChipGroup options={entityTypes} selected={scopeTypes} onToggle={toggle(scopeTypes, setScopeTypes)} />
        </div>
      )}
      {channels.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs text-gray-500">Channels</p>
          <ChipGroup options={channels} selected={scopeChannels} onToggle={toggle(scopeChannels, setScopeChannels)} />
        </div>
      )}

      <Input label="Message template" value={messageTemplate} onChange={(e) => setMessageTemplate(e.target.value)}
        hint="Placeholders: {entity} {metric} {value} {kpi}" />
      <label className="flex items-center gap-2 text-sm text-gray-600">
        <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)}
               className="rounded border-gray-300 text-primary focus:ring-primary/30" />
        Enabled — evaluated on every achievement run
      </label>

      <div className="flex justify-end gap-2 border-t border-gray-100 pt-4">
        <Button variant="outline" onClick={onDone}>Cancel</Button>
        <Button onClick={submit} loading={save.isPending} disabled={!name.trim() || !code.trim()}>
          {existing ? 'Save changes' : 'Create rule'}
        </Button>
      </div>
    </div>
  );
}
