import {useMemo, useState} from 'react';
import {useForm} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {z} from 'zod';
import {Plus, Pencil, Trash2, Search, Package, Upload} from 'lucide-react';
import {
    useSKUs,
    useSKUFacets,
    useCreateSKU,
    useUpdateSKU,
    useDeactivateSKU,
    useBulkImportSKUs,
} from '../../hooks/useMasterData';
import {useQueryClient} from '@tanstack/react-query';
import {useRBAC} from '../../hooks/useRBAC';
import type {SKU, SKUPayload, BulkImportResult} from '../../types/master';
import type {BulkJob} from '../../types/jobs';
import {BulkJobProgress} from '../../components/jobs/BulkJobProgress';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {Card} from '../../components/ui/Card';
import {Badge} from '../../components/ui/Badge';
import {Modal} from '../../components/ui/Modal';
import {EmptyState} from '../../components/ui/EmptyState';
import {ConfirmDialog} from '../../components/ui/ConfirmDialog';
import {Pagination} from '../../components/ui/Pagination';
import {PageHeader} from '../../components/ui/PageHeader';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {SimpleTable} from '../../components/ui/SimpleTable';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';

const skuSchema = z.object({
    code: z.string().min(1, 'Code is required'),
    name: z.string().min(1, 'Name is required'),
    brand: z.string(),
    category: z.string(),
    sub_category: z.string(),
    mrp: z.string().regex(/^\d*\.?\d*$/, 'MRP must be a number').or(z.literal('')),
    is_focus: z.boolean(),
    is_npi: z.boolean(),
});

type SKUFormValues = z.infer<typeof skuSchema>;

export default function SKUsPage() {
    const [search, setSearch] = useState('');
    const [brand, setBrand] = useState('');
    const [category, setCategory] = useState('');
    const [focusOnly, setFocusOnly] = useState(false);

    const [page, setPage] = useState(1);
    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<SKU | null>(null);
    const [deleting, setDeleting] = useState<SKU | null>(null);
    const [importOpen, setImportOpen] = useState(false);

    const params = useMemo(
        () => ({
            page,
            ...(search ? {search} : {}),
            ...(brand ? {brand} : {}),
            ...(category ? {category} : {}),
            ...(focusOnly ? {is_focus: true} : {}),
        }),
        [page, search, brand, category, focusOnly],
    );

    const {canWrite} = useRBAC();
    const writable = canWrite('master_data');

    const {data: resp, isLoading} = useSKUs(params);
    const deactivate = useDeactivateSKU();
    const skus = resp?.results ?? [];

    // Filter options come from a dedicated facets endpoint so every brand/category is
    // listed — not just the values present on the current page of results.
    const {data: facets} = useSKUFacets();
    const brandOptions = facets?.brands ?? [];
    const categoryOptions = facets?.categories ?? [];

    const confirmDelete = () => {
        if (!deleting) return;
        deactivate.mutate(deleting.id, {
            onSuccess: () => {
                notify.success(`${deleting.code} deactivated`);
                setDeleting(null);
            },
            onError: (e) => notify.error(apiErrorMessage(e, 'Could not deactivate SKU')),
        });
    };

    return (
        <div className="p-6">
            <PageHeader
                title="Products (SKUs)"
                description="Your product master — codes, brands, prices, flags."
                actions={writable && (
                    <>
                        <Button variant="outline" icon={<Upload className="h-4 w-4"/>} onClick={() => setImportOpen(true)}>
                            Bulk Import
                        </Button>
                        <Button
                            icon={<Plus className="h-4 w-4"/>}
                            onClick={() => {
                                setEditing(null);
                                setFormOpen(true);
                            }}
                        >
                            Add Product
                        </Button>
                    </>
                )}
            />


            <div className="mb-4 flex flex-wrap items-end gap-3">
                <div className="w-64">
                    <Input
                        placeholder="Search by code or name…"
                        value={search}
                        onChange={(e) => {
                            setSearch(e.target.value);
                            setPage(1);
                        }}
                        leftIcon={<Search className="h-4 w-4"/>}
                    />
                </div>
                <div className="w-44">
                    <Select
                        value={brand}
                        onChange={(e) => {
                            setBrand(e.target.value);
                            setPage(1);
                        }}
                        options={[{value: '', label: 'All brands'}, ...brandOptions.map((b) => ({value: b, label: b}))]}
                    />
                </div>
                <div className="w-44">
                    <Select
                        value={category}
                        onChange={(e) => {
                            setCategory(e.target.value);
                            setPage(1);
                        }}
                        options={[
                            {value: '', label: 'All categories'},
                            ...categoryOptions.map((c) => ({value: c, label: c})),
                        ]}
                    />
                </div>
                <label className="flex cursor-pointer items-center gap-2 py-2 text-sm text-gray-700">
                    <input
                        type="checkbox"
                        checked={focusOnly}
                        onChange={(e) => {
                            setFocusOnly(e.target.checked);
                            setPage(1);
                        }}
                        className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                    />
                    Focus only
                </label>
            </div>

            {isLoading ? (
                <TableSkeleton/>
            ) : skus.length === 0 ? (
                <Card>
                    <EmptyState icon={Package} title="No products found"
                                description="Add your first product or adjust filters."/>
                </Card>
            ) : (
                <Card padding="none">
                    <SimpleTable
                        rows={skus}
                        rowKey={(s) => s.id}
                        columns={[
                            {header: 'Code', render: (s) => (
                                <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{s.code}</code>
                            )},
                            {header: 'Name', render: (s) => <span className="font-medium text-gray-900">{s.name}</span>},
                            {header: 'Brand', render: (s) => <span className="text-gray-600">{s.brand || '—'}</span>},
                            {header: 'Category', render: (s) => <span className="text-gray-600">{s.category || '—'}</span>},
                            {header: 'MRP', align: 'right', render: (s) => (
                                <span className="text-gray-600">{s.mrp !== null ? `₹${s.mrp}` : '—'}</span>
                            )},
                            {header: 'Flags', align: 'center', render: (s) => (
                                <div className="flex justify-center gap-1">
                                    {s.is_focus && <Badge variant="success">Focus</Badge>}
                                    {s.is_npi && <Badge variant="info">NPI</Badge>}
                                    {!s.is_focus && !s.is_npi && <span className="text-gray-300">—</span>}
                                </div>
                            )},
                            ...(writable ? [{
                                header: 'Actions', align: 'right' as const,
                                render: (s: SKU) => (
                                    <div className="flex justify-end gap-1">
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            aria-label={`Edit ${s.code}`}
                                            onClick={() => {
                                                setEditing(s);
                                                setFormOpen(true);
                                            }}
                                        >
                                            <Pencil className="h-4 w-4"/>
                                        </Button>
                                        <Button variant="ghost" size="sm" aria-label={`Deactivate ${s.code}`}
                                                onClick={() => setDeleting(s)}>
                                            <Trash2 className="h-4 w-4 text-danger"/>
                                        </Button>
                                    </div>
                                ),
                            }] : []),
                        ]}
                    />
                    <Pagination count={resp?.count ?? 0} page={page} onPageChange={setPage}/>
                </Card>
            )}

            <Modal
                open={formOpen}
                onClose={() => setFormOpen(false)}
                title={editing ? `Edit ${editing.code}` : 'Add Product'}
                size="lg"
            >
                <SKUForm existing={editing} onDone={() => setFormOpen(false)}/>
            </Modal>

            <Modal open={importOpen} onClose={() => setImportOpen(false)} title="Bulk Import Products" size="xl">
                <BulkImport onDone={() => setImportOpen(false)}/>
            </Modal>

            <ConfirmDialog
                open={deleting !== null}
                onClose={() => setDeleting(null)}
                onConfirm={confirmDelete}
                title="Deactivate product"
                message={`Deactivate ${deleting?.code ?? ''} (${deleting?.name ?? ''})? It will be hidden from active lists.`}
                confirmLabel="Deactivate"
                variant="danger"
            />
        </div>
    );
}



function SKUForm({existing, onDone}: { existing: SKU | null; onDone: () => void }) {
    const create = useCreateSKU();
    const update = useUpdateSKU();
    const [serverError, setServerError] = useState<string | null>(null);

    const {
        register,
        handleSubmit,
        formState: {errors},
    } = useForm<SKUFormValues>({
        resolver: zodResolver(skuSchema),
        defaultValues: {
            code: existing?.code ?? '',
            name: existing?.name ?? '',
            brand: existing?.brand ?? '',
            category: existing?.category ?? '',
            sub_category: existing?.sub_category ?? '',
            mrp: existing?.mrp ?? '',
            is_focus: existing?.is_focus ?? false,
            is_npi: existing?.is_npi ?? false,
        },
    });

    const onSubmit = handleSubmit((values) => {
        setServerError(null);
        const payload: SKUPayload = {
            code: values.code.trim(),
            name: values.name.trim(),
            brand: values.brand.trim(),
            category: values.category.trim(),
            sub_category: values.sub_category.trim(),
            mrp: values.mrp.trim() === '' ? null : values.mrp.trim(),
            is_focus: values.is_focus,
            is_npi: values.is_npi,
        };
        const onError = (e: unknown) => setServerError(apiErrorMessage(e, 'Could not save product'));

        if (existing) {
            update.mutate(
                {id: existing.id, payload},
                {
                    onSuccess: () => {
                        notify.success('Product updated');
                        onDone();
                    },
                    onError,
                },
            );
        } else {
            create.mutate(payload, {
                onSuccess: () => {
                    notify.success('Product created');
                    onDone();
                },
                onError,
            });
        }
    });

    const pending = create.isPending || update.isPending;

    return (
        <form onSubmit={onSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <Input label="Code" {...register('code')} error={errors.code?.message} disabled={!!existing}
                       hint={existing ? 'Code cannot be changed.' : undefined}/>
                <Input label="Name" {...register('name')} error={errors.name?.message}/>
                <Input label="Brand" {...register('brand')} />
                <Input label="Category" {...register('category')} />
                <Input label="Sub-category" {...register('sub_category')} />
                <Input label="MRP (₹)" {...register('mrp')} error={errors.mrp?.message} placeholder="e.g. 199.00"/>
            </div>
            <div className="flex gap-6">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                    <input type="checkbox" {...register('is_focus')}
                           className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"/>
                    Focus product
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                    <input type="checkbox" {...register('is_npi')}
                           className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"/>
                    New product introduction (NPI)
                </label>
            </div>

            {serverError && <p className="text-sm text-danger">{serverError}</p>}

            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>
                    Cancel
                </Button>
                <Button type="submit" loading={pending}>
                    {existing ? 'Save changes' : 'Create product'}
                </Button>
            </div>
        </form>
    );
}



const CSV_HEADER = 'code,name,brand,category,sub_category,mrp,is_focus,is_npi';

function BulkImport({onDone}: { onDone: () => void }) {
    const [csvText, setCsvText] = useState('');
    const [fileName, setFileName] = useState('');
    const bulk = useBulkImportSKUs();
    const qc = useQueryClient();
    const [result, setResult] = useState<BulkImportResult | null>(null);
    const [jobId, setJobId] = useState<number | null>(null);

    const preview = useMemo(() => {
        if (!csvText.trim()) return null;
        const lines = csvText.trim().split(/\r?\n/);
        const header = (lines[0] ?? '').split(',').map((h) => h.trim());
        const rows = lines.slice(1, 6).map((l) => l.split(','));
        return {header, rows, total: Math.max(0, lines.length - 1)};
    }, [csvText]);

    function onFile(e: React.ChangeEvent<HTMLInputElement>) {
        const file = e.target.files?.[0];
        if (!file) return;
        setFileName(file.name);
        const reader = new FileReader();
        reader.onload = () => {
            setCsvText(String(reader.result ?? ''));
            setResult(null);
        };
        reader.readAsText(file);
    }

    function confirmImport() {
        setResult(null);
        bulk.mutate({csvText}, {
            onSuccess: (res) => {
                if (res.async) {
                    // Large file → processing in the background; poll the job.
                    setJobId(res.job.id);
                    return;
                }
                setResult(res.result);
                if (res.result.status === 'success') {
                    notify.success(`Imported: ${res.result.created} created, ${res.result.updated} updated`);
                    onDone();
                } else {
                    notify.error('Some rows have errors — nothing was imported.');
                }
            },
            onError: (e) => notify.error(apiErrorMessage(e, 'Import failed')),
        });
    }

    function handleJobDone(job: BulkJob) {
        void qc.invalidateQueries({queryKey: ['master', 'skus']});
        if (job.status === 'completed') {
            const created = (job.result.created as number | undefined) ?? job.success_count;
            const updated = (job.result.updated as number | undefined) ?? 0;
            notify.success(`Imported: ${created} created, ${updated} updated`);
            onDone();
        } else {
            setResult({
                status: 'validation_failed',
                created: 0,
                updated: 0,
                errors: (job.errors ?? []).map((e) => ({row: e.row, error: e.errors.join(', ')})),
            });
            setJobId(null);
        }
    }

    return (
        <div className="space-y-4">
            {jobId !== null && <BulkJobProgress jobId={jobId} onDone={handleJobDone}/>}

            <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
                Upload a CSV with this header row. Products are matched by <strong>code</strong> — existing ones
                are updated, new ones are created. Extra columns become custom attributes. Large files are
                processed in the background.
                <code className="mt-1 block overflow-x-auto rounded bg-white px-2 py-1 text-[11px] text-gray-700">
                    {CSV_HEADER}
                </code>
            </div>

            <label
                className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed border-gray-300 py-6 text-sm text-gray-500 hover:border-primary hover:text-primary">
                <Upload className="h-4 w-4"/>
                {fileName || 'Choose a CSV file…'}
                <input type="file" accept=".csv,text/csv" className="hidden" onChange={onFile}/>
            </label>

            {preview && (
                <div>
                    <p className="mb-1 text-sm font-medium text-gray-700">
                        Preview <span className="font-normal text-gray-400">({preview.total} row(s) total)</span>
                    </p>
                    <div className="overflow-x-auto rounded-lg border border-gray-200">
                        <table className="w-full text-left text-xs">
                            <thead className="bg-gray-50 text-gray-500">
                            <tr>
                                {preview.header.map((h, i) => (
                                    <th key={i} className="px-2 py-1.5 font-medium">{h}</th>
                                ))}
                            </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                            {preview.rows.map((r, i) => (
                                <tr key={i}>
                                    {r.map((c, j) => (
                                        <td key={j} className="px-2 py-1.5 text-gray-700">{c}</td>
                                    ))}
                                </tr>
                            ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {result?.status === 'validation_failed' && (
                <div className="rounded-lg border border-danger-100 bg-danger-50 px-3 py-2 text-xs text-danger">
                    <p className="font-medium">Import blocked — fix these rows and retry:</p>
                    <ul className="mt-1 list-inside list-disc">
                        {result.errors.slice(0, 10).map((err, i) => (
                            <li key={i}>Row {err.row}: {err.error}</li>
                        ))}
                    </ul>
                </div>
            )}

            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>
                    Cancel
                </Button>
                <Button onClick={confirmImport} loading={bulk.isPending}
                        disabled={!csvText.trim() || jobId !== null}>
                    Import
                </Button>
            </div>
        </div>
    );
}
