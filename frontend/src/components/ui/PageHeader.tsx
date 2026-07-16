import type {ReactNode} from 'react';
import {cn} from '../../utils/cn';
import {Heading} from './Heading';

interface Props {
    title: string;
    description?: string;
    /** Right-aligned actions (buttons, filters). */
    actions?: ReactNode;
    className?: string;
}

/**
 * Consistent page title row: title + optional description on the left,
 * actions on the right. Use at the top of admin routes for visual rhythm.
 */
export function PageHeader({title, description, actions, className}: Props) {
    return (
        <div className={cn('mb-6 flex flex-wrap items-start justify-between gap-3', className)}>
            <div className="min-w-0">
                <Heading level={1}>{title}</Heading>
                {description && <p className="mt-1 text-sm text-gray-500">{description}</p>}
            </div>
            {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </div>
    );
}
