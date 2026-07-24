import { TrendingUp, TrendingDown } from 'lucide-react';
import { Card } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { ProgressBar } from '../ui/ProgressBar';
import { InfoTooltip } from '../ui/InfoTooltip';
import { formatPct, formatUnitCompact } from '../../utils/format';
import type { KpiCard } from '../../types/achievement';

interface KPICardProps {
  card: KpiCard;
  showMultiplier?: boolean;
  onClick?: () => void;
}

function multiplierVariant(value: number): 'success' | 'warning' | 'danger' {
  if (value >= 1) return 'success';
  if (value > 0) return 'warning';
  return 'danger';
}

export function KPICard({ card, showMultiplier = false, onClick }: KPICardProps) {
  const pct = Number(card.pct);
  const projected = Number(card.projected_pct);
  const growth = card.growth_pct !== null ? Number(card.growth_pct) : null;

  const body = (
    <>
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm font-semibold text-gray-900">{card.kpi_name}</p>
            <p className="text-[11px] uppercase tracking-wide text-gray-500">{card.kpi_code}</p>
          </div>
          <div className="flex items-center gap-1.5">
            {card.weight_pct !== null && (
              <Badge variant="info" size="sm">Wt {formatPct(card.weight_pct, 0)}</Badge>
            )}
            {card.is_provisional && (
              <InfoTooltip content="Provisional — figures finalise after the period closes and claims settle." />
            )}
          </div>
        </div>

        <div className="mt-3 flex items-end justify-between">
          <p className="text-3xl font-bold text-gray-800">{formatPct(card.pct)}</p>
          {showMultiplier && card.multiplier !== null && (
            <Badge variant={multiplierVariant(Number(card.multiplier))}>{card.multiplier}x</Badge>
          )}
        </div>

        <div className="mt-2">
          <ProgressBar value={pct} />
        </div>

        <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
          <span>{formatUnitCompact(card.achieved, card.unit)} / {formatUnitCompact(card.target, card.unit)}</span>
          {growth !== null && (
            <span className={growth >= 0 ? 'flex items-center gap-0.5 text-success' : 'flex items-center gap-0.5 text-danger'}>
              {growth >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
              {formatPct(Math.abs(growth))} LY
            </span>
          )}
        </div>

        {/* FMCG run-rate differentiator */}
        <div className="mt-2 flex items-center justify-between border-t border-gray-100 pt-2 text-[11px]">
          <span className="text-gray-400">
            Projected <span className={projected >= 100 ? 'font-semibold text-success' : 'font-semibold text-warning'}>{formatPct(card.projected_pct)}</span>
          </span>
          {Number(card.required_run_rate) > 0 && (
            <span className="text-gray-400">Need {formatUnitCompact(card.required_run_rate, card.unit)}/day</span>
          )}
        </div>
    </>
  );

  return (
    <Card padding="md" className={onClick ? 'transition-shadow hover:shadow-md' : undefined}>
      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          className="w-full rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        >
          {body}
        </button>
      ) : (
        <div>{body}</div>
      )}
    </Card>
  );
}
