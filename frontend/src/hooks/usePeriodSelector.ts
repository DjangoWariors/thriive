import { useSearchParams } from 'react-router';
import type { TargetPeriod } from '../types/target';

/** The period a dashboard should open on. Targets are planned monthly, so prefer the
 * month covering today, else the most recently started month — never the annual root
 * (it sorts first by start_date and would open an empty year view). */
export function pickDefaultPeriod(list: TargetPeriod[]): TargetPeriod | null {
  const monthly = list.filter((p) => p.period_type === 'monthly');
  const today = new Date().toISOString().slice(0, 10);
  return (
    monthly.find((p) => p.start_date <= today && p.end_date >= today)
    ?? [...monthly].reverse().find((p) => p.start_date <= today)
    ?? monthly[0]
    ?? list[0]
    ?? null
  );
}

export function usePeriodSelector() {
  const [searchParams, setSearchParams] = useSearchParams();

  const raw = searchParams.get('period');
  const selectedPeriodId: number | null = raw !== null ? Number(raw) : null;

  function setSelectedPeriodId(id: number | null, opts?: { replace?: boolean }): void {
    const next = new URLSearchParams(searchParams);
    if (id === null) {
      next.delete('period');
    } else {
      next.set('period', String(id));
    }
    // A period is a filter, not a navigation step. Replacing (rather than pushing)
    // keeps the browser Back button working — otherwise the auto-default re-pushes
    // the period on every return to a period-less URL and Back appears to bounce.
    setSearchParams(next, { replace: opts?.replace ?? true });
  }

  return { selectedPeriodId, setSelectedPeriodId };
}
