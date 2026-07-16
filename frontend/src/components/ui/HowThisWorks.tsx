import {useState} from 'react';
import {HelpCircle, ChevronDown, ChevronUp} from 'lucide-react';
import {cn} from '../../utils/cn';

interface Props {
    title?: string;
    children: React.ReactNode;
    /**
     * When set, the collapsed/expanded state is remembered in localStorage under
     * this key. First visit shows it expanded; once a user collapses it, it stays
     * collapsed on later visits.
     */
    storageKey?: string;
    className?: string;
}

function readCollapsed(storageKey?: string): boolean {
    if (!storageKey || typeof window === 'undefined') return false;
    try {
        return window.localStorage.getItem(`howThisWorks:${storageKey}`) === 'collapsed';
    } catch {
        return false;
    }
}

/**
 * A friendly, collapsible "How this works" callout for explaining a screen in
 * plain language. Same blue visual language as the wizard's StepIntro, but
 * dismissible so power users can tuck it away.
 */
export function HowThisWorks({title = 'How this works', children, storageKey, className}: Props) {
    const [collapsed, setCollapsed] = useState(() => readCollapsed(storageKey));

    function toggle() {
        const next = !collapsed;
        setCollapsed(next);
        if (storageKey) {
            try {
                window.localStorage.setItem(
                    `howThisWorks:${storageKey}`,
                    next ? 'collapsed' : 'expanded',
                );
            } catch {
                /* ignore quota / privacy-mode errors */
            }
        }
    }

    return (
        <div className={cn('rounded-lg border border-blue-100 bg-blue-50', className)}>
            <button
                type="button"
                onClick={toggle}
                aria-expanded={!collapsed}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-left"
            >
                <HelpCircle className="h-4 w-4 shrink-0 text-blue-500"/>
                <span className="text-sm font-medium text-blue-900">{title}</span>
                {collapsed ? (
                    <ChevronDown className="ml-auto h-4 w-4 shrink-0 text-blue-400"/>
                ) : (
                    <ChevronUp className="ml-auto h-4 w-4 shrink-0 text-blue-400"/>
                )}
            </button>
            {!collapsed && (
                <div className="px-4 pb-3 pl-10 text-xs leading-relaxed text-blue-800">
                    {children}
                </div>
            )}
        </div>
    );
}
