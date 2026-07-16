/** Read-only rendering of a dialog field whose value the launch context fixed
 * (e.g. the territory when assigning from that territory's panel). */
export function PinnedField({label, name, code}: {label: string; name: string; code?: string}) {
    return (
        <div>
            <p className="mb-1 text-sm font-medium text-gray-700">{label}</p>
            <div className="flex items-baseline gap-2 rounded-lg bg-gray-50 px-3 py-2 text-sm">
                <span className="font-medium text-gray-900">{name}</span>
                {code && <code className="text-xs text-gray-500">{code}</code>}
            </div>
        </div>
    );
}
