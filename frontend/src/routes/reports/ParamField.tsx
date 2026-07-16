import {Input} from '../../components/ui/Input';
import {Select} from '../../components/ui/Select';
import type {ReportParamField} from '../../types/reports';

export function ParamField({field, value, onChange}: {
    field: ReportParamField;
    value: string;
    onChange: (value: string) => void;
}) {
    const label = field.required ? `${field.label} *` : field.label;

    if (field.type === 'choice') {
        return (
            <Select
                label={label}
                placeholder="Select…"
                options={[
                    {value: '', label: 'Any'},
                    ...(field.options ?? []).map((o) => ({value: o, label: o})),
                ]}
                value={value}
                onChange={(e) => onChange(e.target.value)}
            />
        );
    }

    if (field.type === 'boolean') {
        return (
            <Select
                label={label}
                options={[
                    {value: '', label: 'Any'},
                    {value: 'true', label: 'Yes'},
                    {value: 'false', label: 'No'},
                ]}
                value={value}
                onChange={(e) => onChange(e.target.value)}
            />
        );
    }

    const inputType =
        field.type === 'date' ? 'date'
            : field.type === 'integer' || field.type === 'decimal' ? 'number'
                : 'text';

    return (
        <Input
            label={label}
            type={inputType}
            value={value}
            onChange={(e) => onChange(e.target.value)}
        />
    );
}

/** Coerce raw string form values into typed report parameters. */
export function buildParameters(
    schema: ReportParamField[],
    values: Record<string, string>,
): Record<string, unknown> {
    const parameters: Record<string, unknown> = {};
    for (const field of schema) {
        const raw = values[field.key];
        if (raw === undefined || raw === '') continue;
        parameters[field.key] =
            field.type === 'integer' ? Number(raw)
                : field.type === 'boolean' ? raw === 'true'
                    : raw;
    }
    return parameters;
}
