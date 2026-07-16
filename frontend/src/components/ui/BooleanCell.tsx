import {Check, Minus} from 'lucide-react';

interface Props {
    value: boolean;
    /** Accessible labels, e.g. "Can log in" / "No login". */
    trueLabel?: string;
    falseLabel?: string;
}

/**
 * Accessible yes/no cell. Replaces ✅/❌ emoji in tables — a colored check for
 * true, a muted dash for false, each with an aria-label so meaning isn't
 * carried by color alone.
 */
export function BooleanCell({value, trueLabel = 'Yes', falseLabel = 'No'}: Props) {
    return value ? (
        <span className="inline-flex text-success" role="img" aria-label={trueLabel} title={trueLabel}>
            <Check className="h-4 w-4"/>
        </span>
    ) : (
        <span className="inline-flex text-gray-300" role="img" aria-label={falseLabel} title={falseLabel}>
            <Minus className="h-4 w-4"/>
        </span>
    );
}
