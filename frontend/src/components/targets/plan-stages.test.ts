import { describe, expect, it } from 'vitest';
import { activeStageKey, isLive, planStages } from './plan-stages';
import type { TargetPlan } from '../../types/target';

function plan(over: Partial<TargetPlan>): TargetPlan {
  return {
    id: 1, name: 'P', code: 'P', period: 1, period_code: 'FY-M01', period_type: 'monthly',
    root_geography: 1, root_geography_name: 'India', root_geography_code: 'IN',
    channel: null, planning_grain: '', review_levels: [], product_scope: [],
    settings: {}, status: 'draft', owner: null,
    kpis: [{ id: 1, kpi: 10, kpi_code: 'K', kpi_name: 'K', recipe: null, recipe_code: null,
             baseline_spec: {}, product_split: {}, top_value: null, derived_top_value: null }],
    progress: { runs: { staged: 0, committed: 0 }, committed_stages: [], review: { total: 0, open: 0 } },
    created_at: '',
    ...over,
  } as TargetPlan;
}

describe('planStages', () => {
  it('starts a fresh draft at Top numbers with nothing done', () => {
    const stages = planStages(plan({}));
    expect(stages.map((s) => s.key)).toEqual(['top', 'spatial', 'review', 'publish']);
    expect(stages.every((s) => !s.done)).toBe(true);
    expect(activeStageKey(stages)).toBe('top');
  });

  it('includes the product stage only when the plan has a product scope', () => {
    const stages = planStages(plan({ product_scope: ['FOCUS'] }));
    expect(stages.map((s) => s.key)).toEqual(['top', 'spatial', 'product', 'review', 'publish']);
  });

  it('advances through the pipeline as backend signals land', () => {
    const p = plan({
      kpis: [{ id: 1, kpi: 10, kpi_code: 'K', kpi_name: 'K', recipe: null, recipe_code: null,
               baseline_spec: {}, product_split: {}, top_value: '1000', derived_top_value: '900' }],
      progress: { runs: { staged: 0, committed: 1 }, committed_stages: ['spatial'], review: { total: 0, open: 0 } },
    });
    const stages = planStages(p);
    expect(stages.find((s) => s.key === 'top')?.done).toBe(true);
    expect(stages.find((s) => s.key === 'spatial')?.done).toBe(true);
    expect(activeStageKey(stages)).toBe('review');
  });

  it('marks review done once the plan leaves draft, publish once live', () => {
    expect(planStages(plan({ status: 'in_review' })).find((s) => s.key === 'review')?.done).toBe(true);
    const published = planStages(plan({ status: 'published' }));
    expect(published.find((s) => s.key === 'publish')?.done).toBe(true);
    expect(isLive(plan({ status: 'published' }))).toBe(true);
    expect(isLive(plan({ status: 'in_review' }))).toBe(false);
  });

  it('lands on the last stage when everything is done', () => {
    const done = plan({
      status: 'locked',
      kpis: [{ id: 1, kpi: 10, kpi_code: 'K', kpi_name: 'K', recipe: null, recipe_code: null,
               baseline_spec: {}, product_split: {}, top_value: '1000', derived_top_value: '900' }],
      progress: { runs: { staged: 0, committed: 1 }, committed_stages: ['spatial'], review: { total: 0, open: 0 } },
    });
    expect(activeStageKey(planStages(done))).toBe('publish');
  });
});
