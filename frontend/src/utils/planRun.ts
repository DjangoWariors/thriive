import type { PlanRun } from '../types/target';

/** How long a run may sit unfinished before the UI stops waiting on it.
 *
 * A run is dispatched to a Celery worker and only the worker moves it off pending/running.
 * If the worker never picks it up (queue nobody consumes, stale code) or dies mid-task
 * (hard time limit, OOM), the row stays that way forever — and a UI that keys purely off
 * the status spins forever with it. Past this cutoff we call it stalled: release the
 * button, say so, and let the admin start a fresh run. */
export const RUN_STALL_MS = 5 * 60 * 1000;

/** Tolerates a few minutes of browser/server clock skew by construction — the cutoff is
 * long enough that skew shifts the moment we give up, never whether we give up. */
export function isRunStalled(run: PlanRun): boolean {
  if (run.status !== 'pending' && run.status !== 'running') return false;
  return Date.now() - new Date(run.created_at).getTime() > RUN_STALL_MS;
}

/** In flight and still believable — the only state worth showing a spinner or polling for. */
export function isRunActive(run: PlanRun): boolean {
  return (run.status === 'pending' || run.status === 'running') && !isRunStalled(run);
}

/** A run the admin needs to know about: it failed, or it stopped reporting back. */
export function runNeedsAttention(run: PlanRun): boolean {
  return run.status === 'failed' || isRunStalled(run);
}
