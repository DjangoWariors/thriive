import type {ReactNode} from 'react';
import {cn} from '../../utils/cn';

interface HeadingProps {
    /** 1 = page title, 2 = section title, 3 = sub-section / card title. */
    level: 1 | 2 | 3;
    children: ReactNode;
    className?: string;
}

const levelClasses: Record<HeadingProps['level'], string> = {
    1: 'text-xl font-semibold text-gray-900',
    2: 'text-lg font-semibold text-gray-900',
    3: 'text-sm font-semibold text-gray-900',
};

/**
 * Single source for heading typography. Use instead of ad-hoc text-xl/text-lg
 * so the type scale stays consistent across screens.
 */
export function Heading({level, children, className}: HeadingProps) {
    const Tag = (`h${level}`) as 'h1' | 'h2' | 'h3';
    return <Tag className={cn(levelClasses[level], className)}>{children}</Tag>;
}
