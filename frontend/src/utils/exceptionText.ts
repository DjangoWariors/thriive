import type { KpiExceptionAction, PayoutException } from '../types/incentive';

/**
 * How each treatment reads in a sentence. The raise form, the list row and the detail
 * drawer all describe the same stored code, so they share one wording — an exception
 * that says "1×" in one place and "on target" in another reads like two different rules.
 */
export const ACTION_PHRASES: Record<KpiExceptionAction, string> = {
  actual_performance: 'computed normally',
  default_1x: 'paid as if exactly on target (1×)',
  zero: 'not paid',
};

/** Table-cell summary: only what departs from normal computation. */
export function actionSummary(e: PayoutException): string {
  const parts: string[] = [];
  if (e.sales_kpi_action !== 'actual_performance') {
    parts.push(`sales ${e.sales_kpi_action === 'default_1x' ? '1×' : 'zero'}`);
  }
  if (e.execution_kpi_action !== 'actual_performance') {
    parts.push(`execution ${e.execution_kpi_action === 'default_1x' ? '1×' : 'zero'}`);
  }
  if (e.gatekeeper_action === 'exempted') parts.push('gatekeeper exempted');
  return parts.length ? parts.join(' · ') : 'actuals';
}
