import { describe, expect, it } from 'vitest';
import { RUN_STALL_MS, isRunActive, isRunStalled, runNeedsAttention } from './planRun';
import type { PlanRun, RunStatus } from '../types/target';

function run(status: RunStatus, ageMs = 0): PlanRun {
  return {
    id: 1, plan: 1, plan_code: 'P', kind: 'spatial', status,
    scope_node: null, scope_node_code: null, config_snapshot: {}, stats: {},
    job: null, error: '', committed_by: null, committed_at: null,
    created_at: new Date(Date.now() - ageMs).toISOString(),
  };
}

describe('isRunStalled', () => {
  it('leaves a run that is still within the cutoff alone', () => {
    expect(isRunStalled(run('pending', RUN_STALL_MS / 2))).toBe(false);
    expect(isRunActive(run('running', RUN_STALL_MS / 2))).toBe(true);
  });

  it('gives up on a run no worker ever finished', () => {
    expect(isRunStalled(run('pending', RUN_STALL_MS + 1000))).toBe(true);
    expect(isRunActive(run('pending', RUN_STALL_MS + 1000))).toBe(false);
  });

  it('never calls a settled run stalled, however old', () => {
    for (const s of ['staged', 'committed', 'discarded', 'failed'] as RunStatus[]) {
      expect(isRunStalled(run(s, RUN_STALL_MS * 100))).toBe(false);
    }
  });
});

describe('runNeedsAttention', () => {
  it('flags failed and stalled runs, not healthy ones', () => {
    expect(runNeedsAttention(run('failed'))).toBe(true);
    expect(runNeedsAttention(run('running', RUN_STALL_MS + 1000))).toBe(true);
    expect(runNeedsAttention(run('running'))).toBe(false);
    expect(runNeedsAttention(run('staged'))).toBe(false);
  });
});
