import {useState} from 'react';
import {
    type ColumnDef,
    flexRender,
    getCoreRowModel,
    getFilteredRowModel,
    getPaginationRowModel,
    getSortedRowModel,
    type SortingState,
    useReactTable,
} from '@tanstack/react-table';
import {ChevronDown, ChevronUp, ChevronsUpDown, Search} from 'lucide-react';
import {Skeleton} from '../ui/Skeleton';
import {EmptyState} from '../ui/EmptyState';

interface DataTableProps<T> {
    columns: ColumnDef<T, unknown>[];
    data: T[];
    isLoading?: boolean;
    searchPlaceholder?: string;
    /** Hide the built-in client-side search box — use when the caller owns filtering
     * (e.g. server-side filters), so the always-on search doesn't confuse or mislead
     * by only matching the currently-loaded page. */
    hideSearch?: boolean;
    emptyTitle?: string;
    emptyDescription?: string;
    pageSize?: number;
}

export function DataTable<T>({
    columns,
    data,
    isLoading = false,
    searchPlaceholder = 'Search…',
    hideSearch = false,
    emptyTitle = 'No records',
    emptyDescription,
    pageSize = 20,
}: DataTableProps<T>) {
    const [sorting, setSorting] = useState<SortingState>([]);
    const [globalFilter, setGlobalFilter] = useState('');

    const table = useReactTable({
        data,
        columns,
        state: {sorting, globalFilter},
        onSortingChange: setSorting,
        onGlobalFilterChange: setGlobalFilter,
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: getSortedRowModel(),
        getFilteredRowModel: getFilteredRowModel(),
        getPaginationRowModel: getPaginationRowModel(),
        initialState: {pagination: {pageSize}},
    });

    if (isLoading) {
        return (
            <div className="space-y-3">
                <Skeleton width={240} height={34} variant="rect"/>
                <div className="overflow-hidden rounded-lg border border-gray-200">
                    <div className="border-b border-gray-200 bg-gray-50 px-4 py-3">
                        <Skeleton width={120} height={12}/>
                    </div>
                    <div className="divide-y divide-gray-100">
                        {Array.from({length: 6}).map((_, i) => (
                            <div key={i} className="flex items-center gap-4 px-4 py-3">
                                {columns.map((_, c) => (
                                    <Skeleton key={c} height={14} className="flex-1"/>
                                ))}
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    const rows = table.getRowModel().rows;

    return (
        <div className="space-y-3">
            {!hideSearch && (
                <div className="relative max-w-xs">
                    <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400"/>
                    <input
                        type="text"
                        placeholder={searchPlaceholder}
                        value={globalFilter}
                        onChange={(e) => setGlobalFilter(e.target.value)}
                        className="w-full rounded-lg border border-gray-200 bg-gray-50 py-1.5 pl-8 pr-3 text-sm
                         focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                    />
                </div>
            )}

            {rows.length === 0 ? (
                <EmptyState title={emptyTitle} description={emptyDescription}/>
            ) : (
                <>
                    <div className="overflow-x-auto rounded-lg border border-gray-200">
                        <table className="w-full text-left text-sm">
                            <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500">
                            {table.getHeaderGroups().map((hg) => (
                                <tr key={hg.id}>
                                    {hg.headers.map((header) => {
                                        const canSort = header.column.getCanSort();
                                        const sorted = header.column.getIsSorted();
                                        return (
                                            <th key={header.id} className="px-4 py-3">
                                                {header.isPlaceholder ? null : canSort ? (
                                                    <button
                                                        type="button"
                                                        onClick={header.column.getToggleSortingHandler()}
                                                        className="inline-flex items-center gap-1 hover:text-gray-700"
                                                    >
                                                        {flexRender(header.column.columnDef.header, header.getContext())}
                                                        {sorted === 'asc' ? (
                                                            <ChevronUp className="h-3 w-3"/>
                                                        ) : sorted === 'desc' ? (
                                                            <ChevronDown className="h-3 w-3"/>
                                                        ) : (
                                                            <ChevronsUpDown className="h-3 w-3 text-gray-300"/>
                                                        )}
                                                    </button>
                                                ) : (
                                                    flexRender(header.column.columnDef.header, header.getContext())
                                                )}
                                            </th>
                                        );
                                    })}
                                </tr>
                            ))}
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                            {rows.map((row) => (
                                <tr key={row.id} className="hover:bg-gray-50">
                                    {row.getVisibleCells().map((cell) => (
                                        <td key={cell.id} className="px-4 py-3 text-gray-700">
                                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                            </tbody>
                        </table>
                    </div>

                    {table.getPageCount() > 1 && (
                        <div className="flex items-center justify-between text-sm text-gray-500">
                            <span>
                                Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
                                {' · '}{rows.length} of {table.getFilteredRowModel().rows.length} shown
                            </span>
                            <div className="flex items-center gap-2">
                                <button
                                    type="button"
                                    onClick={() => table.previousPage()}
                                    disabled={!table.getCanPreviousPage()}
                                    className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium
                                     hover:border-primary hover:text-primary disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-500"
                                >
                                    Previous
                                </button>
                                <button
                                    type="button"
                                    onClick={() => table.nextPage()}
                                    disabled={!table.getCanNextPage()}
                                    className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium
                                     hover:border-primary hover:text-primary disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-500"
                                >
                                    Next
                                </button>
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );
}
