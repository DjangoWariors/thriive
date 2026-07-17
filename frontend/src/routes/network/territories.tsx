import {useMemo, useState} from 'react';
import type React from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {Plus, Pencil, Trash2, Move, MapPin, Globe, Settings2, Upload, X} from 'lucide-react';
import {
    useGeographyTypes,
    useGeographyTree,
    useCreateGeoType,
    useCreateGeoNode,
    useUpdateGeoNode,
    useMoveGeoNode,
    useDeactivateGeoNode,
} from '../../hooks/useEntities';
import {GeoNodeCombobox, type GeoSelection} from '../../components/entity/GeoNodeCombobox';
import {useRBAC} from '../../hooks/useRBAC';
import type {
    GeographyNode,
    GeographyType,
    CreateGeographyNodePayload,
} from '../../types/entity';
import {GeographyTree} from '../../components/geography/GeographyTree';
import {ScopeOwnershipCard} from '../../components/assignments/ScopeOwnershipCard';
import {BulkJobProgress} from '../../components/jobs/BulkJobProgress';
import {entityService} from '../../services/entityService';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import {Card} from '../../components/ui/Card';
import {Badge} from '../../components/ui/Badge';
import {Modal} from '../../components/ui/Modal';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {EmptyState} from '../../components/ui/EmptyState';
import {HowThisWorks} from '../../components/ui/HowThisWorks';
import {ConfirmDialog} from '../../components/ui/ConfirmDialog';
import {PageHeader} from '../../components/ui/PageHeader';
import {notify} from '../../utils/notify';
import {apiErrorMessage} from '../../utils/apiError';


function slugify(value: string): string {
    return value.toUpperCase().trim().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}


export default function GeographyPage() {
    const {canWrite} = useRBAC();
    const writable = canWrite('hierarchy_management');

    const {data: typesResp, isLoading: typesLoading} = useGeographyTypes();
    const types = typesResp?.results ?? [];

    const [typeCode, setTypeCode] = useState<string>('');
    const activeType = useMemo<GeographyType | undefined>(
        () => types.find((t) => t.code === typeCode) ?? types[0],
        [types, typeCode],
    );
    const effectiveCode = activeType?.code ?? '';

    const {data: roots = [], isLoading: treeLoading} = useGeographyTree(effectiveCode);

    const [selected, setSelected] = useState<GeographyNode | null>(null);
    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<GeographyNode | null>(null);
    const [moving, setMoving] = useState<GeographyNode | null>(null);
    const [deleting, setDeleting] = useState<GeographyNode | null>(null);
    const [typeFormOpen, setTypeFormOpen] = useState(false);
    const [importOpen, setImportOpen] = useState(false);

    const deactivate = useDeactivateGeoNode();

    const confirmDelete = () => {
        if (!deleting) return;
        deactivate.mutate(deleting.id, {
            onSuccess: () => {
                notify.success(`${deleting.name} deactivated`);
                if (selected?.id === deleting.id) setSelected(null);
                setDeleting(null);
            },
            onError: (e) => {
                notify.error(apiErrorMessage(e, 'Could not deactivate node'));
                setDeleting(null);
            },
        });
    };

    if (typesLoading) {
        return <div className="p-6"><TableSkeleton/></div>;
    }

    if (types.length === 0) {
        return (
            <div className="p-6">
                <PageHeader
                    title="Territories"
                    description="The places you sell into — your regions, districts and towns."
                    actions={<>{writable && (
                        <Button icon={<Plus className="h-4 w-4"/>} onClick={() => setTypeFormOpen(true)}>
                            New territory set
                        </Button>
                    )}</>}
                />
                <Card>
                    <EmptyState
                        icon={Globe}
                        title="No territories yet"
                        description="Set up a territory set (something like “Sales Geography”) and its levels, and you'll be ready to start mapping out your territories."
                    />
                </Card>
                <Modal open={typeFormOpen} onClose={() => setTypeFormOpen(false)} title="New territory set" size="md">
                    <GeographyTypeForm onDone={(t) => {
                        setTypeFormOpen(false);
                        if (t) setTypeCode(t.code);
                    }}/>
                </Modal>
            </div>
        );
    }

    return (
        <div className="flex h-full flex-col p-6">
            <PageHeader
                className="mb-4"
                title="Territories"
                description="The places you sell into. Sales, targets and reports all add up by territory."
                actions={
                    <div className="flex items-end gap-2">
                        <div className="w-52">
                            <Select
                                label="Territory set"
                                value={effectiveCode}
                                onChange={(e) => {
                                    setTypeCode(e.target.value);
                                    setSelected(null);
                                }}
                                options={types.map((t) => ({value: t.code, label: t.name}))}
                            />
                        </div>
                        {writable && (
                            <Button variant="outline" icon={<Settings2 className="h-4 w-4"/>} onClick={() => setTypeFormOpen(true)}>
                                New territory set
                            </Button>
                        )}
                    </div>
                }
            />

            {activeType && (
                <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
                    <span>Levels:</span>
                    {activeType.levels.map((lvl, i) => (
                        <span key={lvl} className="flex items-center gap-1.5">
                            <Badge variant="info">{lvl}</Badge>
                            {i < activeType.levels.length - 1 && <span className="text-gray-300">→</span>}
                        </span>
                    ))}
                </div>
            )}

            <HowThisWorks storageKey="geography-help" className="mb-3">
                Territories are simply the places you sell into — kept separate from the people who cover
                them. Build the levels that suit your business (say Region → District → Town). You won't add
                people here; pick a territory and its <strong>Ownership</strong> card shows who looks after
                it — assign or transfer right there. That's the trick that lets someone move on without
                taking the territory or its sales with them.
            </HowThisWorks>

            <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-5 lg:grid-rows-[minmax(0,1fr)]">
                {/* Tree */}
                <Card className="lg:col-span-2 min-h-0 overflow-y-auto" padding="none">
                    <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-100 bg-white px-4 py-2.5">
                        <h2 className="text-sm font-semibold text-gray-700">Territory tree</h2>
                        {writable && (
                            <div className="flex gap-2">
                                <Button
                                    size="sm"
                                    variant="outline"
                                    icon={<Upload className="h-4 w-4"/>}
                                    onClick={() => setImportOpen(true)}
                                >
                                    Import
                                </Button>
                                <Button
                                    size="sm"
                                    icon={<Plus className="h-4 w-4"/>}
                                    onClick={() => {
                                        setEditing(null);
                                        setFormOpen(true);
                                    }}
                                >
                                    Add node
                                </Button>
                            </div>
                        )}
                    </div>
                    <div className="px-2 pb-2">
                        <GeographyTree
                            roots={roots}
                            isLoading={treeLoading}
                            selectedId={selected?.id ?? null}
                            onSelect={setSelected}
                        />
                    </div>
                </Card>

                {/* Detail */}
                <Card className="lg:col-span-3 min-h-0 overflow-y-auto">
                    {selected ? (
                        <GeographyNodePanel
                            node={selected}
                            writable={writable}
                            onEdit={() => {
                                setEditing(selected);
                                setFormOpen(true);
                            }}
                            onMove={() => setMoving(selected)}
                            onDeactivate={() => setDeleting(selected)}
                        />
                    ) : (
                        <EmptyState
                            icon={MapPin}
                            title="Select a node"
                            description="Pick a territory on the left to see its details and actions."
                        />
                    )}
                </Card>
            </div>

            {activeType && (
                <Modal
                    open={formOpen}
                    onClose={() => setFormOpen(false)}
                    title={editing ? `Edit ${editing.name}` : 'Add a territory'}
                    size="md"
                >
                    <GeographyNodeForm
                        geoType={activeType}
                        existing={editing}
                        defaultParent={!editing ? selected : null}
                        onDone={() => setFormOpen(false)}
                    />
                </Modal>
            )}

            {activeType && moving && (
                <MoveNodeDialog
                    geoType={activeType}
                    node={moving}
                    onClose={() => setMoving(null)}
                />
            )}

            <Modal open={typeFormOpen} onClose={() => setTypeFormOpen(false)} title="New territory set" size="md">
                <GeographyTypeForm onDone={(t) => {
                    setTypeFormOpen(false);
                    if (t) setTypeCode(t.code);
                }}/>
            </Modal>

            <Modal open={importOpen} onClose={() => setImportOpen(false)} title="Import territories" size="xl">
                <GeographyImport geoTypeCode={effectiveCode} onClose={() => setImportOpen(false)}/>
            </Modal>

            <ConfirmDialog
                open={deleting !== null}
                onClose={() => setDeleting(null)}
                onConfirm={confirmDelete}
                title="Deactivate node"
                message={`Deactivate ${deleting?.name ?? ''}? Nodes with child nodes or assigned entities cannot be removed.`}
                confirmLabel="Deactivate"
                variant="danger"
            />
        </div>
    );
}


function GeographyNodePanel({
    node,
    writable,
    onEdit,
    onMove,
    onDeactivate,
}: {
    node: GeographyNode;
    writable: boolean;
    onEdit: () => void;
    onMove: () => void;
    onDeactivate: () => void;
}) {
    return (
        <div className="space-y-5">
            <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                    <MapPin className="h-5 w-5 text-primary"/>
                    <div>
                        <h2 className="text-lg font-semibold text-gray-900">{node.name}</h2>
                        <code className="text-xs text-gray-500">{node.code}</code>
                    </div>
                </div>
                <Badge variant="info">{node.level}</Badge>
            </div>

            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                <div>
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Territory set</dt>
                    <dd className="text-gray-900">{node.geography_type.name}</dd>
                </div>
                <div>
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Reports to</dt>
                    <dd className="text-gray-900">{node.parent_name ?? '— (top level)'}</dd>
                </div>
                <div>
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Child nodes</dt>
                    <dd className="text-gray-900">{node.children_count}</dd>
                </div>
                <div>
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Depth</dt>
                    <dd className="text-gray-900">{node.depth}</dd>
                </div>
                <div className="col-span-2">
                    <dt className="text-xs uppercase tracking-wide text-gray-400">Path</dt>
                    <dd className="font-mono text-xs text-gray-600">{node.path}</dd>
                </div>
            </dl>

            <ScopeOwnershipCard
                scope={{id: node.id, name: node.name, code: node.code, level: node.level}}
                geoTypeCode={node.geography_type.code}
            />

            {writable && (
                <div className="flex gap-2 border-t border-gray-100 pt-4">
                    <Button variant="outline" size="sm" icon={<Pencil className="h-4 w-4"/>} onClick={onEdit}>
                        Edit
                    </Button>
                    <Button variant="outline" size="sm" icon={<Move className="h-4 w-4"/>} onClick={onMove}>
                        Move
                    </Button>
                    <Button variant="outline" size="sm" icon={<Trash2 className="h-4 w-4 text-danger"/>} onClick={onDeactivate}>
                        Deactivate
                    </Button>
                </div>
            )}
        </div>
    );
}


function GeographyNodeForm({
    geoType,
    existing,
    defaultParent,
    onDone,
}: {
    geoType: GeographyType;
    existing: GeographyNode | null;
    defaultParent: GeographyNode | null;
    onDone: () => void;
}) {
    const create = useCreateGeoNode();
    const update = useUpdateGeoNode();

    const [name, setName] = useState(existing?.name ?? '');
    const [code, setCode] = useState(existing?.code ?? '');
    const [codeEdited, setCodeEdited] = useState(existing !== null);
    const [level, setLevel] = useState(
        existing?.level ?? (defaultParent ? nextLevel(geoType, defaultParent.level) : geoType.levels[0] ?? ''),
    );
    const [parent, setParent] = useState<GeoSelection | null>(
        defaultParent && !existing
            ? {id: defaultParent.id, name: defaultParent.name, level: defaultParent.level, code: defaultParent.code}
            : null,
    );
    const [error, setError] = useState<string | null>(null);

    // Candidate parents are searched server-side, constrained to levels shallower
    // than the chosen child level — never a load-everything <select>.
    const levelIndex = geoType.levels.indexOf(level);
    const parentLevels = levelIndex > 0 ? geoType.levels.slice(0, levelIndex) : [];

    function handleName(v: string) {
        setName(v);
        if (!codeEdited) setCode(slugify(v));
    }

    function submit() {
        setError(null);
        if (!name.trim() || !code.trim() || !level) {
            setError('Name, code and level are required.');
            return;
        }
        const onError = (e: unknown) => setError(apiErrorMessage(e, 'Could not save node'));

        if (existing) {
            update.mutate(
                {id: existing.id, payload: {name: name.trim(), level}},
                {
                    onSuccess: () => {
                        notify.success('Node updated');
                        onDone();
                    },
                    onError,
                },
            );
        } else {
            const payload: CreateGeographyNodePayload = {
                geography_type_id: geoType.id,
                name: name.trim(),
                code: code.trim(),
                level,
                parent: parent?.id ?? null,
            };
            create.mutate(payload, {
                onSuccess: () => {
                    notify.success('Node created');
                    onDone();
                },
                onError,
            });
        }
    }

    const pending = create.isPending || update.isPending;

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <Input label="Name" value={name} onChange={(e) => handleName(e.target.value)} placeholder="e.g. New Delhi"/>
                <Input
                    label="Code"
                    value={code}
                    disabled={!!existing}
                    onChange={(e) => {
                        setCodeEdited(true);
                        setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ''));
                    }}
                    hint={existing ? 'Code cannot be changed.' : undefined}
                />
            </div>

            <Select
                label="Level"
                value={level}
                onChange={(e) => setLevel(e.target.value)}
                options={geoType.levels.map((l) => ({value: l, label: l}))}
            />

            {!existing && (
                <div>
                    {levelIndex <= 0 ? (
                        <p className="text-xs text-gray-400">Top-level nodes have no parent.</p>
                    ) : (
                        <GeoNodeCombobox
                            typeCode={geoType.code}
                            label="Parent"
                            placeholder="Search a parent territory (leave empty for top level)…"
                            value={parent}
                            onChange={setParent}
                            levels={parentLevels}
                        />
                    )}
                </div>
            )}

            {error && <p className="text-sm text-danger">{error}</p>}

            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
                <Button onClick={submit} loading={pending}>
                    {existing ? 'Save changes' : 'Create node'}
                </Button>
            </div>
        </div>
    );
}


function MoveNodeDialog({
    geoType,
    node,
    onClose,
}: {
    geoType: GeographyType;
    node: GeographyNode;
    onClose: () => void;
}) {
    const move = useMoveGeoNode();
    const [newParent, setNewParent] = useState<GeoSelection | null>(null);
    const [toTopLevel, setToTopLevel] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Valid new parents: shallower level, not self, not a descendant — searched
    // server-side, never a load-everything <select>.
    const levelIndex = geoType.levels.indexOf(node.level);
    const parentLevels = levelIndex > 0 ? geoType.levels.slice(0, levelIndex) : [];
    const canSubmit = toTopLevel || newParent !== null;

    function submit() {
        setError(null);
        move.mutate(
            {id: node.id, newParentId: toTopLevel ? null : (newParent?.id ?? null)},
            {
                onSuccess: () => {
                    notify.success(`${node.name} moved`);
                    onClose();
                },
                onError: (e) => setError(apiErrorMessage(e, 'Could not move node')),
            },
        );
    }

    return (
        <Modal open onClose={onClose} title={`Move ${node.name}`} size="md">
            <div className="space-y-4">
                <div className="rounded-lg bg-warning-50 px-3 py-2 text-xs text-warning">
                    Heads up: moving this takes everything underneath it along for the ride
                    {node.children_count > 0 ? ` (that's ${node.children_count} place${node.children_count === 1 ? '' : 's'} sitting directly below)` : ''}.
                    We'll redo the paths and keep a record of the change.
                </div>
                {!toTopLevel && (
                    <GeoNodeCombobox
                        typeCode={geoType.code}
                        label="New parent"
                        value={newParent}
                        onChange={setNewParent}
                        levels={parentLevels}
                        excludePathPrefix={node.path}
                    />
                )}
                <label className="flex items-center gap-2 text-sm text-gray-600">
                    <input type="checkbox" checked={toTopLevel}
                           onChange={(e) => setToTopLevel(e.target.checked)}/>
                    Make it a top-level node (no parent)
                </label>
                {error && <p className="text-sm text-danger">{error}</p>}
                <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                    <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
                    <Button onClick={submit} loading={move.isPending} disabled={!canSubmit}>Move node</Button>
                </div>
            </div>
        </Modal>
    );
}


const GEO_CSV_HEADER = 'geography_type_code,name,code,parent_code,level,attributes_json';

function GeographyImport({geoTypeCode, onClose}: {geoTypeCode: string; onClose: () => void}) {
    const qc = useQueryClient();
    const [csvText, setCsvText] = useState('');
    const [fileName, setFileName] = useState('');
    const [jobId, setJobId] = useState<number | null>(null);
    const [submitting, setSubmitting] = useState(false);

    function onFile(e: React.ChangeEvent<HTMLInputElement>) {
        const file = e.target.files?.[0];
        if (!file) return;
        setFileName(file.name);
        const reader = new FileReader();
        reader.onload = () => setCsvText(String(reader.result ?? ''));
        reader.readAsText(file);
    }

    async function confirmImport() {
        setSubmitting(true);
        try {
            const job = await entityService.bulkImportGeoNodes(csvText);
            setJobId(job.id);
        } catch (e) {
            notify.error(apiErrorMessage(e, 'We couldn’t start the import. Please check the file and try again.'));
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <div className="space-y-4">
            <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
                Upload a spreadsheet (CSV) with these columns. <code>parent_code</code> may point at an
                existing territory <em>or another row in the same file</em>, so a whole branch — towns,
                beats and hundreds of outlets — imports in one go. All-or-nothing: any bad row cancels
                the whole file. Your current territory set code is{' '}
                <code className="rounded bg-white px-1">{geoTypeCode || '—'}</code>.
                <code className="mt-1 block overflow-x-auto rounded bg-white px-2 py-1 text-[11px] text-gray-700">{GEO_CSV_HEADER}</code>
            </div>

            {jobId === null ? (
                <>
                    <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed border-gray-300 py-6 text-sm text-gray-500 hover:border-primary hover:text-primary">
                        <Upload className="h-4 w-4"/>
                        {fileName || 'Choose a file from your computer…'}
                        <input type="file" accept=".csv,text/csv" className="hidden" onChange={onFile}/>
                    </label>
                    <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
                        <Button onClick={confirmImport} loading={submitting} disabled={!csvText.trim()}>Import</Button>
                    </div>
                </>
            ) : (
                <>
                    <BulkJobProgress jobId={jobId} onDone={() => void qc.invalidateQueries({queryKey: ['geography-nodes']})}/>
                    <div className="flex justify-end border-t border-gray-100 pt-4">
                        <Button onClick={onClose}>Done</Button>
                    </div>
                </>
            )}
        </div>
    );
}


function GeographyTypeForm({onDone}: {onDone: (created?: GeographyType) => void}) {
    const create = useCreateGeoType();
    const [name, setName] = useState('');
    const [code, setCode] = useState('');
    const [codeEdited, setCodeEdited] = useState(false);
    const [levels, setLevels] = useState<string[]>(['country','region', 'state', 'district', 'town','outlet']);
    const [newLevel, setNewLevel] = useState('');
    const [error, setError] = useState<string | null>(null);

    function handleName(v: string) {
        setName(v);
        if (!codeEdited) setCode(v.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, ''));
    }

    function addLevel() {
        const l = newLevel.trim().toLowerCase();
        if (l && !levels.includes(l)) setLevels((prev) => [...prev, l]);
        setNewLevel('');
    }

    function submit() {
        setError(null);
        if (!name.trim() || !code.trim() || levels.length === 0) {
            setError('Name, code and at least one level are required.');
            return;
        }
        create.mutate(
            {name: name.trim(), code: code.trim(), levels},
            {
                onSuccess: (t) => {
                    notify.success('Territory set created');
                    onDone(t);
                },
                onError: (e) => setError(apiErrorMessage(e, "Sorry, we couldn't create that territory set")),
            },
        );
    }

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <Input label="Name" value={name} onChange={(e) => handleName(e.target.value)} placeholder="e.g. Sales Geography"/>
                <Input
                    label="Code"
                    value={code}
                    onChange={(e) => {
                        setCodeEdited(true);
                        setCode(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''));
                    }}
                />
            </div>

            <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Levels (top → bottom)</label>
                <p className="mb-2 text-xs text-gray-500">
                    These are just to get you going — rename them, drop them, or add your own to match how
                    you work (Zone, Territory, Outlet, whatever fits).
                </p>
                <div className="mb-2 flex flex-wrap gap-1.5">
                    {levels.map((l, i) => (
                        <span key={l} className="inline-flex items-center gap-1 rounded-full bg-primary-50 px-2 py-0.5 text-xs text-primary">
                            <span className="text-gray-500">{i + 1}.</span> {l}
                            <button
                                type="button"
                                onClick={() => setLevels((prev) => prev.filter((x) => x !== l))}
                                className="text-primary/60 hover:text-primary"
                                aria-label={`Remove ${l}`}
                            >
                                <X className="h-3 w-3"/>
                            </button>
                        </span>
                    ))}
                    {levels.length === 0 && <span className="text-xs text-gray-400">No levels yet.</span>}
                </div>
                <div className="flex gap-2">
                    <Input
                        value={newLevel}
                        onChange={(e) => setNewLevel(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                e.preventDefault();
                                addLevel();
                            }
                        }}
                        placeholder="Add a level, e.g. beat"
                    />
                    <Button type="button" variant="outline" onClick={addLevel}>Add</Button>
                </div>
            </div>

            {error && <p className="text-sm text-danger">{error}</p>}

            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
                <Button type="button" variant="outline" onClick={() => onDone()}>Cancel</Button>
                <Button onClick={submit} loading={create.isPending}>Create territory set</Button>
            </div>
        </div>
    );
}


function nextLevel(geoType: GeographyType, parentLevel?: string): string {
    if (!parentLevel) return geoType.levels[0] ?? '';
    const idx = geoType.levels.indexOf(parentLevel);
    return geoType.levels[idx + 1] ?? geoType.levels[geoType.levels.length - 1] ?? '';
}
