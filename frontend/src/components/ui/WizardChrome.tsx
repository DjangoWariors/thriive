import type { ComponentType } from 'react';
import { Check, ChevronRight, Info, Lightbulb } from 'lucide-react';
import { cn } from '../../utils/cn';

export interface WizardStep {
    label: string;
    icon: ComponentType<{ className?: string }>;
}

/**
 * Icon pill stepper shared by the EntityType and KPI wizards. Completed steps
 * are clickable (when `onStepClick` is provided) so users can jump back.
 */
export function Stepper({
    steps,
    current,
    onStepClick,
}: {
    steps: WizardStep[];
    current: number;
    onStepClick?: (index: number) => void;
}) {
    return (
        <div className="flex items-center gap-1 overflow-x-auto">
            {steps.map((s, i) => {
                const Icon = s.icon;
                const done = i < current;
                const active = i === current;
                const clickable = !!onStepClick && i !== current;
                return (
                    <div key={s.label} className="flex shrink-0 items-center gap-1">
                        <button
                            type="button"
                            disabled={!clickable}
                            onClick={() => onStepClick?.(i)}
                            className={cn(
                                'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
                                active && 'bg-primary text-white',
                                done && 'bg-primary-100 text-primary hover:bg-primary-100',
                                !active && !done && 'text-gray-400',
                                clickable && 'hover:text-gray-600',
                                !clickable && 'cursor-default',
                            )}
                        >
                            {done ? <Check className="h-3 w-3" /> : <Icon className="h-3 w-3" />}
                            {s.label}
                        </button>
                        {i < steps.length - 1 && <ChevronRight className="h-3 w-3 shrink-0 text-gray-300" />}
                    </div>
                );
            })}
        </div>
    );
}

/** Blue guidance box shown at the top of each wizard step. */
export function StepIntro({ title, body }: { title: string; body: string }) {
    return (
        <div className="mb-5 flex gap-3 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue-500" />
            <div>
                <p className="text-sm font-medium text-blue-900">{title}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-blue-700">{body}</p>
            </div>
        </div>
    );
}

/** Inline yellow-lightbulb example hint placed under a field. */
export function Example({ children }: { children: React.ReactNode }) {
    return (
        <p className="mt-1.5 flex items-start gap-1.5 text-xs text-gray-500">
            <Lightbulb className="mt-0.5 h-3 w-3 shrink-0 text-warning" />
            <span>{children}</span>
        </p>
    );
}
