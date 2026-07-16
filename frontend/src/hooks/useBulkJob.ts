import { useQuery } from '@tanstack/react-query';
import { jobService } from '../services/jobService';
import { isTerminalStatus, type BulkJob } from '../types/jobs';

const POLL_INTERVAL_MS = 1000;

/**
 * Poll a bulk job until it reaches a terminal state, then stop.
 * Pass `null` to disable (e.g. before a job has been created).
 */
export function useBulkJob(jobId: number | null) {
  return useQuery({
    queryKey: ['bulk-job', jobId],
    queryFn: () => jobService.get(jobId as number),
    enabled: jobId !== null && jobId > 0,
    refetchInterval: (query) => {
      const job = query.state.data as BulkJob | undefined;
      if (!job) return POLL_INTERVAL_MS;
      return isTerminalStatus(job.status) ? false : POLL_INTERVAL_MS;
    },
  });
}
