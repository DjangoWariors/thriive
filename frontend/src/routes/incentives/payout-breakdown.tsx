import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { ArrowLeft, ArrowRight, Ban, Download, Info, RotateCcw } from 'lucide-react';
import { useHoldPayout, usePayout, useReleasePayout } from '../../hooks/useIncentives';
import { useRBAC } from '../../hooks/useRBAC';
import { incentiveService } from '../../services/incentiveService';
import { Badge } from '../../components/ui/Badge';
import { Breadcrumb } from '../../components/ui/Breadcrumb';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { EmptyState } from '../../components/ui/EmptyState';
import { Modal } from '../../components/ui/Modal';
import { ProgressBar } from '../../components/ui/ProgressBar';
import { Spinner } from '../../components/ui/Spinner';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { Textarea } from '../../components/ui/Textarea';
import { Tooltip } from '../../components/ui/Tooltip';
import { formatCurrency, formatDate } from '../../utils/format';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';
import type { LineTreatment, PayoutLineItem } from '../../types/incentive';

const TREATMENT_META: Record<LineTreatment, { label: string; hint: string; variant: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'purple' } | null> = {
  actual: null,
  default_1x: { label: 'Defaulted 1×', variant: 'purple',
    hint: 'An approved exception fixed this KPI at 1× instead of actual performance' },
  zero: { label: 'Zeroed', variant: 'danger',
    hint: 'An approved exception zeroed this KPI' },
  below_threshold: { label: 'Below qualify', variant: 'warning',
    hint: 'Achievement is below the minimum qualifying threshold, so the line pays nothing' },
  capped: { label: 'Capped', variant: 'warning',
    hint: 'The multiplier was limited by a cap on this KPI (or the gatekeeper cap)' },
};

function tierLabel(line: PayoutLineItem): string {
  if (line.tier_min === null) return '—';
  const max = line.tier_max ?? '∞';
  return `${parseFloat(line.tier_min)}–${max === '∞' ? '∞' : parseFloat(max)}%`;
}

export default function PayoutBreakdownPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { canWrite } = useRBAC();
  const { data: payout, isLoading, isError } = usePayout(id ? Number(id) : null);
  const holdPayout = useHoldPayout();
  const releasePayout = useReleasePayout();
  const [holding, setHolding] = useState(false);
  const [holdReason, setHoldReason] = useState('');

  const isOperator = canWrite('final_payout');

  const downloadStatement = async () => {
    if (!payout) return;
    try {
      const stmt = await incentiveService.payoutStatement(payout.id);
      const blob = new Blob([JSON.stringify(stmt, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `statement-${stmt.entity.code}-${stmt.period.code}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      notify.error(apiErrorMessage(e, 'Sorry, we couldn’t download the statement'));
    }
  };

  if (isLoading) {
    return <div className="flex justify-center py-20"><Spinner size="lg" /></div>;
  }
  if (isError || !payout) {
    return (
      <div className="p-6">
        <Card>
          <EmptyState icon={Info} title="Payout not found"
                      description="This payout doesn’t exist or you don’t have access to it."
                      actionLabel="Back to payouts" onAction={() => navigate('/incentives/payouts')} />
        </Card>
      </div>
    );
  }

  const prorated = parseFloat(payout.proration_factor) < 1;
  const gatekeeperZeroed = payout.gatekeeper_status === 'failed' &&
    payout.total_payout !== payout.gross_payout;
  // A cycle-attached final run rests at 'computed' only while its cycle is under review;
  // hold/release are refused by the API in any other state.
  const underReview = payout.run_status === 'computed';

  return (
    <div className="p-6">
      <div className="mb-3 flex items-center justify-between">
        <Breadcrumb
          items={[
            { label: 'Payouts', onClick: () => navigate('/incentives/payouts') },
            { label: payout.entity_name },
          ]}
        />
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" icon={<Download size={14} />} onClick={downloadStatement}>
            Statement
          </Button>
          {/* Hold/release are only accepted while the cycle is under review — its final
              runs sit at 'computed' exactly then (approved/paid = past the review gate). */}
          {isOperator && underReview && payout.hold_status !== 'held' && (
            <Button variant="outline" size="sm" icon={<Ban size={14} />}
                    onClick={() => { setHoldReason(''); setHolding(true); }}>
              Hold
            </Button>
          )}
          {isOperator && underReview && payout.hold_status === 'held' && (
            <Button variant="outline" size="sm" icon={<RotateCcw size={14} />} loading={releasePayout.isPending}
                    onClick={() => releasePayout.mutate(payout.id, {
                      onSuccess: () => notify.success('Payout released'),
                      onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, we couldn’t release the payout')),
                    })}>
              Release
            </Button>
          )}
          <button onClick={() => navigate(-1)}
                  className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-primary">
            <ArrowLeft size={14} /> Back
          </button>
        </div>
      </div>

      {/* Header card */}
      <Card className="mb-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{payout.entity_name}</h1>
            <p className="text-sm text-gray-500">
              {payout.entity_code} · {payout.scheme_name} (v{payout.scheme_version}) · {payout.period_name}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <StatusBadge status={payout.run_status} />
              {payout.gatekeeper_status !== 'not_applicable' && (
                <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                  Gatekeeper: <StatusBadge status={payout.gatekeeper_status} />
                </span>
              )}
              {payout.capped && <Badge variant="warning">Capped</Badge>}
              {payout.hold_status === 'held' && (
                <Tooltip content={payout.hold_reason || 'Held during cycle review — excluded from the register'}>
                  <StatusBadge status="held" />
                </Tooltip>
              )}
              {payout.hold_status === 'released' && <StatusBadge status="released" />}
            </div>
          </div>
          <div className="text-right">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">Final payout</p>
            <p className="text-3xl font-bold text-gray-900">{formatCurrency(payout.total_payout)}</p>
            <p className="text-xs text-gray-500">{parseFloat(payout.total_multiplier).toFixed(2)}× weighted multiplier</p>
          </div>
        </div>

        {/* VP → eligible → gross → total walk */}
        <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg bg-gray-50 px-4 py-3 text-sm text-gray-700">
          <span>Variable pay <strong>{formatCurrency(payout.variable_pay_amount)}</strong></span>
          {prorated && (
            <>
              <ArrowRight size={13} className="text-gray-400" />
              <span>prorated ×{parseFloat(payout.proration_factor).toFixed(4)}</span>
            </>
          )}
          <ArrowRight size={13} className="text-gray-400" />
          <span>eligible <strong>{formatCurrency(payout.eligible_vp)}</strong></span>
          <ArrowRight size={13} className="text-gray-400" />
          <span>gross <strong>{formatCurrency(payout.gross_payout)}</strong></span>
          <ArrowRight size={13} className="text-gray-400" />
          <span className={gatekeeperZeroed || payout.capped ? 'text-danger' : ''}>
            final <strong>{formatCurrency(payout.total_payout)}</strong>
            {gatekeeperZeroed && ' (gatekeeper failed)'}
            {payout.capped && ' (overall cap applied)'}
          </span>
        </div>
      </Card>

      {/* Gate criteria — per-gate pass/fail */}
      {payout.gate_results.length > 0 && (
        <Card className="mb-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-gray-400">
            Gate criteria (all must pass)
          </p>
          <div className="flex flex-wrap gap-2">
            {payout.gate_results.map((g) => (
              <span key={g.kpi_code}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
                      g.passed
                        ? 'border-success-100 bg-success-50 text-success'
                        : 'border-danger-100 bg-danger-50 text-danger'
                    }`}>
                {g.passed ? '✓' : '✗'} {g.kpi_code}: {parseFloat(g.achievement_pct)}%
                {' '}{g.operator === 'gt' ? '>' : '≥'} {parseFloat(g.threshold_pct)}%
              </span>
            ))}
          </div>
          {payout.gatekeeper_status === 'exempted' && (
            <p className="mt-2 text-xs text-gray-500">
              An approved exception exempted this payout from the gate criteria.
            </p>
          )}
        </Card>
      )}

      {/* Exception card */}
      {payout.exception && (
        <Card className="mb-4" borderColor="purple">
          <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-gray-400">
            Approved exception applied
          </p>
          <p className="text-sm text-gray-700">
            {payout.exception.category && (
              <Badge variant="purple" className="mr-2">{payout.exception.category}</Badge>
            )}
            {payout.exception.reason}
          </p>
          <p className="mt-2 text-xs text-gray-500">
            Sales KPIs: <strong>{payout.exception.sales_kpi_action.replace(/_/g, ' ')}</strong>
            {' · '}Execution KPIs: <strong>{payout.exception.execution_kpi_action.replace(/_/g, ' ')}</strong>
            {' · '}Gatekeeper: <strong>{payout.exception.gatekeeper_action.replace(/_/g, ' ')}</strong>
          </p>
        </Card>
      )}

      {/* Line items */}
      <Card padding="none" className="mb-4">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-4 py-3">KPI</th>
              <th className="px-4 py-3 text-right">Target</th>
              <th className="px-4 py-3 text-right">Achieved</th>
              <th className="px-4 py-3">Achievement</th>
              <th className="px-4 py-3">Slab matched</th>
              <th className="px-4 py-3 text-right">Base ×</th>
              <th className="px-4 py-3 text-right">Applied ×</th>
              <th className="px-4 py-3 text-right">Weight</th>
              <th className="px-4 py-3 text-right">Contribution</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {payout.line_items.map((line) => {
              const treatment = TREATMENT_META[line.treatment];
              const pct = parseFloat(line.achievement_pct);
              return (
                <tr key={line.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <button
                      className="font-medium text-gray-900 hover:text-primary hover:underline"
                      onClick={() => navigate(`/achievements?period=${payout.target_period}&kpi=${line.kpi_id}&entity=${payout.entity}`)}
                    >
                      {line.kpi_name}
                    </button>
                    <p className="text-xs text-gray-400">
                      {line.kpi_code} · <span className="capitalize">{line.incentive_category}</span>
                    </p>
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600">{formatCurrency(line.target_value)}</td>
                  <td className="px-4 py-3 text-right text-gray-600">{formatCurrency(line.achieved_value)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20"><ProgressBar value={Math.min(pct, 150)} size="sm" /></div>
                      <span className="text-xs text-gray-600">{pct.toFixed(2)}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{tierLabel(line)}</td>
                  <td className="px-4 py-3 text-right text-gray-500">{parseFloat(line.base_multiplier).toFixed(3)}</td>
                  <td className="px-4 py-3 text-right">
                    <span className="font-medium text-gray-900">
                      {parseFloat(line.applied_multiplier).toFixed(3)}
                    </span>
                    {treatment && (
                      <Tooltip content={treatment.hint}>
                        <Badge variant={treatment.variant} className="ml-1.5">{treatment.label}</Badge>
                      </Tooltip>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600">{parseFloat(line.weightage)}%</td>
                  <td className="px-4 py-3 text-right font-semibold text-gray-900">
                    {formatCurrency(line.line_payout)}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot className="border-t border-gray-200 bg-gray-50">
            <tr>
              <td colSpan={8} className="px-4 py-3 text-right text-xs font-semibold uppercase text-gray-500">
                Gross payout
              </td>
              <td className="px-4 py-3 text-right font-bold text-gray-900">
                {formatCurrency(payout.gross_payout)}
              </td>
            </tr>
          </tfoot>
        </table>
      </Card>

      {/* Computation metadata */}
      <p className="text-xs text-gray-400">
        Computed on {formatDate(payout.computed_at)} · computation #{payout.computation_id ?? '—'} ·
        run #{payout.run} · scheme {payout.scheme_code} v{payout.scheme_version}
      </p>

      <Modal open={holding} onClose={() => setHolding(false)} title="Hold this payout" size="md"
             footer={
               <div className="flex justify-end gap-2">
                 <Button variant="outline" onClick={() => setHolding(false)}>Cancel</Button>
                 <Button variant="danger" disabled={!holdReason.trim()} loading={holdPayout.isPending}
                         onClick={() => holdPayout.mutate({ id: payout.id, reason: holdReason.trim() }, {
                           onSuccess: () => { setHolding(false); notify.success('Payout held — excluded from the register'); },
                           onError: (e) => notify.error(apiErrorMessage(e, 'Sorry, we couldn’t hold the payout')),
                         })}>
                   Hold payout
                 </Button>
               </div>
             }>
        <p className="mb-3 text-sm text-gray-600">
          The payee is excluded from this cycle’s register while held. Released before disbursement they pay
          normally; still held, they ride the next cycle as an adjustment.
        </p>
        <Textarea label="Why is this payout being held?" rows={3} value={holdReason}
                  onChange={(e) => setHoldReason(e.target.value)}
                  placeholder="e.g. Territory dispute under review with the RSM" />
      </Modal>
    </div>
  );
}
