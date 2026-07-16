import {useMemo, useState} from 'react';
import {notify} from '../../utils/notify';
import {Modal} from '../ui/Modal';
import {Button} from '../ui/Button';
import {Textarea} from '../ui/Textarea';
import {TypePicker, ParentSearch, AttrField, buildZodSchema} from './EntityForm';
import {useBlueprint, useChangeEntityType} from '../../hooks/useEntities';
import {apiErrorMessage} from '../../utils/apiError';
import type {Entity, EntityListItem, EntityType} from '../../types/entity';

interface Props {
    entity: Entity;
    onClose: () => void;
}

export function ChangeTypeDialog({entity, onClose}: Props) {
    const {data: blueprint = []} = useBlueprint();
    const changeMutation = useChangeEntityType();

    // Candidate new types: everything except the current one.
    const candidates = useMemo(
        () => blueprint.filter((t) => t.id !== entity.entity_type.id),
        [blueprint, entity.entity_type.id],
    );

    const [newTypeId, setNewTypeId] = useState<number>(candidates[0]?.id ?? 0);
    const newType: EntityType | undefined = useMemo(
        () => blueprint.find((t) => t.id === newTypeId),
        [blueprint, newTypeId],
    );

    // Carry over the current attributes; the new schema reads what it needs.
    const [attrs, setAttrs] = useState<Record<string, unknown>>({...entity.attributes});
    const [attrErrors, setAttrErrors] = useState<Record<string, string>>({});
    const [parent, setParent] = useState<EntityListItem | null>(null);
    const [reassign, setReassign] = useState<EntityListItem | null>(null);
    const [reason, setReason] = useState('');
    const [effectiveDate, setEffectiveDate] = useState(
        new Date().toISOString().split('T')[0] as string,
    );

    const allowedParentLabels = useMemo(() => {
        if (!newType) return [];
        const byCode = new Map(blueprint.map((t) => [t.code, t.name]));
        return newType.allowed_parent_types.map((c) => byCode.get(c) ?? c);
    }, [newType, blueprint]);

    const canSubmit = newType !== undefined && reason.trim().length > 0;

    function handleSubmit() {
        if (!newType) return;

        const parsed = buildZodSchema(newType.attribute_schema).safeParse(attrs);
        if (!parsed.success) {
            const errs: Record<string, string> = {};
            for (const issue of parsed.error.issues) {
                const key = issue.path[0];
                if (typeof key === 'string') errs[key] = issue.message;
            }
            setAttrErrors(errs);
            return;
        }
        setAttrErrors({});

        changeMutation.mutate(
            {
                id: entity.id,
                payload: {
                    new_type_id: newType.id,
                    new_parent_id: parent?.id ?? null,
                    attributes: parsed.data,
                    reason: reason.trim(),
                    effective_date: effectiveDate,
                    reassign_reports_to: reassign?.id ?? null,
                },
            },
            {
                onSuccess: () => {
                    notify.success(`${entity.name} is now ${newType.name}.`);
                    onClose();
                },
                onError: (e) => notify.error(apiErrorMessage(e, 'Could not change role.')),
            },
        );
    }

    return (
        <Modal
            open
            onClose={onClose}
            title={`Change Role — ${entity.name}`}
            description={`Currently ${entity.entity_type.name}. Promote or demote to another type.`}
            size="2xl"
            footer={
                <>
                    <Button variant="outline" onClick={onClose}>Cancel</Button>
                    <Button onClick={handleSubmit} loading={changeMutation.isPending} disabled={!canSubmit}>
                        Apply Change
                    </Button>
                </>
            }
        >
            <div className="space-y-6">
                <section>
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">New type</h3>
                    <div className="mt-3">
                        <TypePicker blueprint={candidates} selectedId={newTypeId} onSelect={setNewTypeId}/>
                    </div>
                </section>

                {newType && (
                    <section>
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">New parent</h3>
                        <p className="mt-0.5 text-xs text-gray-400">
                            Leave empty only if {newType.name} can sit at the top.
                        </p>
                        <div className="mt-3">
                            <ParentSearch
                                allowedTypes={newType.allowed_parent_types}
                                allowedTypeLabels={allowedParentLabels}
                                value={parent}
                                onChange={setParent}
                            />
                        </div>
                    </section>
                )}

                {entity.children_count > 0 && (
                    <section>
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                            Reassign reports ({entity.children_count})
                        </h3>
                        <p className="mt-0.5 text-xs text-gray-400">
                            Move this entity’s direct reports to another manager. Required if they
                            wouldn’t be valid under the new type.
                        </p>
                        <div className="mt-3">
                            <ParentSearch
                                allowedTypes={[]}
                                allowedTypeLabels={[]}
                                value={reassign}
                                onChange={setReassign}
                            />
                        </div>
                    </section>
                )}

                {newType && newType.attribute_schema.length > 0 && (
                    <section>
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                            {newType.name} details
                        </h3>
                        <div className="mt-3 grid grid-cols-2 gap-4">
                            {newType.attribute_schema.map((field) => (
                                <AttrField
                                    key={field.key}
                                    field={field}
                                    value={attrs[field.key]}
                                    error={attrErrors[field.key]}
                                    onChange={(v) => setAttrs((prev) => ({...prev, [field.key]: v}))}
                                />
                            ))}
                        </div>
                    </section>
                )}

                <section>
                    <div className="grid grid-cols-2 gap-4">
                        <Textarea
                            label="Reason *"
                            placeholder="Promotion, role change, etc."
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            rows={2}
                        />
                        <div>
                            <label className="mb-1 block text-sm font-medium text-gray-700">Effective date</label>
                            <input
                                type="date"
                                value={effectiveDate}
                                onChange={(e) => setEffectiveDate(e.target.value)}
                                className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm
                                   focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                            />
                        </div>
                    </div>
                </section>
            </div>
        </Modal>
    );
}
