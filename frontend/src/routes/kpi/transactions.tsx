import { useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { ArrowLeft, Upload, Receipt } from 'lucide-react';
import { useKpiTransactions } from '../../hooks/useKpi';
import { kpiService } from '../../services/kpiService';
import { useRBAC } from '../../hooks/useRBAC';
import type { TransactionLevel } from '../../types/kpi';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { InfoTooltip } from '../../components/ui/InfoTooltip';
import { EmptyState } from '../../components/ui/EmptyState';
import { Modal } from '../../components/ui/Modal';
import { Pagination } from '../../components/ui/Pagination';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import { BulkJobProgress } from '../../components/jobs/BulkJobProgress';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

const LEVEL_OPTIONS = [
  { value: '', label: 'All sales stages' },
  { value: 'primary', label: 'Primary — Company to Distributor' },
  { value: 'secondary', label: 'Secondary — Distributor to Retailer' },
  { value: 'tertiary', label: 'Tertiary — Retailer to Shopper' },
];
const TYPE_OPTIONS = [
  { value: '', label: 'Sales & returns' },
  { value: 'sale', label: 'Sales only' },
  { value: 'return', label: 'Returns only' },
  //{ value: 'credit_note', label: 'Credit notes only' }, #comment by developer
];

export default function TransactionsPage() {
  const navigate = useNavigate();
  const { canWrite } = useRBAC();
  const writable = canWrite('kpi_definitions');

  const [nodeId, setNodeId] = useState('');
  const [level, setLevel] = useState('');
  const [txnType, setTxnType] = useState('');
  const [page, setPage] = useState(1);
  const [importOpen, setImportOpen] = useState(false);

  const params = useMemo(
    () => ({
      page,
      ...(nodeId ? { attributed_node_id: Number(nodeId) } : {}),
      ...(level ? { transaction_level: level as TransactionLevel } : {}),
      ...(txnType ? { transaction_type: txnType } : {}),
    }),
    [page, nodeId, level, txnType],
  );

  const { data: resp, isLoading } = useKpiTransactions(params);
  const txns = resp?.results ?? [];

  return (
    <div className="p-6">
      <button onClick={() => navigate('/kpi/definitions')} className="mb-3 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-primary">
        <ArrowLeft className="h-4 w-4" /> Back to KPIs
      </button>
      <PageHeader
          title="Sales Data"
          description="Every sale and return that your KPIs are calculated from. Bring it in from any source — your DMS, the field app"
          actions={<>{writable && (
          <Button icon={<Upload className="h-4 w-4" />} onClick={() => setImportOpen(true)}>
            Import sales data
          </Button>
        )}</>}
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-44">
          <Input label="Territory ID" value={nodeId} onChange={(e) => { setNodeId(e.target.value); setPage(1); }} placeholder="Show all territories" />
        </div>
        <div className="w-72">
          <Select label="Sales stage" value={level} onChange={(e) => { setLevel(e.target.value); setPage(1); }} options={LEVEL_OPTIONS} />
        </div>
        <div className="w-48">
          <Select label="Show" value={txnType} onChange={(e) => { setTxnType(e.target.value); setPage(1); }} options={TYPE_OPTIONS} />
        </div>
      </div>

      {isLoading ? (
        <TableSkeleton/>
      ) : txns.length === 0 ? (
        <Card>
          <EmptyState icon={Receipt} title="No sales data yet" description="Import a spreadsheet to get started — your KPIs will start calculating straight away." />
        </Card>
      ) : (
        <Card padding="none">
          <SimpleTable
            rows={txns}
            rowKey={(t) => t.id}
            columns={[
              {header: (
                <span className="inline-flex items-center gap-1.5">
                  Date
                  <InfoTooltip content="When the sale actually happened. (KPIs aggregate by this transaction date.)" />
                </span>
              ), render: (t) => <span className="text-gray-600">{t.transaction_date}</span>},
              {header: (
                <span className="inline-flex items-center gap-1.5">
                  Posted
                  <InfoTooltip content="When the row was posted into the source system — which can be later than when the sale happened. Useful for spotting late or back-dated entries." />
                </span>
              ), render: (t) => <span className="text-gray-500">{t.posted_date ?? '—'}</span>},
              {header: (
                <span className="inline-flex items-center gap-1.5">
                  Territory
                  <InfoTooltip content="The territory (beat/outlet) the sale is attributed to. The responsible person is resolved through territory assignments — so a transfer never rewrites sales rows." />
                </span>
              ), render: (t) => (
                <span className="text-gray-600">{t.attributed_node_label || `#${t.attributed_node_id}`}</span>
              )},
              {header: 'Sale / Return', render: (t) => (
                <Badge variant={t.transaction_type === 'sale' ? 'success' : 'danger'}>{t.transaction_type}</Badge>
              )},
              {header: 'Stage', render: (t) => <span className="text-gray-600">{t.transaction_level}</span>},
              {header: 'Channel', render: (t) => <span className="text-gray-600">{t.channel_code || '—'}</span>},
              {header: 'Product', render: (t) => <span className="text-gray-600">{t.sku_code || '—'}</span>},
              {header: 'Shop / Bill', render: (t) => (
                <span className="text-gray-500">{t.outlet_code || '—'}{t.bill_ref ? ` · ${t.bill_ref}` : ''}</span>
              )},
              {header: 'Net value', align: 'right', render: (t) => <span className="text-gray-700">₹{t.net_amount}</span>},
              {header: 'Qty', align: 'right', render: (t) => <span className="text-gray-600">{t.quantity} {t.uom}</span>},
              {header: (
                <span className="inline-flex items-center gap-1.5">
                  Came from
                  <InfoTooltip content="The data source: DMS sync, field app (SFA), QR scan, invoice upload, manual entry or API push. KPIs ignore the source when aggregating — unless a KPI is deliberately restricted to one." />
                </span>
              ), render: (t) => <span className="text-gray-500">{t.source || '—'}</span>},
            ]}
          />
          <Pagination count={resp?.count ?? 0} page={page} onPageChange={setPage} />
        </Card>
      )}

      <Modal open={importOpen} onClose={() => setImportOpen(false)} title="Import sales data" size="xl">
        <TransactionImport onClose={() => setImportOpen(false)} />
      </Modal>
    </div>
  );
}

const CSV_HEADER =
  'attributed_node_id,transaction_date,transaction_type,transaction_level,channel_code,sku_code,outlet_code,bill_ref,gross_amount,discount_amount,tax_amount,net_amount,quantity,uom,source,external_ref';

function TransactionImport({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [csvText, setCsvText] = useState('');
  const [fileName, setFileName] = useState('');
  const [jobId, setJobId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = () => setCsvText(String(reader.result ?? ''));
    reader.readAsText(file);
  }

  async function confirmImport() {
    setSubmitting(true);
    try {
      const job = await kpiService.bulkImportTransactions(csvText);
      setJobId(job.id);
    } catch (e) {
      notify.error(apiErrorMessage(e, 'We couldn’t start the upload. Please check the file and try again.'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
        Upload a spreadsheet (CSV) with these columns. It's safe to re-upload the same file —
        matching rows are refreshed, never duplicated.
        <code className="mt-1 block overflow-x-auto rounded bg-white px-2 py-1 text-[11px] text-gray-700">{CSV_HEADER}</code>
      </div>

      {jobId === null ? (
        <>
          <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed border-gray-300 py-6 text-sm text-gray-500 hover:border-primary hover:text-primary">
            <Upload className="h-4 w-4" />
            {fileName || 'Choose a file from your computer…'}
            <input type="file" accept=".csv,text/csv" className="hidden" onChange={onFile} />
          </label>
          <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button onClick={confirmImport} loading={submitting} disabled={!csvText.trim()}>Upload</Button>
          </div>
        </>
      ) : (
        <>
          <BulkJobProgress jobId={jobId} onDone={() => void qc.invalidateQueries({ queryKey: ['kpi', 'transactions'] })} />
          <div className="flex justify-end border-t border-gray-100 pt-4">
            <Button onClick={onClose}>Done</Button>
          </div>
        </>
      )}
    </div>
  );
}
