import type { TargetPeriodNode } from '../types/target';

/** Flatten a period tree into dropdown options — months only (targets are always set
 * monthly; the annual root is just the container and is never a valid target period). */
export function flattenPeriods(node: TargetPeriodNode | undefined): { value: string; label: string }[] {
  return monthlyNodes(node).map((n) => ({ value: String(n.id), label: n.name }));
}

/** The month a period picker should default to: the one covering today, else the most
 * recently started, else the first of the year. */
export function defaultMonthId(node: TargetPeriodNode | undefined): number | null {
  const months = monthlyNodes(node);
  const today = new Date().toISOString().slice(0, 10);
  const pick =
    months.find((m) => m.start_date <= today && m.end_date >= today)
    ?? [...months].reverse().find((m) => m.start_date <= today)
    ?? months[0];
  return pick ? pick.id : null;
}

function monthlyNodes(node: TargetPeriodNode | undefined): TargetPeriodNode[] {
  if (!node) return [];
  const own = node.period_type === 'monthly' ? [node] : [];
  return [...own, ...node.children.flatMap(monthlyNodes)];
}
