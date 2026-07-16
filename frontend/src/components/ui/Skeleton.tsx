import type {CSSProperties} from 'react';
import {cn} from '../../utils/cn';

interface SkeletonProps {
    variant?: 'text' | 'circle' | 'rect';
    width?: string | number;
    height?: string | number;
    className?: string;
}

export function Skeleton({variant = 'text', width, height, className}: SkeletonProps) {
    const style: CSSProperties = {};
    if (width !== undefined) style.width = typeof width === 'number' ? `${width}px` : width;
    if (height !== undefined) style.height = typeof height === 'number' ? `${height}px` : height;

    return (
        <div
            className={cn(
                'animate-pulse bg-gray-200',
                variant === 'text' && 'h-4 rounded',
                variant === 'circle' && 'rounded-full',
                variant === 'rect' && 'rounded-lg',
                className
            )}
            style={style}
        />
    );
}

/** Standard loading state for list/table pages — a card of shimmering rows. */
export function TableSkeleton({rows = 8, className}: { rows?: number; className?: string }) {
    return (
        <div className={cn('rounded-xl border border-gray-200 bg-white', className)} aria-busy="true">
            <div className="border-b border-gray-100 px-4 py-3">
                <Skeleton width="40%"/>
            </div>
            <div className="divide-y divide-gray-100">
                {Array.from({length: rows}).map((_, i) => (
                    <div key={i} className="flex items-center gap-4 px-4 py-3.5">
                        <Skeleton width="18%"/>
                        <Skeleton width="30%"/>
                        <Skeleton width="14%"/>
                        <Skeleton width="10%" className="ml-auto"/>
                    </div>
                ))}
            </div>
        </div>
    );
}

/** Standard loading state for card-grid pages (dashboards, SIP structure). */
export function CardGridSkeleton({cards = 4, className}: { cards?: number; className?: string }) {
    return (
        <div className={cn('grid grid-cols-1 gap-4 sm:grid-cols-2', className)} aria-busy="true">
            {Array.from({length: cards}).map((_, i) => (
                <div key={i} className="rounded-xl border border-gray-200 bg-white p-4">
                    <Skeleton width="50%"/>
                    <Skeleton width="80%" className="mt-3"/>
                    <Skeleton variant="rect" height={12} className="mt-3 w-full"/>
                    <Skeleton width="35%" className="mt-3"/>
                </div>
            ))}
        </div>
    );
}
