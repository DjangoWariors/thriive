import {useEffect, useRef} from 'react';
import {Loader2, CheckCircle, AlertCircle} from 'lucide-react';
import {useBulkJob} from '../../hooks/useBulkJob';
import {isTerminalStatus, type BulkJob} from '../../types/jobs';

interface Props {
    jobId: number;

    onDone?: (job: BulkJob) => void;
}

const STATUS_LABEL: Record<string, string> = {
    queued: 'Queued…',
    validating: 'Validating…',
    running: 'Importing…',
    completed: 'Completed',
    failed: 'Failed',
    partial: 'Completed with errors',
};

export function BulkJobProgress({jobId, onDone}: Props) {
    const {data: job} = useBulkJob(jobId);
    const firedRef = useRef(false);

    useEffect(() => {
        if (job && isTerminalStatus(job.status) && !firedRef.current) {
            firedRef.current = true;
            onDone?.(job);
        }
    }, [job, onDone]);

    if (!job) {
        return (
            <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-4 py-3 text-sm text-gray-500">
                <Loader2 className="h-4 w-4 animate-spin"/>
                Starting background job…
            </div>
        );
    }

    const total = job.total_rows || 0;
    const pct = total > 0 ? Math.min((job.processed_rows / total) * 100, 100) : 0;
    const done = isTerminalStatus(job.status);
    const failed = job.status === 'failed';
    const partial = job.status === 'partial';

    const barColor = failed ? 'bg-danger' : partial ? 'bg-warning' : done ? 'bg-success' : 'bg-primary';

    return (
        <div className="space-y-3 rounded-lg border border-gray-200 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
                {!done && <Loader2 className="h-4 w-4 animate-spin text-primary"/>}
                {job.status === 'completed' && <CheckCircle className="h-4 w-4 text-success"/>}
                {(failed || partial) && <AlertCircle className="h-4 w-4 text-warning"/>}
                <span>{STATUS_LABEL[job.status] ?? job.status}</span>
                <span className="ml-auto text-xs font-normal text-gray-400">
          {job.processed_rows.toLocaleString('en-IN')}
                    {total > 0 ? ` / ${total.toLocaleString('en-IN')}` : ''}
        </span>
            </div>

            <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
                <div
                    className={`h-full rounded-full transition-all duration-300 ${barColor}`}
                    style={{width: `${done ? 100 : pct}%`}}
                />
            </div>

            <div className="flex gap-4 text-xs text-gray-500">
                <span className="text-success">{job.success_count.toLocaleString('en-IN')} succeeded</span>
                {job.error_count > 0 && (
                    <span className="text-danger">{job.error_count.toLocaleString('en-IN')} failed</span>
                )}
            </div>

            {job.errors.length > 0 && (
                <div className="max-h-40 overflow-auto rounded-lg bg-danger-50 px-3 py-2">
                    <ul className="space-y-1">
                        {job.errors.map((e) => (
                            <li key={e.row} className="text-xs text-danger">
                                <span className="font-medium">Row {e.row}:</span> {e.errors.join(', ')}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}
