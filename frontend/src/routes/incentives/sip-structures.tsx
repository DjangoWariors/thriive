import {Link} from 'react-router';
import {Layers, CheckCircle2, AlertCircle} from 'lucide-react';
import {useSipStructures} from '../../hooks/useIncentives';
import type {SipStructureGroup} from '../../types/incentive';
import {Badge} from '../../components/ui/Badge';
import {Card} from '../../components/ui/Card';
import {EmptyState} from '../../components/ui/EmptyState';
import {HowThisWorks} from '../../components/ui/HowThisWorks';
import {PageHeader} from '../../components/ui/PageHeader';
import {CardGridSkeleton} from '../../components/ui/Skeleton';

export default function SipStructuresPage() {
    const {data: groups, isLoading} = useSipStructures();

    return (
        <div className="p-6">
            <PageHeader
                title="SIP Structure"
                description="How each role's variable pay is allocated across SIP components — e.g. Expert: 80% against monthly KPIs + 20% against annual performance."
            />

            <HowThisWorks storageKey="sip-structures-help" className="mb-6">
                A Sales Incentive Plan (SIP) can pay variable pay in parts: a monthly scheme paying against
                monthly KPIs (say 80% of VP) and an annual scheme paying against full-year performance (the
                remaining 20%). Each part is an ordinary incentive scheme with its own KPIs, weightages and
                multiplier slabs — this view groups them per role × channel and checks the shares add up to
                100%. A single scheme at 100% is equally valid.
            </HowThisWorks>

            {isLoading ? (
                <CardGridSkeleton/>
            ) : !groups || groups.length === 0 ? (
                <Card>
                    <EmptyState icon={Layers} title="No SIP schemes yet"
                                description="Create incentive schemes and they will be grouped here by role and channel."/>
                </Card>
            ) : (
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    {groups.map((g) => <SipCard key={`${g.entity_type}-${g.channel ?? 'all'}`} group={g}/>)}
                </div>
            )}
        </div>
    );
}

function SipCard({group}: { group: SipStructureGroup }) {
    const total = parseFloat(group.total_vp_basis_pct);
    return (
        <Card>
            <div className="mb-3 flex items-start justify-between">
                <div>
                    <p className="font-semibold text-gray-900">{group.entity_type_name}</p>
                    <p className="text-xs text-gray-500">
                        {group.entity_type} · {group.channel ?? 'All channels'}
                    </p>
                </div>
                {group.is_complete ? (
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-success">
                        <CheckCircle2 className="h-4 w-4"/> Complete (100%)
                    </span>
                ) : (
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-warning"
                          title="Variable-pay shares don't sum to 100% — fine if intentional.">
                        <AlertCircle className="h-4 w-4"/> {group.total_vp_basis_pct}% of VP covered
                    </span>
                )}
            </div>

            {/* VP split bar */}
            <div className="mb-3 flex h-3 w-full overflow-hidden rounded-full bg-gray-100">
                {group.components.map((c, i) => (
                    <div key={c.scheme_id}
                         className={i % 2 === 0 ? 'bg-primary' : 'bg-primary-light'}
                         style={{width: `${Math.min(100, parseFloat(c.vp_basis_pct))}%`}}
                         title={`${c.scheme_name}: ${c.vp_basis_pct}%`}/>
                ))}
                {total < 100 && <div className="flex-1 bg-gray-100"/>}
            </div>

            <div className="divide-y divide-gray-100">
                {group.components.map((c) => (
                    <div key={c.scheme_id} className="flex items-center justify-between py-2 text-sm">
                        <div>
                            <Link to={`/incentives/schemes/builder/${c.scheme_id}`}
                                  className="font-medium text-gray-900 hover:text-primary">
                                {c.scheme_name}
                            </Link>
                            <span className="ml-2 text-xs text-gray-500">{c.scheme_code}</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <Badge variant={c.payout_frequency === 'annual' ? 'purple' : 'info'}>
                                {c.payout_frequency}
                            </Badge>
                            <span className="text-xs text-gray-500">{c.kpi_count} KPI{c.kpi_count === 1 ? '' : 's'}</span>
                            <span className="w-14 text-right font-semibold text-gray-900">{c.vp_basis_pct}%</span>
                        </div>
                    </div>
                ))}
            </div>
        </Card>
    );
}
