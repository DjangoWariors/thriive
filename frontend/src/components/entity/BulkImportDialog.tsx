import {useRef, useState} from 'react';
import {Upload, AlertCircle, CheckCircle, Download} from 'lucide-react';
import {notify} from '../../utils/notify';
import {useQueryClient} from '@tanstack/react-query';
import {Modal} from '../ui/Modal';
import {Button} from '../ui/Button';
import {BulkJobProgress} from '../jobs/BulkJobProgress';
import {useBulkImport, useBlueprint, entityQueryKeys} from '../../hooks/useEntities';
import {entityService} from '../../services/entityService';
import {downloadBlob} from '../../utils/download';
import type {BulkJob} from '../../types/jobs';

interface ParsedRow {
    entity_type_code: string;
    name: string;
    code: string;
    parent_code: string;
    attributes: Record<string, string>;
}

interface ValidationError {
    row: number;
    errors: string[];
}

function parseJsonRows(text: string): ParsedRow[] | null {
    try {
        const parsed: unknown = JSON.parse(text);
        if (!Array.isArray(parsed)) return null;
        return parsed as ParsedRow[];
    } catch {
        return null;
    }
}

/** Best-effort guess of the pasted content's format, to catch toggle mismatches. */
function detectFormat(text: string): 'json' | 'csv' | null {
    const t = text.trim();
    if (!t) return null;
    return t.startsWith('[') || t.startsWith('{') ? 'json' : 'csv';
}

interface Props {
    onClose: () => void;
}

export function BulkImportDialog({onClose}: Props) {
    const [format, setFormat] = useState<'json' | 'csv'>('json');
    const [rawText, setRawText] = useState('');
    const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);
    const [jobId, setJobId] = useState<number | null>(null);
    const [validatedRows, setValidatedRows] = useState<number | null>(null);
    const [templateType, setTemplateType] = useState('');
    const fileRef = useRef<HTMLInputElement>(null);

    const queryClient = useQueryClient();
    const importMutation = useBulkImport();
    const validateMutation = useBulkImport();
    const {data: blueprint = []} = useBlueprint();

    async function handleDownloadTemplate() {
        if (!templateType) return;
        try {
            const blob = await entityService.importTemplate(templateType);
            downloadBlob(blob, `${templateType}_import_template.csv`);
        } catch {
            notify.error('Could not download template.');
        }
    }

    function resetResults() {
        setValidationErrors([]);
        setValidatedRows(null);
    }


    const previewRows: ParsedRow[] | null =
        format === 'json' && rawText.trim() ? parseJsonRows(rawText) : null;

    function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
        const file = e.target.files?.[0];
        if (!file) return;
        const fmt = file.name.endsWith('.csv') ? 'csv' : 'json';
        setFormat(fmt);
        const reader = new FileReader();
        reader.onload = (ev) => {
            setRawText((ev.target?.result as string | null) ?? '');
            resetResults();
        };
        reader.readAsText(file);
    }

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
                        setValidatedRows(null);
                    } else {
                        setValidationErrors([]);
                        setValidatedRows(result.rows ?? 0);
                    }
                },
                onError: () => notify.error('Validation failed unexpectedly.'),
            },
        );
    }

    function handleImport() {
        if (!rawText.trim()) return;

        importMutation.mutate(
            {format, data: rawText},
            {
                onSuccess: (res) => {
                    if (res.async) {
                        // Large import accepted as a background job — switch to polling.
                        resetResults();
                        setJobId(res.job.id);
                        return;
                    }
                    const result = res.result;
                    if (result.status === 'validation_failed') {
                        setValidationErrors(result.errors ?? []);
                        setValidatedRows(null);
                    } else {
                        notify.success(
                            `Import complete: ${result.created ?? 0} entities created` +
                            (result.users_created ? `, ${result.users_created} users created.` : '.'),
                        );
                        onClose();
                    }
                },
                onError: () => notify.error('Import failed unexpectedly.'),
            },
        );
    }

    function handleJobDone(job: BulkJob) {
        void queryClient.invalidateQueries({queryKey: entityQueryKeys.lists()});
        if (job.status === 'completed') {
            const created = (job.result.created as number | undefined) ?? job.success_count;
            notify.success(`Import complete: ${created} entities created.`);
            onClose();
        } else {
            // failed / partial — show the per-row errors and let the user retry.
            setValidationErrors(job.errors ?? []);
            setJobId(null);
        }
    }

    // Build a set of rows with errors for quick lookup
    const errorRows = new Set(validationErrors.map((e) => e.row));

    const detected = detectFormat(rawText);
    const mismatch = detected !== null && detected !== format;
    // Two-phase flow: review (dry-run) first, then commit. A clean dry-run sets validatedRows.
    const reviewed = validatedRows !== null;

    return (
        <Modal
            open
            onClose={onClose}
            title="Bulk Import Entities"
            description="Import entities from a JSON array or CSV file. We check everything first — nothing is created until you confirm."
            size="xl"
            footer={
                jobId !== null ? (
                    <Button variant="secondary" onClick={onClose}>Close</Button>
                ) : !reviewed ? (
                    <>
                        <Button variant="secondary" onClick={onClose}>Cancel</Button>
                        <Button
                            onClick={handleValidate}
                            loading={validateMutation.isPending}
                            disabled={!rawText.trim()}
                        >
                            Review import
                        </Button>
                    </>
                ) : (
                    <>
                        <Button variant="secondary" onClick={resetResults}>Back</Button>
                        <Button
                            onClick={handleImport}
                            loading={importMutation.isPending}
                        >
                            Import {validatedRows} {validatedRows === 1 ? 'row' : 'rows'}
                        </Button>
                    </>
                )
            }
        >
            <div className="space-y-4">

                {jobId !== null && <BulkJobProgress jobId={jobId} onDone={handleJobDone}/>}


                <div className="flex items-center gap-3">
                    <button
                        type="button"
                        onClick={() => fileRef.current?.click()}
                        className="flex items-center gap-2 rounded-lg border border-dashed border-gray-300 px-4 py-2 text-sm text-gray-500 hover:border-primary hover:text-primary transition-colors"
                    >
                        <Upload className="h-4 w-4"/>
                        Upload file
                    </button>
                    <input ref={fileRef} type="file" accept=".json,.csv" className="hidden"
                           onChange={handleFileChange}/>

                    <div className="flex rounded-lg border border-gray-200 overflow-hidden">
                        {(['json', 'csv'] as const).map((f) => (
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

                    {detected && (
                        mismatch ? (
                            <button
                                type="button"
                                onClick={() => {
                                    setFormat(detected);
                                    resetResults();
                                }}
                                className="rounded-full bg-warning-100 px-2 py-0.5 text-[11px] font-medium text-warning hover:bg-warning-100/70"
                            >
                                Looks like {detected.toUpperCase()} — switch?
                            </button>
                        ) : (
                            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                                Detected: {detected.toUpperCase()}
                            </span>
                        )
                    )}


                    <div className="ml-auto flex items-center gap-1.5">
                        <select
                            value={templateType}
                            onChange={(e) => setTemplateType(e.target.value)}
                            className="rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-600
                         focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                        >
                            <option value="">Template…</option>
                            {blueprint.map((t) => (
                                <option key={t.code} value={t.code}>{t.name}</option>
                            ))}
                        </select>
                        <button
                            type="button"
                            onClick={handleDownloadTemplate}
                            disabled={!templateType}
                            className="flex items-center gap-1 text-sm text-primary hover:underline disabled:text-gray-300 disabled:no-underline"
                        >
                            <Download className="h-4 w-4"/>
                            CSV
                        </button>
                    </div>
                </div>


                <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">
                        {format === 'json' ? 'JSON Array' : 'CSV Data'}
                    </label>
                    {format === 'json' && (
                        <p className="mb-1 text-xs text-gray-400">
                            Example: {`[{"entity_type_code":"NSM","name":"John","code":"NSM_001","parent_code":null,"attributes":{}}]`}
                        </p>
                    )}
                    {format === 'csv' && (
                        <p className="mb-1 text-xs text-gray-400">
                            First row is the header. Columns:{' '}
                            <code className="rounded bg-gray-100 px-1">entity_type_code</code>,{' '}
                            <code className="rounded bg-gray-100 px-1">name</code>,{' '}
                            <code className="rounded bg-gray-100 px-1">code</code>,{' '}
                            <code className="rounded bg-gray-100 px-1">parent_code</code>, then one column per
                            attribute. Use <span className="font-medium">Template…</span> above for a type’s exact columns.
                        </p>
                    )}
                    <textarea
                        value={rawText}
                        onChange={(e) => {
                            setRawText(e.target.value);
                            resetResults();
                        }}
                        rows={6}
                        placeholder={format === 'json' ? '[{"entity_type_code": "...", "name": "...", ...}]' : 'entity_type_code,name,code,parent_code\n...'}
                        className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 font-mono text-xs
                       focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
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
                                    <th className="px-3 py-2 w-6">#</th>
                                    <th className="px-3 py-2">Type</th>
                                    <th className="px-3 py-2">Name</th>
                                    <th className="px-3 py-2">Code</th>
                                    <th className="px-3 py-2">Parent</th>
                                    <th className="px-3 py-2 w-6"/>
                                </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                {previewRows.map((row, i) => {
                                    const rowNum = i + 1;
                                    const hasError = errorRows.has(rowNum);
                                    return (
                                        <tr key={i} className={hasError ? 'bg-danger-50' : ''}>
                                            <td className="px-3 py-1.5 text-gray-500">{rowNum}</td>
                                            <td className="px-3 py-1.5 font-mono">{row.entity_type_code}</td>
                                            <td className="px-3 py-1.5">{row.name}</td>
                                            <td className="px-3 py-1.5 font-mono">{row.code}</td>
                                            <td className="px-3 py-1.5 text-gray-500">{row.parent_code || '—'}</td>
                                            <td className="px-3 py-1.5">
                                                {hasError ? (
                                                    <AlertCircle className="h-3.5 w-3.5 text-danger"/>
                                                ) : reviewed ? (
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


                {reviewed && (
                    <div className="flex items-center gap-2 rounded-lg bg-success-50 px-4 py-3 text-sm text-success">
                        <CheckCircle className="h-4 w-4 shrink-0"/>
                        <span>
              All {validatedRows} row{validatedRows !== 1 ? 's' : ''} look good — nothing imported yet.
              Use <span className="font-medium">Import {validatedRows} {validatedRows === 1 ? 'row' : 'rows'}</span> below to commit.
            </span>
                    </div>
                )}


                {validationErrors.length > 0 && (
                    <div className="rounded-lg bg-danger-50 px-4 py-3">
                        <p className="mb-2 text-sm font-medium text-danger">
                            {validationErrors.length} row{validationErrors.length !== 1 ? 's' : ''} need fixing
                            before import — nothing was created.
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
