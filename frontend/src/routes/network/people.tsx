import {useState} from 'react';
import axios from 'axios';
import {Search, Upload, Download, GitBranch, X} from 'lucide-react';
import {notify} from '../../utils/notify';
import {Button} from '../../components/ui/Button';
import {EmptyState} from '../../components/ui/EmptyState';
import {HowThisWorks} from '../../components/ui/HowThisWorks';
import {BlueprintPanel} from '../../components/entity/BlueprintPanel';
import {EntityTree, FlatEntityList, VirtualEntityList} from '../../components/entity/EntityTree';
import {EntityCard} from '../../components/entity/EntityCard';
import {EntityForm} from '../../components/entity/EntityForm';
import {BulkImportDialog} from '../../components/entity/BulkImportDialog';
import {BulkActionBar} from '../../components/entity/BulkActionBar';
import {BulkMoveDialog} from '../../components/entity/BulkMoveDialog';
import {BulkDeactivateDialog} from '../../components/entity/BulkDeactivateDialog';
import {BulkReactivateDialog} from '../../components/entity/BulkReactivateDialog';
import {
    useBlueprint,
    useEntities,
    useEntityCounts,
    useEntitySearch,
    useChannels,
    useGeographyTypes,
} from '../../hooks/useEntities';
import {GeoNodeCombobox, type GeoSelection} from '../../components/entity/GeoNodeCombobox';
import {entityService} from '../../services/entityService';
import {downloadBlob} from '../../utils/download';
import {useHierarchyStore} from '../../stores/hierarchyStore';
import {useRBAC} from '../../hooks/useRBAC';

export default function HierarchyPage() {
    const [activeTypeFilter, setActiveTypeFilter] = useState<string | null>(null);
    const [searchQ, setSearchQ] = useState('');
    const [channelFilter, setChannelFilter] = useState('');
    const [geoSel, setGeoSel] = useState<GeoSelection | null>(null);
    const [showCreateForm, setShowCreateForm] = useState(false);
    const [showBulkImport, setShowBulkImport] = useState(false);
    const [exporting, setExporting] = useState(false);
    const [bulkAction, setBulkAction] = useState<'transfer' | 'deactivate' | 'reactivate' | null>(null);

    const {data: channelsResp} = useChannels();
    const channels = channelsResp?.results ?? [];
    const {data: geoTypesResp} = useGeographyTypes();
    const geoTypeCode = geoTypesResp?.results?.[0]?.code ?? '';
    const geoFilter = geoSel?.code ?? '';

    const colFilters = {
        ...(activeTypeFilter ? {type: activeTypeFilter} : {}),
        ...(channelFilter ? {channel: channelFilter} : {}),
        ...(geoFilter ? {geography: geoFilter} : {}),
    };
    const hasColFilter = channelFilter !== '' || geoFilter !== '';

    async function handleExport() {
        setExporting(true);
        try {
            const blob = await entityService.export(colFilters);
            downloadBlob(blob, 'entities.csv');
        } catch (err) {
            // A timed-out export is a size problem, not a failure — say so, because
            // the generic message sent people looking for a broken endpoint.
            notify.error(
                axios.isAxiosError(err) && err.code === 'ECONNABORTED'
                    ? 'Export timed out. Narrow the list with the type or channel filter and try again.'
                    : 'Could not export entities.',
            );
        } finally {
            setExporting(false);
        }
    }

    const {canWrite} = useRBAC();
    const writable = canWrite('hierarchy_management');

    const {selectedId, selectedIds, selectedStatuses, clearChecked} = useHierarchyStore();
    const checkedIds = Array.from(selectedIds);
    const activeIds = checkedIds.filter((id) => selectedStatuses[id] === 'active');
    const inactiveIds = checkedIds.filter((id) => selectedStatuses[id] && selectedStatuses[id] !== 'active');
    const {data: blueprint = []} = useBlueprint();

    // Counts come from a server-side aggregation; the tree loads roots only and
    // lazy-loads children. Neither pulls the full entity table.
    const {data: countsData} = useEntityCounts();
    const counts = countsData?.counts ?? {};
    const totalCount = countsData?.total ?? 0;

    const {data: rootEntities, isLoading: entitiesLoading} = useEntities({root: true, page_size: 200});
    const rootItems = rootEntities?.results ?? [];
    // Roots are top-of-org people; >200 means the tree is misconfigured, but never truncate silently.
    const rootsTruncated = (rootEntities?.count ?? 0) > 200;

    // Rows render through the virtualized infinite list; this 1-row query only
    // supplies the true server-side match count for the filter summary.
    const {data: filteredCount} = useEntities({page_size: 1, ...colFilters});

    const isSearchMode = searchQ.trim().length > 0;
    const {data: searchResults, isLoading: searchLoading} = useEntitySearch(
        searchQ,
        activeTypeFilter ?? undefined,
    );

    // Active-filter summary. Only show chips for filters that affect the current
    // view: search ignores channel/area, so those chips hide while searching.
    const typeLabel = activeTypeFilter
        ? (blueprint.find((t) => t.code === activeTypeFilter)?.name ?? activeTypeFilter)
        : null;
    const channelLabel = channelFilter
        ? (channels.find((c) => c.code === channelFilter)?.name ?? channelFilter)
        : null;
    const geoLabel = geoSel?.name ?? null;

    const showTypeChip = typeLabel !== null;
    const showChannelChip = !isSearchMode && channelLabel !== null;
    const showGeoChip = !isSearchMode && geoLabel !== null;
    const anyFilter = showTypeChip || showChannelChip || showGeoChip || isSearchMode;

    const shownCount = isSearchMode
        ? (searchResults?.length ?? 0)
        : hasColFilter
            ? (filteredCount?.count ?? 0)
            : activeTypeFilter
                ? (counts[activeTypeFilter] ?? 0)
                : totalCount;

    function clearAllFilters() {
        setActiveTypeFilter(null);
        setChannelFilter('');
        setGeoSel(null);
        setSearchQ('');
    }

    return (

        <div className="flex h-full flex-col overflow-hidden">

            <div className="shrink-0 space-y-2 border-b border-gray-200 bg-white px-4 py-3">
                <div>
                    <p className="text-xs text-gray-500">
                        Everyone you work with — your team, distributors and retailers — and who reports to whom.
                    </p>
                </div>
                <HowThisWorks storageKey="hierarchy-help">
                    This is everyone in your network. Browse the reporting lines on the left, or search for
                    someone by name. Click any name to see their profile, their team, and the territories they
                    look after. Looking for the <em>places</em> instead of the people? Head to{' '}
                    <strong>Territories</strong>. Want to set who's in charge of a place? That's{' '}
                    <strong>Territory Owners</strong>.
                </HowThisWorks>
            </div>

            <div className="flex flex-1 overflow-hidden">

            <div className="flex w-2/5 min-w-56 flex-col overflow-hidden border-r border-gray-200 bg-white">

                <BlueprintPanel
                    blueprint={blueprint}
                    counts={counts}
                    total={totalCount}
                    activeType={activeTypeFilter}
                    onTypeSelect={setActiveTypeFilter}
                />


                <div className="flex items-center gap-2 border-b border-gray-100 px-3 py-2">
                    <div className="relative flex-1">
                        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400"/>
                        <input
                            type="text"
                            placeholder="Search by name…"
                            value={searchQ}
                            onChange={(e) => setSearchQ(e.target.value)}
                            className="w-full rounded-lg border border-gray-200 bg-gray-50 py-1.5 pl-8 pr-3 text-sm
                         focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                        />
                    </div>
                    <button
                        type="button"
                        title="Export entities (CSV)"
                        aria-label="Export entities (CSV)"
                        onClick={handleExport}
                        disabled={exporting}
                        className="rounded-lg border border-gray-200 p-1.5 text-gray-500 hover:border-primary hover:text-primary transition-colors disabled:opacity-50"
                    >
                        <Download className="h-4 w-4"/>
                    </button>
                    {writable && (
                        <button
                            type="button"
                            title="Bulk Import"
                            onClick={() => setShowBulkImport(true)}
                            className="rounded-lg border border-gray-200 p-1.5 text-gray-500 hover:border-primary hover:text-primary transition-colors"
                        >
                            <Upload className="h-4 w-4"/>
                        </button>
                    )}
                    {writable && (
                        <Button size="sm" title="Create Entity" onClick={() => setShowCreateForm(true)}>
                            + New
                        </Button>
                    )}
                </div>

                {isSearchMode ? (
                    <p className="border-b border-gray-100 bg-gray-50/60 px-3 py-2 text-xs text-gray-500">
                        We've paused the channel &amp; territory filters while you search.
                    </p>
                ) : (
                    <div className="flex items-center gap-2 border-b border-gray-100 px-3 py-2">
                        <select
                            value={channelFilter}
                            onChange={(e) => setChannelFilter(e.target.value)}
                            className="flex-1 rounded-lg border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs
                             focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                        >
                            <option value="">All channels</option>
                            {channels.map((c) => (
                                <option key={c.id} value={c.code}>{c.name}</option>
                            ))}
                        </select>
                        <div className="flex-1">
                            <GeoNodeCombobox
                                typeCode={geoTypeCode}
                                value={geoSel}
                                onChange={setGeoSel}
                                placeholder="All territories"
                            />
                        </div>
                    </div>
                )}

                {anyFilter && (
                    <div className="flex flex-wrap items-center gap-1.5 border-b border-gray-100 bg-gray-50/60 px-3 py-2 text-xs">
                        <span className="font-medium text-gray-600">{shownCount} shown</span>
                        <span className="text-gray-300">·</span>
                        {showTypeChip && <FilterChip label={`Type: ${typeLabel}`} onRemove={() => setActiveTypeFilter(null)}/>}
                        {showChannelChip && <FilterChip label={`Channel: ${channelLabel}`} onRemove={() => setChannelFilter('')}/>}
                        {showGeoChip && <FilterChip label={`Territory: ${geoLabel}`} onRemove={() => setGeoSel(null)}/>}
                        {isSearchMode && <FilterChip label={`Search: “${searchQ.trim()}”`} onRemove={() => setSearchQ('')}/>}
                        <button
                            type="button"
                            onClick={clearAllFilters}
                            className="ml-auto text-gray-400 hover:text-gray-600"
                        >
                            Clear all
                        </button>
                    </div>
                )}

                {!isSearchMode && !hasColFilter && !activeTypeFilter && rootsTruncated && (
                    <p className="border-b border-warning/20 bg-warning-50 px-3 py-1.5 text-xs text-warning">
                        Showing the first 200 top-level people — use search or the type filters to find the rest.
                    </p>
                )}
                <div className="flex-1 overflow-y-auto">
                    {isSearchMode ? (
                        <FlatEntityList items={searchResults ?? []} isLoading={searchLoading}/>
                    ) : hasColFilter || activeTypeFilter ? (
                        // Channel/territory/type filters can match 150k retailers —
                        // always the virtualized infinite path, never a capped flat list.
                        <VirtualEntityList params={{...colFilters, page_size: 50}}/>
                    ) : (
                        <EntityTree items={rootItems} blueprint={blueprint} isLoading={entitiesLoading}/>
                    )}
                </div>


                {writable && (
                    <BulkActionBar
                        count={checkedIds.length}
                        activeCount={activeIds.length}
                        inactiveCount={inactiveIds.length}
                        onMove={() => setBulkAction('transfer')}
                        onDeactivate={() => setBulkAction('deactivate')}
                        onReactivate={() => setBulkAction('reactivate')}
                        onClear={clearChecked}
                    />
                )}
            </div>


            <div className="flex-1 overflow-y-auto bg-gray-50">
                {selectedId !== null ? (
                    <EntityCard entityId={selectedId}/>
                ) : (
                    <div className="flex h-full items-center justify-center">
                        <EmptyState
                            icon={GitBranch}
                            title="Pick someone to see their details"
                            description="Click any name on the left and you'll see their profile, their team, the territories they look after, and their connections."
                        />
                    </div>
                )}
            </div>
            </div>


            {showCreateForm && <EntityForm onClose={() => setShowCreateForm(false)}/>}
            {showBulkImport && <BulkImportDialog onClose={() => setShowBulkImport(false)}/>}
            {bulkAction === 'transfer' && (
                <BulkMoveDialog
                    ids={checkedIds}
                    onClose={() => setBulkAction(null)}
                    onDone={clearChecked}
                />
            )}
            {bulkAction === 'deactivate' && (
                <BulkDeactivateDialog
                    ids={activeIds}
                    onClose={() => setBulkAction(null)}
                    onDone={clearChecked}
                />
            )}
            {bulkAction === 'reactivate' && (
                <BulkReactivateDialog
                    ids={inactiveIds}
                    onClose={() => setBulkAction(null)}
                    onDone={clearChecked}
                />
            )}
        </div>
    );
}


function FilterChip({label, onRemove}: { label: string; onRemove: () => void }) {
    return (
        <span className="inline-flex items-center gap-1 rounded-full bg-primary-50 px-2 py-0.5 text-primary">
            {label}
            <button
                type="button"
                onClick={onRemove}
                className="rounded-full hover:text-primary-dark"
                aria-label={`Remove filter: ${label}`}
            >
                <X className="h-3 w-3"/>
            </button>
        </span>
    );
}
