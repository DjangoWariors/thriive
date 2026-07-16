import {useRef, useState} from 'react';
import {GripVertical, Plus, Trash2} from 'lucide-react';
import {cn} from '../../utils/cn';
import {InfoTooltip} from '../ui/InfoTooltip';
import type {AttributeField} from '../../types/entity';


const FIELD_TYPES: { value: AttributeField['type']; label: string }[] = [
    {value: 'string', label: 'Text'},
    {value: 'integer', label: 'Integer'},
    {value: 'decimal', label: 'Decimal'},
    {value: 'date', label: 'Date'},
    {value: 'boolean', label: 'Boolean'},
    {value: 'choice', label: 'Choice'},
    {value: 'email', label: 'Email'},
    {value: 'phone', label: 'Phone'},
];

// Ready-made format rules so most users never have to write a regex by hand.
const PATTERN_PRESETS: { label: string; pattern: string }[] = [
    {label: 'Letters only', pattern: '^[A-Za-z ]+$'},
    {label: 'Alphanumeric', pattern: '^[A-Za-z0-9]+$'},
    {label: '10-digit phone', pattern: '^[0-9]{10}$'},
    {label: 'PAN', pattern: '^[A-Z]{5}[0-9]{4}[A-Z]$'},
    {label: 'GSTIN', pattern: '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$'},
];

function emptyField(): AttributeField {
    return {key: '', label: '', type: 'string', required: false, unique: false};
}

function parseOptionalInt(v: string): number | undefined {
    const n = parseInt(v, 10);
    return isNaN(n) ? undefined : n;
}

/** Returns an error message if the pattern is not a valid regex, else null. */
function regexError(pattern?: string): string | null {
    if (!pattern) return null;
    try {
        new RegExp(pattern);
        return null;
    } catch (e) {
        return (e as Error).message;
    }
}


interface Props {
    value: AttributeField[];
    onChange: (fields: AttributeField[]) => void;
    disabled?: boolean;
}


interface RowProps {
    field: AttributeField;
    index: number;
    isDragOver: boolean;
    disabled: boolean;
    onUpdate: (updates: Partial<AttributeField>) => void;
    onRemove: () => void;
    onDragStart: () => void;
    onDragOver: (e: React.DragEvent) => void;
    onDrop: () => void;
    onDragEnd: () => void;
}

function FieldRow({
                      field,
                      index,
                      isDragOver,
                      disabled,
                      onUpdate,
                      onRemove,
                      onDragStart,
                      onDragOver,
                      onDrop,
                      onDragEnd,
                  }: RowProps) {
    const needsOptions = field.type === 'choice';
    const needsStringConfig = field.type === 'string';
    const needsNumericRange = field.type === 'integer' || field.type === 'decimal';
    const hasExpanded = needsOptions || needsStringConfig || needsNumericRange;

    const patternErr = regexError(field.pattern);

    // options stored as string[], edited as comma-separated text
    const optionsText = field.options?.join(', ') ?? '';

    return (
        <div
            draggable
            onDragStart={onDragStart}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onDragEnd={onDragEnd}
            className={cn(
                'rounded-lg border bg-white transition-colors',
                isDragOver ? 'border-primary bg-primary-50 ring-1 ring-primary/30' : 'border-gray-200',
                disabled && 'opacity-60',
            )}
        >

            <div className="flex items-center gap-2 px-3 py-2">

                <button
                    type="button"
                    className="cursor-grab text-gray-300 hover:text-gray-500 active:cursor-grabbing touch-none"
                    aria-label="Drag to reorder"
                    tabIndex={-1}
                >
                    <GripVertical className="h-4 w-4"/>
                </button>


                <span className="w-5 shrink-0 text-xs text-gray-500 font-mono">{index + 1}</span>


                <input
                    type="text"
                    placeholder="field_id"
                    title="Internal tag (lowercase, no spaces). Auto-formatted as you type."
                    value={field.key}
                    disabled={disabled}
                    onChange={(e) =>
                        onUpdate({key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '')})
                    }
                    className="w-28 shrink-0 rounded border border-gray-200 bg-gray-50 px-2 py-1 font-mono text-xs
                     focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                />


                <input
                    type="text"
                    placeholder="e.g. Employee ID"
                    title="The human-friendly name staff will see on the form"
                    value={field.label}
                    disabled={disabled}
                    onChange={(e) => onUpdate({label: e.target.value})}
                    className="min-w-0 flex-1 rounded border border-gray-200 bg-gray-50 px-2 py-1 text-xs
                     focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                />


                <select
                    value={field.type}
                    disabled={disabled}
                    onChange={(e) =>
                        onUpdate({type: e.target.value as AttributeField['type'], options: undefined})
                    }
                    className="w-24 shrink-0 rounded border border-gray-200 bg-gray-50 px-1 py-1 text-xs
                     focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                >
                    {FIELD_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>
                            {t.label}
                        </option>
                    ))}
                </select>


                <label className="flex items-center gap-1 shrink-0 cursor-pointer select-none">
                    <input
                        type="checkbox"
                        checked={field.required}
                        disabled={disabled}
                        onChange={(e) => onUpdate({required: e.target.checked})}
                        className="h-3.5 w-3.5 rounded border-gray-300 accent-primary"
                    />
                    <span className="text-xs text-gray-600">Req'd</span>
                </label>


                <label className="flex items-center gap-1 shrink-0 cursor-pointer select-none">
                    <input
                        type="checkbox"
                        checked={field.unique}
                        disabled={disabled}
                        onChange={(e) => onUpdate({unique: e.target.checked})}
                        className="h-3.5 w-3.5 rounded border-gray-300 accent-primary"
                    />
                    <span className="text-xs text-gray-600">Unique</span>
                </label>


                <button
                    type="button"
                    onClick={onRemove}
                    disabled={disabled}
                    className="shrink-0 text-gray-300 hover:text-danger transition-colors"
                    aria-label="Remove field"
                >
                    <Trash2 className="h-3.5 w-3.5"/>
                </button>
            </div>


            {hasExpanded && (
                <div className="flex flex-wrap gap-3 border-t border-gray-100 bg-gray-50/60 px-10 py-2">
                    {needsOptions && (
                        <div className="flex-1 min-w-48">
                            <label className="block text-xs font-medium text-gray-600 mb-1">
                                Options <span className="text-gray-400">(comma-separated)</span>
                            </label>
                            <input
                                type="text"
                                placeholder="A, B, C, D"
                                value={optionsText}
                                disabled={disabled}
                                onChange={(e) =>
                                    onUpdate({
                                        options: e.target.value
                                            .split(',')
                                            .map((s) => s.trim())
                                            .filter(Boolean),
                                    })
                                }
                                className="w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs
                           focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                            />
                        </div>
                    )}

                    {needsStringConfig && (
                        <>
                            <div className="w-24">
                                <label className="block text-xs font-medium text-gray-600 mb-1">Min length</label>
                                <input
                                    type="number"
                                    min={0}
                                    placeholder="—"
                                    value={field.min ?? ''}
                                    disabled={disabled}
                                    onChange={(e) => onUpdate({min: parseOptionalInt(e.target.value)})}
                                    className="w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs
                             focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                                />
                            </div>
                            <div className="w-24">
                                <label className="block text-xs font-medium text-gray-600 mb-1">Max length</label>
                                <input
                                    type="number"
                                    min={0}
                                    placeholder="—"
                                    value={field.max ?? ''}
                                    disabled={disabled}
                                    onChange={(e) => onUpdate({max: parseOptionalInt(e.target.value)})}
                                    className="w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs
                             focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                                />
                            </div>
                            <div className="min-w-48 flex-1">
                                <label className="mb-1 flex items-center gap-1 text-xs font-medium text-gray-600">
                                    Format rule <span className="text-gray-400">(optional)</span>
                                    <InfoTooltip content="Restricts what staff can enter. Pick a preset, or leave blank to allow anything."/>
                                </label>
                                <input
                                    type="text"
                                    placeholder="Pick a preset or leave blank"
                                    value={field.pattern ?? ''}
                                    disabled={disabled}
                                    onChange={(e) =>
                                        onUpdate({pattern: e.target.value || undefined})
                                    }
                                    className={cn(
                                        'w-full rounded border bg-white px-2 py-1 font-mono text-xs focus:outline-none focus:ring-1',
                                        patternErr
                                            ? 'border-danger focus:border-danger focus:ring-danger/20'
                                            : 'border-gray-200 focus:border-primary focus:ring-primary/20',
                                    )}
                                />
                                <div className="mt-1 flex flex-wrap gap-1">
                                    {PATTERN_PRESETS.map((p) => (
                                        <button
                                            key={p.label}
                                            type="button"
                                            disabled={disabled}
                                            onClick={() => onUpdate({pattern: p.pattern})}
                                            className={cn(
                                                'rounded-full border px-2 py-0.5 text-[11px] transition-colors',
                                                field.pattern === p.pattern
                                                    ? 'border-primary bg-primary text-white'
                                                    : 'border-gray-200 bg-white text-gray-600 hover:border-primary hover:text-primary',
                                            )}
                                        >
                                            {p.label}
                                        </button>
                                    ))}
                                    {field.pattern && (
                                        <button
                                            type="button"
                                            disabled={disabled}
                                            onClick={() => onUpdate({pattern: undefined})}
                                            className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-500 hover:text-gray-700"
                                        >
                                            Clear
                                        </button>
                                    )}
                                </div>
                                {patternErr ? (
                                    <p className="mt-1 text-[11px] text-danger">That rule isn’t valid — try a preset above.</p>
                                ) : field.pattern ? (
                                    <p className="mt-1 text-[11px] text-success">Valid rule.</p>
                                ) : null}
                            </div>
                        </>
                    )}

                    {needsNumericRange && (
                        <>
                            <div className="w-24">
                                <label className="block text-xs font-medium text-gray-600 mb-1">Min</label>
                                <input
                                    type="number"
                                    placeholder="—"
                                    value={field.min ?? ''}
                                    disabled={disabled}
                                    onChange={(e) => onUpdate({min: parseOptionalInt(e.target.value)})}
                                    className="w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs
                             focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                                />
                            </div>
                            <div className="w-24">
                                <label className="block text-xs font-medium text-gray-600 mb-1">Max</label>
                                <input
                                    type="number"
                                    placeholder="—"
                                    value={field.max ?? ''}
                                    disabled={disabled}
                                    onChange={(e) => onUpdate({max: parseOptionalInt(e.target.value)})}
                                    className="w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs
                             focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20"
                                />
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}


export function AttributeSchemaBuilder({value, onChange, disabled = false}: Props) {
    const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
    const dragIndexRef = useRef<number | null>(null);

    function addField() {
        onChange([...value, emptyField()]);
    }

    function removeField(index: number) {
        onChange(value.filter((_, i) => i !== index));
    }

    function updateField(index: number, updates: Partial<AttributeField>) {
        onChange(value.map((f, i) => (i === index ? {...f, ...updates} : f)));
    }

    function handleDragStart(index: number) {
        dragIndexRef.current = index;
    }

    function handleDragOver(e: React.DragEvent, index: number) {
        e.preventDefault();
        setDragOverIndex(index);
    }

    function handleDrop(targetIndex: number) {
        const srcIndex = dragIndexRef.current;
        if (srcIndex === null || srcIndex === targetIndex) {
            setDragOverIndex(null);
            return;
        }
        const updated = [...value];
        const [removed] = updated.splice(srcIndex, 1);
        updated.splice(targetIndex, 0, removed);
        onChange(updated);
        setDragOverIndex(null);
        dragIndexRef.current = null;
    }

    function handleDragEnd() {
        setDragOverIndex(null);
        dragIndexRef.current = null;
    }

    return (
        <div className="space-y-2">

            {value.length > 0 && (
                <div className="flex items-center gap-2 px-3 text-xs font-medium text-gray-400">
                    <span className="w-4"/>
                    <span className="w-5"/>
                    <span className="w-28" title="Internal tag used by the system">Field ID</span>
                    <span className="flex-1" title="What staff see on the form">Label</span>
                    <span className="w-24">Type</span>
                    <span className="w-9" title="Must always be filled in">Req'd</span>
                    <span className="w-9" title="No two records can share this value">Unique</span>
                    <span className="w-4"/>
                </div>
            )}


            {value.map((field, i) => (
                <FieldRow
                    key={i}
                    field={field}
                    index={i}
                    isDragOver={dragOverIndex === i}
                    disabled={disabled}
                    onUpdate={(updates) => updateField(i, updates)}
                    onRemove={() => removeField(i)}
                    onDragStart={() => handleDragStart(i)}
                    onDragOver={(e) => handleDragOver(e, i)}
                    onDrop={() => handleDrop(i)}
                    onDragEnd={handleDragEnd}
                />
            ))}

            {value.length === 0 && (
                <div
                    className="rounded-lg border-2 border-dashed border-gray-200 py-8 text-center text-sm text-gray-400">
                    No information fields yet. Click "Add Field" below to record your first one.
                </div>
            )}


            <button
                type="button"
                onClick={addField}
                disabled={disabled}
                className={cn(
                    'flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed',
                    'border-gray-300 py-2 text-sm text-gray-500',
                    'hover:border-primary hover:text-primary transition-colors',
                    'disabled:opacity-50 disabled:cursor-not-allowed',
                )}
            >
                <Plus className="h-4 w-4"/>
                Add Field
            </button>
        </div>
    );
}
