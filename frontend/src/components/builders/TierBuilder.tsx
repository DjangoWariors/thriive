import { Lock, Plus, Trash2 } from 'lucide-react';
import { cn } from '../../utils/cn';
import { Button } from '../ui/Button';
import type { MultiplierTier } from '../../types/incentive';

/**
 * Step-tier grid editor for one KPI's achievement → multiplier mapping.
 *
 * Contiguity is structural, not validated after the fact: each row's Min is
 * read-only and chained from the previous row's Max, the first row is locked
 * to 0, and the last row is always unbounded. Editing a Max re-chains the next
 * row's Min automatically.
 */

interface TierBuilderProps {
  value: MultiplierTier[];
  onChange: (tiers: MultiplierTier[]) => void;
  disabled?: boolean;
}

function rechain(tiers: MultiplierTier[]): MultiplierTier[] {
  return tiers.map((tier, i) => ({
    ...tier,
    min_achievement_pct: i === 0 ? '0' : tiers[i - 1].max_achievement_pct ?? '0',
    max_achievement_pct: i === tiers.length - 1 ? null : tier.max_achievement_pct,
  }));
}

export function defaultTiers(): MultiplierTier[] {
  return [
    { min_achievement_pct: '0', max_achievement_pct: '80', multiplier: '0' },
    { min_achievement_pct: '80', max_achievement_pct: '100', multiplier: '0.8' },
    { min_achievement_pct: '100', max_achievement_pct: null, multiplier: '1.2' },
  ];
}

function rowError(tier: MultiplierTier, isLast: boolean): string | null {
  if (!isLast) {
    const min = parseFloat(tier.min_achievement_pct);
    const max = parseFloat(tier.max_achievement_pct ?? '');
    if (isNaN(max)) return 'Max is required';
    if (max <= min) return `Max must be greater than ${tier.min_achievement_pct}`;
  }
  const mult = parseFloat(tier.multiplier);
  if (isNaN(mult)) return 'Multiplier is required';
  if (mult < 0) return 'Multiplier cannot be negative';
  return null;
}

export function tierGridErrors(tiers: MultiplierTier[]): string[] {
  return tiers
    .map((tier, i) => rowError(tier, i === tiers.length - 1))
    .filter((e): e is string => e !== null);
}

const CELL = 'w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm ' +
  'focus:outline-none focus:ring-2 focus:border-primary focus:ring-primary/20';

export function TierBuilder({ value, onChange, disabled = false }: TierBuilderProps) {
  const update = (index: number, patch: Partial<MultiplierTier>) => {
    const next = value.map((t, i) => (i === index ? { ...t, ...patch } : t));
    onChange(rechain(next));
  };

  const addRow = () => {
    const last = value[value.length - 1];
    const lastMin = parseFloat(last?.min_achievement_pct ?? '0');
    const split = String(lastMin + 20);
    const next = [
      ...value.slice(0, -1),
      { ...last, max_achievement_pct: split },
      { min_achievement_pct: split, max_achievement_pct: null, multiplier: last?.multiplier ?? '1' },
    ];
    onChange(rechain(next));
  };

  const removeRow = (index: number) => {
    onChange(rechain(value.filter((_, i) => i !== index)));
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[1fr_1fr_1fr_36px] items-center gap-2 px-1 text-xs font-medium uppercase tracking-wide text-gray-500">
        <span>Min achievement %</span>
        <span>Max achievement %</span>
        <span>Multiplier ×</span>
        <span />
      </div>

      {value.map((tier, i) => {
        const isLast = i === value.length - 1;
        const error = rowError(tier, isLast);
        return (
          <div key={i}>
            <div className="grid grid-cols-[1fr_1fr_1fr_36px] items-center gap-2">
              <input
                value={tier.min_achievement_pct}
                readOnly
                disabled
                aria-label={`Slab ${i + 1} minimum`}
                className={cn(CELL, 'cursor-not-allowed text-gray-500')}
              />
              {isLast ? (
                <div className={cn(CELL, 'flex items-center gap-1.5 text-gray-500')}>
                  <Lock size={12} /> Unlimited
                </div>
              ) : (
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  value={tier.max_achievement_pct ?? ''}
                  disabled={disabled}
                  aria-label={`Slab ${i + 1} maximum`}
                  onChange={(e) => update(i, { max_achievement_pct: e.target.value })}
                  className={cn(CELL, error && 'border-danger')}
                />
              )}
              <input
                type="number"
                min={0}
                step="0.001"
                value={tier.multiplier}
                disabled={disabled}
                aria-label={`Slab ${i + 1} multiplier`}
                onChange={(e) => update(i, { multiplier: e.target.value })}
                className={cn(CELL, error?.includes('Multiplier') && 'border-danger')}
              />
              <button
                type="button"
                onClick={() => removeRow(i)}
                disabled={disabled || value.length <= 1}
                aria-label={`Remove slab ${i + 1}`}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-400 hover:bg-danger/10 hover:text-danger disabled:opacity-30"
              >
                <Trash2 size={15} />
              </button>
            </div>
            {error && <p className="mt-0.5 px-1 text-xs text-danger">{error}</p>}
          </div>
        );
      })}

      <Button type="button" variant="outline" size="sm" onClick={addRow} disabled={disabled}
              icon={<Plus size={14} />}>
        Add slab
      </Button>
    </div>
  );
}
