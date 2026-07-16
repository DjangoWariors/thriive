import {Fragment} from 'react';
import {ChevronRight} from 'lucide-react';
import {cn} from '../../utils/cn';

export interface BreadcrumbItem {
    label: string;
    /** When provided, the crumb renders as a clickable button. */
    onClick?: () => void;
}

interface Props {
    items: BreadcrumbItem[];
    className?: string;
}

/**
 * "You are here" trail. The last item is rendered as the current location
 * (non-interactive, emphasized); earlier items are clickable when given onClick.
 */
export function Breadcrumb({items, className}: Props) {
    if (items.length === 0) return null;

    return (
        <nav aria-label="Breadcrumb" className={cn('flex flex-wrap items-center gap-1 text-xs text-gray-500', className)}>
            {items.map((item, i) => {
                const isLast = i === items.length - 1;
                return (
                    <Fragment key={i}>
                        {item.onClick && !isLast ? (
                            <button
                                type="button"
                                onClick={item.onClick}
                                className="max-w-[12rem] truncate rounded px-1 hover:bg-gray-100 hover:text-gray-700"
                            >
                                {item.label}
                            </button>
                        ) : (
                            <span className={cn('max-w-[12rem] truncate px-1', isLast && 'font-medium text-gray-700')}>
                                {item.label}
                            </span>
                        )}
                        {!isLast && <ChevronRight className="h-3 w-3 shrink-0 text-gray-300"/>}
                    </Fragment>
                );
            })}
        </nav>
    );
}
