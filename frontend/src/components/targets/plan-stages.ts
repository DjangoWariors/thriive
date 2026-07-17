import type { TargetPlan } from '../../types/target';

export type StageKey = 'top' | 'spatial' | 'product' | 'review' | 'publish';

export interface PlanStage {
  key: StageKey;
  label: string;
  done: boolean;
}

export function isLive(plan: TargetPlan): boolean {
  return ['published', 'locked', 'closed'].includes(plan.status);
}

/** The linear plan pipeline. Done flags mirror the backend's own signals: top numbers set,
 * committed run stages, and plan status — nothing is inferred client-side. */
export function planStages(plan: TargetPlan): PlanStage[] {
  const committed = plan.progress.committed_stages;
  const stages: PlanStage[] = [
    {
      key: 'top', label: 'Top numbers',
      done: plan.kpis.length > 0 && plan.kpis.every((k) => k.top_value !== null),
    },
    { key: 'spatial', label: 'Territory split', done: committed.includes('spatial') },
  ];
  if (plan.product_scope.length) {
    stages.push({ key: 'product', label: 'Product split', done: committed.includes('product') });
  }
  stages.push(
    { key: 'review', label: 'Field review', done: plan.status !== 'draft' },
    { key: 'publish', label: 'Publish', done: isLive(plan) },
  );
  return stages;
}

/** Where the workspace lands by default: the first thing still to do. */
export function activeStageKey(stages: PlanStage[]): StageKey {
  return (stages.find((s) => !s.done) ?? stages[stages.length - 1]!).key;
}
