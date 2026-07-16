import {useRef, useState} from 'react';
import {Upload, AlertCircle, CheckCircle, Download} from 'lucide-react';
import {useQueryClient} from '@tanstack/react-query';
import {Modal} from '../ui/Modal';
import {Button} from '../ui/Button';
import {BulkJobProgress} from '../jobs/BulkJobProgress';
import {useBulkImportUsers, adminKeys} from '../../hooks/useAdmin';
import type {UserImportError} from '../../types/admin';
import type {BulkJob} from '../../types/jobs';
import {notify} from '../../utils/notify';

interface ParsedRow {
    first_name?: string;
    last_name?: string;
    email?: string;
    mobile?: string;
    employee_id?: string;
    roles?: string;
    entity_code?: string;
}

const CSV_HEADER =
    'first_name,last_name,email,mobile,employee_id,designation,department,password,roles,entity_code';
const CSV_SAMPLE = `${CSV_HEADER}\nDeepa,Sharma,deepa@acme.com,9876543210,EMP001,Area Sales Exec,Sales,,sales_exec,ASE_DEEPA`;

function parseJsonRows(text: string): ParsedRow[] | null {
    try {
        const parsed: unknown = JSON.parse(text);
        return Array.isArray(parsed) ? (parsed as ParsedRow[]) : null;
    } catch {
        return null;
    }
}

interface Props {
    onClose: () => void;
}

export function UserBulkImportDialog({onClose}: Props) {
    const [format, setFormat] = useState<'csv' | 'json'>('csv');
    const [rawText, setRawText] = useState('');
    const [validationErrors, setValidationErrors] = useState<UserImportError[]>([]);
    const [lastStatus, setLastStatus] = useState<'idle' | 'failed' | 'success'>('idle');
    const [jobId, setJobId] = useState<number | null>(null);
    const [validatedRows, setValidatedRows] = useState<number | null>(null);
    const fileRef = useRef<HTMLInputElement>(null);

    const queryClient = useQueryClient();
    const importMutation = useBulkImportUsers();
    const validateMutation = useBulkImportUsers();

    const previewRows = format === 'json' && rawText.trim() ? parseJsonRows(rawText) : null;

    const reset = () => {
        setValidationErrors([]);
        setLastStatus('idle');
        setValidatedRows(null);
    };

    function handleValidate() {
        if (!rawText.trim()) return;
        validateMutation.mutate(
            {format, data: rawText, dry_run: true},
            {
                onSuccess: (res) => {
                    if (res.async) return;
                    const result = res.result;
                    if (result.status === 'validation_failed') {
                        setValidationErrors(result.errors ?? []);
                        setLastStatus('failed');
                        setValidatedRows(null);
                    } else {
                        setValidationErrors([]);
                        setLastStatus('idle');
                        setValidatedRows(result.rows ?? 0);
                    }
                },
                onError: () => notify.error('Validation failed unexpectedly.'),
            },
        );
    }

    function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
        const file = e.target.files?.[0];
        if (!file) return;
        setFormat(file.name.endsWith('.json') ? 'json' : 'csv');
        const reader = new FileReader();
        reader.onload = (ev) => {
            setRawText((ev.target?.result as string | null) ?? '');
            reset();
        };
        reader.readAsText(file);
    }

    function downloadTemplate() {
        const blob = new Blob([CSV_SAMPLE], {type: 'text/csv'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'users-template.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    function handleImport() {
        if (!rawText.trim()) return;
        importMutation.mutate(
            {format, data: rawText},
            {
                onSuccess: (res) => {
                    if (res.async) {
                        reset();
                        setJobId(res.job.id);
                        return;
                    }
                    const result = res.result;
                    if (result.status === 'validation_failed') {
                        setValidationErrors(result.errors ?? []);
                        setLastStatus('failed');
                        setValidatedRows(null);
                    } else {
                        notify.success(`Import complete: ${result.created ?? 0} user(s) created.`);
                        setLastStatus('success');
                        onClose();
                    }
                },
                onError: () => notify.error('Import failed unexpectedly.'),
            },
        );
    }

    function handleJobDone(job: BulkJob) {
        void queryClient.invalidateQueries({queryKey: ['admin', 'users']});
        void queryClient.invalidateQueries({queryKey: adminKeys.departments()});
        if (job.status === 'completed') {
            const created = (job.result.created as number | undefined) ?? job.success_count;
            notify.success(`Import complete: ${created} user(s) created.`);
            onClose();
        } else {
            setValidationErrors(job.errors ?? []);
            setLastStatus('failed');
            setJobId(null);
        }
    }

    const errorRows = new Set(validationErrors.map((e) => e.row));

    return (
        <Modal
            open
            onClose={onClose}
            title="Bulk Import Users"
            description="Upload a CSV or JSON array. All-or-nothing: if any row fails validation, nothing is created."
            size="xl"
            footer={
                <>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        variant="outline"
                        onClick={handleValidate}
                        loading={validateMutation.isPending}
                        disabled={!rawText.trim() || jobId !== null || importMutation.isPending}
                    >
                        Validate
                    </Button>
                    <Button
                        onClick={handleImport}
                        loading={importMutation.isPending}
                        disabled={!rawText.trim() || jobId !== null || validateMutation.isPending}
                    >
                        Import
                    </Button>
                </>
            }
        >
            <div className="space-y-4">
                {jobId !== null && <BulkJobProgress jobId={jobId} onDone={handleJobDone}/>}

                <div className="flex flex-wrap items-center gap-3">
                    <button
                        type="button"
                        onClick={() => fileRef.current?.click()}
                        className="flex items-center gap-2 rounded-lg border border-dashed border-gray-300 px-4 py-2 text-sm text-gray-500 transition-colors hover:border-primary hover:text-primary"
                    >
                        <Upload className="h-4 w-4"/>
                        Upload file
                    </button>
                    <input
                        ref={fileRef}
                        type="file"
                        accept=".csv,.json"
                        className="hidden"
                        onChange={handleFileChange}
                    />

                    <div className="flex overflow-hidden rounded-lg border border-gray-200">
                        {(['csv', 'json'] as const).map((f) => (
                            <button
                                key={f}
                                type="button"
                                onClick={() => setFormat(f)}
                                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                                    format === f ? 'bg-primary text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                                }`}
                            >
                                {f.toUpperCase()}
                            </button>
                        ))}
                    </div>

                    <button
                        type="button"
                        onClick={downloadTemplate}
                        className="ml-auto flex items-center gap-1.5 text-sm text-primary hover:underline"
                    >
                        <Download className="h-4 w-4"/>
                        CSV template
                    </button>
                </div>

                <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">
                        {format === 'csv' ? 'CSV data' : 'JSON array'}
                    </label>
                    <p className="mb-1 text-xs text-gray-400">
                        Columns: first_name, last_name, email, mobile, employee_id, designation, department,
                        password, roles (comma-separated role codes), entity_code (optional — links to an
                        existing entity). At least one of email/mobile/employee_id is required.
                    </p>
                    <textarea
                        value={rawText}
                        onChange={(e) => {
                            setRawText(e.target.value);
                            reset();
                        }}
                        rows={7}
                        placeholder={format === 'csv' ? CSV_HEADER : '[{"first_name": "...", "roles": "sales_exec"}]'}
                        className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 font-mono text-xs focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                </div>

                {previewRows && previewRows.length > 0 && (
                    <div>
                        <p className="mb-1 text-sm font-medium text-gray-700">
                            Preview — {previewRows.length} row{previewRows.length !== 1 ? 's' : ''}
                        </p>
                        <div className="max-h-48 overflow-auto rounded-lg border border-gray-200">
                            <table className="w-full text-xs">
                                <thead className="sticky top-0 bg-gray-50">
                                <tr className="text-left text-gray-500">
                                    <th className="w-6 px-3 py-2">#</th>
                                    <th className="px-3 py-2">Name</th>
                                    <th className="px-3 py-2">Email / Mobile</th>
                                    <th className="px-3 py-2">Roles</th>
                                    <th className="px-3 py-2">Entity</th>
                                    <th className="w-6 px-3 py-2"/>
                                </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                {previewRows.map((row, i) => {
                                    const rowNum = i + 1;
                                    const hasError = errorRows.has(rowNum);
                                    return (
                                        <tr key={i} className={hasError ? 'bg-danger-50' : ''}>
                                            <td className="px-3 py-1.5 text-gray-500">{rowNum}</td>
                                            <td className="px-3 py-1.5">
                                                {`${row.first_name ?? ''} ${row.last_name ?? ''}`.trim() || '—'}
                                            </td>
                                            <td className="px-3 py-1.5 font-mono text-gray-500">
                                                {row.email || row.mobile || row.employee_id || '—'}
                                            </td>
                                            <td className="px-3 py-1.5 font-mono text-gray-500">{row.roles || '—'}</td>
                                            <td className="px-3 py-1.5 font-mono text-gray-500">
                                                {row.entity_code || '—'}
                                            </td>
                                            <td className="px-3 py-1.5">
                                                {hasError ? (
                                                    <AlertCircle className="h-3.5 w-3.5 text-danger"/>
                                                ) : lastStatus === 'success' ? (
                                                    <CheckCircle className="h-3.5 w-3.5 text-success"/>
                                                ) : null}
                                            </td>
                                        </tr>
                                    );
                                })}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {validatedRows !== null && (
                    <div className="flex items-center gap-2 rounded-lg bg-success-50 px-4 py-3 text-sm text-success">
                        <CheckCircle className="h-4 w-4"/>
                        <span>
              {validatedRows} row{validatedRows !== 1 ? 's' : ''} valid — nothing imported yet.
              Click <span className="font-medium">Import</span> to commit.
            </span>
                    </div>
                )}

                {validationErrors.length > 0 && (
                    <div className="rounded-lg bg-danger-50 px-4 py-3">
                        <p className="mb-2 text-sm font-medium text-danger">
                            Validation failed — {validationErrors.length} row
                            {validationErrors.length !== 1 ? 's' : ''} with errors. Nothing was imported.
                        </p>
                        <ul className="space-y-1">
                            {validationErrors.map((e) => (
                                <li key={e.row} className="text-xs text-danger">
                                    <span className="font-medium">Row {e.row}:</span> {e.errors.join(', ')}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </Modal>
    );
}
