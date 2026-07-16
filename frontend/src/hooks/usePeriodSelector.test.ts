import { describe, expect, it } from 'vitest';
import { pickDefaultPeriod } from './usePeriodSelector';
import type { TargetPeriod } from '../types/target';

function period(p: Partial<TargetPeriod> & Pick<TargetPeriod, 'id' | 'period_type' | 'start_date' | 'end_date'>): TargetPeriod {
  return {
    name: `P${p.id}`, code: `P${p.id}`, fiscal_year: 'FY2026', parent: null, channel: null,
    working_days: null, path: String(p.id), depth: 0, status: 'published', is_active: true,
    ...p,
  } as TargetPeriod;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);
const shift = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return iso(d);
};

describe('pickDefaultPeriod', () => {
  it('prefers the monthly period covering today over the annual root', () => {
    const list = [
      period({ id: 1, period_type: 'annual', start_date: shift(-200), end_date: shift(200) }),
      period({ id: 2, period_type: 'monthly', start_date: shift(-45), end_date: shift(-16) }),
      period({ id: 3, period_type: 'monthly', start_date: shift(-15), end_date: shift(15) }),
    ];
    expect(pickDefaultPeriod(list)?.id).toBe(3);
  });

  it('falls back to the most recently started month when none covers today', () => {
    const list = [
      period({ id: 1, period_type: 'annual', start_date: shift(-200), end_date: shift(-100) }),
      period({ id: 2, period_type: 'monthly', start_date: shift(-90), end_date: shift(-61) }),
      period({ id: 3, period_type: 'monthly', start_date: shift(-60), end_date: shift(-31) }),
    ];
    expect(pickDefaultPeriod(list)?.id).toBe(3);
  });

  it('falls back to the first period when there are no monthly ones', () => {
    const list = [
      period({ id: 1, period_type: 'annual', start_date: shift(-200), end_date: shift(200) }),
      period({ id: 2, period_type: 'custom', start_date: shift(-45), end_date: shift(45) }),
    ];
    expect(pickDefaultPeriod(list)?.id).toBe(1);
  });

  it('returns null for an empty list', () => {
    expect(pickDefaultPeriod([])).toBeNull();
  });
});
