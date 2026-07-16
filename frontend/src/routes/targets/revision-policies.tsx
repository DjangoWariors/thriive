import { useState } from 'react';
import { useNavigate } from 'react-router';
import { ArrowLeft, Plus, Pencil, ShieldCheck } from 'lucide-react';
import { useRevisionPolicies, useSaveRevisionPolicy, useTargetPeriods } from '../../hooks/useTargets';
import { useChannels } from '../../hooks/useEntities';
import type { RevisionPolicy } from '../../types/target';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Modal } from '../../components/ui/Modal';
import { EmptyState } from '../../components/ui/EmptyState';
import {PageHeader} from '../../components/ui/PageHeader';
import { Pagination } from '../../components/ui/Pagination';
import { SimpleTable } from '../../components/ui/SimpleTable';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

/** Tolerate either an array or a paginated {results} response. */
function rows<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object' && 'results' in data) return ((data as { results: T[] }).results) ?? [];
  return [];
}

export default function RevisionPoliciesPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const { data } = useRevisionPolicies({ page });
  const policies = data?.results ?? [];
  const [editing, setEditing] = useState<RevisionPolicy | null>(null);
  const [open, setOpen] = useState(false);

  return (
    <div className="p-6">
      <button onClick={() => navigate('/targets')} className="mb-3 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-primary">
        <ArrowLeft className="h-4 w-4" /> Back to targets
      </button>
      <PageHeader
        className="mb-5"
        title="Target change caps"
        description="How far a target may be revised — during the review cascade and after publish — before it needs approval, or is blocked. The most specific policy (period > channel) applies. With no policy, review adjustments are free and published edits route for approval by default."
      />

      <div className="mb-3 flex justify-end">
        <Button icon={<Plus className="h-4 w-4" />} onClick={() => { setEditing(null); setOpen(true); }}>New policy</Button>
      </div>

      {policies.length === 0 ? (
        <Card><EmptyState icon={ShieldCheck} title="No change caps yet" description="Add one to auto-approve small revisions and escalate or block big ones." /></Card>
      ) : (
        <Card padding="none">
          <SimpleTable
            rows={policies}
            rowKey={(p) => p.id}
            columns={[
              {header: 'Code', render: (p) => <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs">{p.code}</code>},
              {header: 'Name', render: (p) => <span className="font-medium text-gray-900">{p.name}</span>},
              {header: 'Auto ≤', align: 'right', render: (p) => <>{p.auto_approve_within_pct}%</>},
              {header: 'Ceiling', align: 'right', render: (p) => <>{p.hard_ceiling_pct ? `${p.hard_ceiling_pct}%` : '—'}</>},
              {header: 'Reason?', align: 'center', render: (p) => (
                p.requires_reason ? <Badge variant="success">yes</Badge> : <Badge variant="default">no</Badge>
              )},
              {header: 'Ver', align: 'center', render: (p) => <span className="text-gray-500">v{p.version}</span>},
              {header: '', align: 'right', render: (p) => (
                <Button variant="ghost" size="sm" aria-label={`Edit ${p.code}`}
                        onClick={() => { setEditing(p); setOpen(true); }}><Pencil className="h-4 w-4" /></Button>
              )},
            ]}
          />
          <Pagination count={data?.count ?? 0} page={page} onPageChange={setPage} />
        </Card>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title={editing ? `Edit ${editing.code}` : 'New change cap'} size="lg">
        <PolicyForm existing={editing} onDone={() => setOpen(false)} />
      </Modal>
    </div>
  );
}

interface NamedRow { id: number; name: string; code?: string }

function PolicyForm({ existing, onDone }: { existing: RevisionPolicy | null; onDone: () => void }) {
  const save = useSaveRevisionPolicy();
  // Lookup, not a list view: fetch the whole calendar so later months stay selectable.
  const { data: periodsResp } = useTargetPeriods({ page_size: 200 });
  const { data: channelsData } = useChannels();
  // Indent by tree depth so a quarter/month is picked knowingly, not confused with its year.
  const periods = [...(periodsResp?.results ?? [])].sort((a, b) => a.path.localeCompare(b.path));
  const channels = rows<NamedRow>(channelsData);

  const [name, setName] = useState(existing?.name ?? '');
  const [code, setCode] = useState(existing?.code ?? '');
  const [periodId, setPeriodId] = useState(existing?.target_period ? String(existing.target_period) : '');
  const [channelId, setChannelId] = useState(existing?.channel ? String(existing.channel) : '');
  const [autoPct, setAutoPct] = useState(existing?.auto_approve_within_pct ?? '10');
  const [ceiling, setCeiling] = useState(existing?.hard_ceiling_pct ?? '');
  const [maxRev, setMaxRev] = useState(existing?.max_revisions_per_period != null ? String(existing.max_revisions_per_period) : '');
  const [freeze, setFreeze] = useState(existing?.freeze_after ?? '');
  const [requiresReason, setRequiresReason] = useState(existing?.requires_reason ?? true);

  function submit() {
    save.mutate({ id: existing?.id ?? null, payload: {
      name: name.trim(), code: code.trim(),
      target_period: periodId ? Number(periodId) : null,
      channel: channelId ? Number(channelId) : null,
      // Targets are geography-anchored — entity-type-scoped policies never match, so the
      // dimension is not offered (a policy carrying one would be silently dead).
      entity_type: null,
      auto_approve_within_pct: autoPct.trim() || '0',
      hard_ceiling_pct: ceiling.trim() ? ceiling.trim() : null,
      max_revisions_per_period: maxRev.trim() ? Number(maxRev) : null,
      freeze_after: freeze.trim() ? freeze.trim() : null,
      requires_reason: requiresReason,
    } }, {
      onSuccess: () => { notify.success(existing ? 'Policy saved (new version)' : 'Policy created'); onDone(); },
      onError: (e) => notify.error(apiErrorMessage(e, 'Could not save the policy')),
    });
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Standard ±10%" />
        <Input label="Short code" value={code} disabled={!!existing} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/\s+/g, '_'))} placeholder="STD_10" />
      </div>

      <p className="text-xs font-medium uppercase tracking-wide text-gray-400">Applies to (leave blank for all)</p>
      <div className="grid grid-cols-2 gap-4">
        <Select label="Period" value={periodId} onChange={(e) => setPeriodId(e.target.value)}
          options={[{ value: '', label: 'All periods' },
            ...periods.map((p) => ({ value: String(p.id), label: `${'  '.repeat(p.depth)}${p.name}` }))]} />
        <Select label="Channel" value={channelId} onChange={(e) => setChannelId(e.target.value)}
          options={[{ value: '', label: 'All channels' }, ...channels.map((c) => ({ value: String(c.id), label: c.name }))]} />
      </div>

      <p className="text-xs font-medium uppercase tracking-wide text-gray-400">Limits</p>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Auto-approve within (%)" type="number" value={autoPct} onChange={(e) => setAutoPct(e.target.value)}
          hint="A change up to this much applies immediately." />
        <Input label="Hard ceiling (%) — optional" type="number" value={ceiling} onChange={(e) => setCeiling(e.target.value)}
          placeholder="blank = no ceiling" hint="A bigger change is blocked outright." />
        <Input label="Max revisions per period — optional" type="number" value={maxRev} onChange={(e) => setMaxRev(e.target.value)} placeholder="blank = unlimited" />
        <Input label="Freeze edits after — optional" type="date" value={freeze} onChange={(e) => setFreeze(e.target.value)} />
      </div>
      <label className="flex items-center gap-2 text-sm text-gray-600">
        <input type="checkbox" checked={requiresReason} onChange={(e) => setRequiresReason(e.target.checked)} className="rounded border-gray-300 text-primary focus:ring-primary/30" />
        Require a reason for every revision
      </label>

      <div className="flex justify-end gap-2 border-t border-gray-100 pt-4">
        <Button variant="outline" onClick={onDone}>Cancel</Button>
        <Button onClick={submit} loading={save.isPending} disabled={!name.trim() || !code.trim()}>{existing ? 'Save changes' : 'Create policy'}</Button>
      </div>
    </div>
  );
}
