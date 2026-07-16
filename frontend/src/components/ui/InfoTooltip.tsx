import {Info} from 'lucide-react';
import {Tooltip} from './Tooltip';

interface Props {
    content: string;
    side?: 'top' | 'bottom' | 'left' | 'right';
}

/**
 * A small "(i)" affordance that reveals an explanation on hover. Use next to
 * terse labels or abbreviations (Req'd, Unique, GST, etc.).
 */
export function InfoTooltip({content, side = 'top'}: Props) {
    return (
        <Tooltip content={content} side={side}>
            <span className="inline-flex cursor-help text-gray-400 hover:text-gray-600" aria-label={content}>
                <Info className="h-3.5 w-3.5"/>
            </span>
        </Tooltip>
    );
}
