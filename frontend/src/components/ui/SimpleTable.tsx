import {Fragment, type ReactNode} from 'react';
import {cn} from '../../utils/cn';

export interface SimpleColumn<T> {
    header: ReactNode;
    align?: 'left' | 'center' | 'right';
    /** Extra th/td classes (e.g. width hints like 'w-20'). */
    className?: string;
    render: (row: T) => ReactNode;
}

interface SimpleTableProps<T> {
    columns: SimpleColumn<T>[];
    rows: T[];
    rowKey: (row: T) => string | number;
    onRowClick?: (row: T) => void;
    /** Rendered as a full-width row beneath a row when non-null (expandable tables). */
    expandedRow?: (row: T) => ReactNode | null;
    className?: string;
}

const ALIGN = {left: 'text-left', center: 'text-center', right: 'text-right'} as const;

/**
 * The plain, behavior-free table every list page composes — one place for the
 * thead/tbody styling. Needs sorting/column-toggle? That's `data/DataTable`
 * (client-side). Server-paginated grids pair this with `ui/Pagination`.
 */
export function SimpleTable<T>({columns, rows, rowKey, onRowClick, expandedRow, className}: SimpleTableProps<T>) {
    return (
        <table className={cn('w-full text-left text-sm', className)}>
            <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
                {columns.map((c, i) => (
                    <th key={i} className={cn('px-4 py-3', ALIGN[c.align ?? 'left'], c.className)}>
                        {c.header}
                    </th>
                ))}
            </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
            {rows.map((row) => {
                const expanded = expandedRow?.(row) ?? null;
                return (
                    <Fragment key={rowKey(row)}>
                        <tr
                            className={cn('hover:bg-gray-50', onRowClick && 'cursor-pointer')}
                            onClick={onRowClick ? () => onRowClick(row) : undefined}
                        >
                            {columns.map((c, i) => (
                                <td key={i} className={cn('px-4 py-3', ALIGN[c.align ?? 'left'], c.className)}>
                                    {c.render(row)}
                                </td>
                            ))}
                        </tr>
                        {expanded !== null && (
                            <tr>
                                <td colSpan={columns.length} className="bg-gray-50 px-6 py-4">{expanded}</td>
                            </tr>
                        )}
                    </Fragment>
                );
            })}
            </tbody>
        </table>
    );
}
