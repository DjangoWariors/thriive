import { useNavigate, useSearchParams } from 'react-router';
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
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const raw = searchParams.get('period');
  const selectedPeriodId: number | null = raw !== null ? Number(raw) : null;

  function setSelectedPeriodId(id: number | null, opts?: { replace?: boolean }): void {
    // Read the live URL rather than this render's location. The header's auto-default
    // fires from a closure captured before a redirect route (<Navigate>) has moved us,
    // and `setSearchParams` resolves "?params" against that stale pathname — which
    // bounced the app back onto the path it had just left. <Navigate> only fires once
    // per mount, so its redirect was spent and the outlet rendered nothing: every
    // legacy URL (/hierarchy, /geography, /admin/api-keys…) opened blank on a cold load.
    // Writing an explicit pathname keeps a period change a pure query-string edit.
    const next = new URLSearchParams(window.location.search);
    if (id === null) {
      next.delete('period');
    } else {
      next.set('period', String(id));
    }
    const search = next.toString();
    // A period is a filter, not a navigation step. Replacing (rather than pushing)
    // keeps the browser Back button working — otherwise the auto-default re-pushes
    // the period on every return to a period-less URL and Back appears to bounce.
    navigate(
      { pathname: window.location.pathname, search: search ? `?${search}` : '' },
      { replace: opts?.replace ?? true },
    );
  }

  return { selectedPeriodId, setSelectedPeriodId };
}
