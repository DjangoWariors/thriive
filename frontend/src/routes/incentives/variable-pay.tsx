import { useMemo, useState } from 'react';
import { Plus, Search, Upload, Wallet } from 'lucide-react';
import { usePeriodSelector } from '../../hooks/usePeriodSelector';
import { useTargetPeriods } from '../../hooks/useTargets';
import { useEntitySearch } from '../../hooks/useEntities';
import {
  useBulkImportVariablePay, useUpsertVariablePay, useVariablePay,
} from '../../hooks/useIncentives';
import { useRBAC } from '../../hooks/useRBAC';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { EmptyState } from '../../components/ui/EmptyState';
import { HowThisWorks } from '../../components/ui/HowThisWorks';
import { Input } from '../../components/ui/Input';
import { Modal } from '../../components/ui/Modal';
import { Pagination } from '../../components/ui/Pagination';
import { Textarea } from '../../components/ui/Textarea';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import { formatCurrency } from '../../utils/format';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import type { VariablePayBulkResult } from '../../types/incentive';

/** Parses "entity_code,amount[,eligible_working_days]" CSV lines (header optional). */
function parseCsv(text: string): Array<Record<string, unknown>> {
  const lines = text.trim().split(/\r?\n/).filter((l) => l.trim());
  const rows: Array<Record<string, unknown>> = [];
  for (const line of lines) {
    const [code, amount, days] = line.split(',').map((c) => c.trim());
    if (!code || code.toLowerCase() === 'entity_code') continue;
    rows.push({
      entity_code: code,
      amount,
      ...(days ? { eligible_working_days: Number(days) } : {}),
    });
  }
  return rows;
}

export default function VariablePayPage() {
  const { selectedPeriodId } = usePeriodSelector();
  // Same no-arg call as the header's PeriodSelector, so this hits the React Query cache.
  const { data: periodsResp } = useTargetPeriods();
  const periodName = periodsResp?.results.find((p) => p.id === selectedPeriodId)?.name;
  const { canWrite } = useRBAC();
  const writable = canWrite('scheme_management');

  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);

  const params = selectedPeriodId !== null ? { period: selectedPeriodId, page } : undefined;
  const { data: resp, isLoading } = useVariablePay(params);
  const rows = resp?.results ?? [];

  return (
    <div className="p-6">
      <PageHeader
          title={periodName ? `Variable Pay — ${periodName}` : 'Variable Pay'}
          description="The monthly pay base each person's incentive is computed against — one row per person for the month picked in the header. Eligible working days prorate it for mid-month joiners, transfers and approved leave."
          actions={writable && selectedPeriodId !== null && (
            <>
              <Button variant="outline" icon={<Upload className="h-4 w-4" />} onClick={() => setImporting(true)}>
                Bulk import
              </Button>
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => setAdding(true)}>
                Set variable pay
              </Button>
            </>
          )}
      />

      <HowThisWorks storageKey="variable-pay-help" className="mb-6">
        <p>
          Variable pay is the <strong>at-risk part of a person's salary</strong> — the amount they
          play for each month. HR decides it; the platform never calculates it. It is not the payout
          itself: it is the base every payout is computed from.
        </p>
        <p className="mt-2">
          <strong>Example:</strong> Priya's salary is ₹80,000 — ₹50,000 fixed + ₹30,000 variable, so
          you enter <strong>30,000</strong> here for the month. Her SIP's monthly scheme pays against
          80% of it → a ₹24,000 base. If she hits 105% of target and the multiplier grid says 1.2x on
          a KPI weighted 70%, that line pays 24,000 × 1.2 × 70% = <strong>₹20,160</strong>. Perform
          at exactly 1x on everything and the payout equals the base; strong months can pay more,
          weak months less.
        </p>
        <p className="mt-2">
          Two rules to remember: a person <strong>without a row here earns nothing</strong> for the
          month, and someone eligible only part of the month gets a prorated base — set eligible
          working days (e.g. 13 of 26 days → half the base).
        </p>
      </HowThisWorks>

      {selectedPeriodId === null ? (
        <Card>
          <EmptyState icon={Wallet} title="Pick a period"
                      description="Choose a period from the selector in the header." />
        </Card>
      ) : isLoading ? (
        <TableSkeleton/>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState icon={Wallet} title="No variable pay set for this period"
                      description="Payout runs skip anyone without a variable-pay row — set them individually or import a CSV."
                      actionLabel={writable ? 'Set variable pay' : undefined}
                      onAction={writable ? () => setAdding(true) : undefined} />
        </Card>
      ) : (
        <Card padding="none">
          <SimpleTable
            rows={rows}
            rowKey={(vp) => vp.id}
            columns={[
              {header: 'Person', render: (vp) => (
                <>
                  <p className="font-medium text-gray-900">{vp.entity_name}</p>
                  <p className="text-xs text-gray-500">{vp.entity_code}</p>
                </>
              )},
              {header: 'Monthly VP', align: 'right', render: (vp) => (
                <span className="font-medium text-gray-900">{formatCurrency(vp.amount)}</span>
              )},
              {header: 'Eligible days', align: 'right', render: (vp) => (
                <span className="text-gray-600">{vp.eligible_working_days ?? 'Full period'}</span>
              )},
              {header: 'Source', render: (vp) => (
                <span className="text-gray-500">{vp.source === 'bulk_import' ? 'Bulk import' : 'Manual'}</span>
              )},
            ]}
          />
          <Pagination count={resp?.count ?? 0} page={page} onPageChange={setPage} />
        </Card>
      )}

      {selectedPeriodId !== null && (
        <>
          <UpsertModal open={adding} onClose={() => setAdding(false)} periodId={selectedPeriodId} />
          <ImportModal open={importing} onClose={() => setImporting(false)} periodId={selectedPeriodId} />
        </>
      )}
    </div>
  );
}

function UpsertModal({ open, onClose, periodId }: { open: boolean; onClose: () => void; periodId: number }) {
  const [query, setQuery] = useState('');
  const [entityId, setEntityId] = useState<number | null>(null);
  const [entityLabel, setEntityLabel] = useState('');
  const [amount, setAmount] = useState('');
  const [days, setDays] = useState('');
  const { data: matches } = useEntitySearch(query);
  const upsert = useUpsertVariablePay();

  const reset = () => { setQuery(''); setEntityId(null); setEntityLabel(''); setAmount(''); setDays(''); };

  const save = () => {
    if (entityId === null || !amount) return;
    upsert.mutate({
      entity: entityId, target_period: periodId, amount,
      eligible_working_days: days ? Number(days) : null,
    }, {
      onSuccess: () => { notify.success('Variable pay saved'); reset(); onClose(); },
      onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, we couldn’t save that')),
    });
  };

  return (
    <Modal open={open} onClose={() => { reset(); onClose(); }} title="Set variable pay" size="md"
           footer={
             <div className="flex justify-end gap-2">
               <Button variant="outline" onClick={() => { reset(); onClose(); }}>Cancel</Button>
               <Button onClick={save} disabled={entityId === null || !amount} loading={upsert.isPending}>
                 Save
               </Button>
             </div>
           }>
      <div className="space-y-4">
        {entityId === null ? (
          <div>
            <Input label="Person" placeholder="Search by name or code…" value={query}
                   onChange={(e) => setQuery(e.target.value)} leftIcon={<Search className="h-4 w-4" />} />
            {query && (matches ?? []).length > 0 && (
              <div className="mt-1 max-h-44 overflow-auto rounded-lg border border-gray-200">
                {(matches ?? []).map((m) => (
                  <button key={m.id} type="button"
                          className="block w-full px-3 py-2 text-left text-sm hover:bg-primary-50"
                          onClick={() => { setEntityId(m.id); setEntityLabel(`${m.name} (${m.code})`); }}>
                    <span className="font-medium text-gray-900">{m.name}</span>{' '}
                    <span className="text-xs text-gray-500">{m.code}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2 text-sm">
            <span className="font-medium text-gray-900">{entityLabel}</span>
            <Button variant="ghost" size="sm" onClick={() => setEntityId(null)}>Change</Button>
          </div>
        )}
        <Input label="Monthly variable pay (₹)" type="number" min={0} step="0.01"
               value={amount} onChange={(e) => setAmount(e.target.value)} />
        <Input label="Eligible working days (optional)" type="number" min={0}
               hint="Leave blank for the full period; set for mid-month joiners/transfers/leave"
               value={days} onChange={(e) => setDays(e.target.value)} />
      </div>
    </Modal>
  );
}

function ImportModal({ open, onClose, periodId }: { open: boolean; onClose: () => void; periodId: number }) {
  const [text, setText] = useState('');
  const [result, setResult] = useState<VariablePayBulkResult | null>(null);
  const bulkImport = useBulkImportVariablePay();
  const rows = useMemo(() => parseCsv(text), [text]);

  const run = () => {
    bulkImport.mutate({ targetPeriod: periodId, rows }, {
      onSuccess: (res) => {
        setResult(res);
        if (res.errors.length === 0) {
          notify.success(`${res.created} created, ${res.updated} updated`);
        } else {
          notify.error('Nothing was imported — fix the listed rows and retry');
        }
      },
      onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, the import failed')),
    });
  };

  return (
    <Modal open={open} onClose={() => { setText(''); setResult(null); onClose(); }}
           title="Bulk import variable pay" size="lg"
           footer={
             <div className="flex items-center justify-between">
               <span className="text-xs text-gray-500">{rows.length} rows parsed</span>
               <div className="flex gap-2">
                 <Button variant="outline" onClick={() => { setText(''); setResult(null); onClose(); }}>Close</Button>
                 <Button onClick={run} disabled={rows.length === 0} loading={bulkImport.isPending}>
                   Import (all-or-nothing)
                 </Button>
               </div>
             </div>
           }>
      <div className="space-y-3">
        <Textarea label="CSV rows" rows={8} value={text} onChange={(e) => setText(e.target.value)}
                  placeholder={'entity_code,amount,eligible_working_days\nASE_DL_E,60000\nASE_DL_W,60000,12'} />
        {result && result.errors.length > 0 && (
          <div className="max-h-40 overflow-auto rounded-lg border border-danger/30 bg-danger/5 p-3">
            <ul className="list-inside list-disc text-sm text-danger">
              {result.errors.map((e, i) => (
                <li key={i}>Row {e.row}: {e.errors.join(', ')}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  );
}
