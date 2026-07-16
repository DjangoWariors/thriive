import {lazy, Suspense, useEffect} from 'react';
import {BrowserRouter, Routes, Route, Navigate, Outlet, useParams} from 'react-router';
import {Toaster} from 'sonner';
import {useAuth} from './hooks/useAuth';
import {AdminLayout} from './components/layout/AdminLayout';
import {PartnerLayout} from './components/layout/PartnerLayout';
import {RequirePermission, RequirePlanningAdmin} from './components/auth/RequirePermission';
import {Spinner} from './components/ui/Spinner';
import {EXTERNAL_METRICS_ENABLED} from './config/features';


const Login = lazy(() => import('./routes/auth/login'));
const Dashboard = lazy(() => import('./routes/dashboard/index'));
const NetworkWorkspaceLayout = lazy(() => import('./routes/network/index'));
const NetworkSetupLayout = lazy(() => import('./routes/network/setup'));
const EntityTypesPage = lazy(() => import('./routes/network/setup-role-types'));
const PeoplePage = lazy(() => import('./routes/network/people'));
const PersonDetailPage = lazy(() => import('./routes/network/person-detail'));
const UsersPage = lazy(() => import('./routes/admin/users'));
const RolesPage = lazy(() => import('./routes/admin/roles'));
const AuditLogsPage = lazy(() => import('./routes/admin/audit-logs'));
const ReportsPage = lazy(() => import('./routes/reports/index'));
const SKUsPage = lazy(() => import('./routes/master/skus'));
const SKUGroupsPage = lazy(() => import('./routes/master/sku-groups'));
const UOMConversionsPage = lazy(() => import('./routes/master/uom-conversions'));
const ChannelsPage = lazy(() => import('./routes/network/setup-channels'));
const TerritoriesPage = lazy(() => import('./routes/network/territories'));
const OwnersPage = lazy(() => import('./routes/network/owners'));
const KpiDefinitionsPage = lazy(() => import('./routes/kpi/definitions'));
const KpiBuilderPage = lazy(() => import('./routes/kpi/kpi-builder'));
const TransactionsPage = lazy(() => import('./routes/kpi/transactions'));
const ExternalMetricsPage = lazy(() => import('./routes/admin/external-metrics'));
const IntegrationMonitorPage = lazy(() => import('./routes/admin/integration-monitor'));
const ApiKeysPage = lazy(() => import('./routes/admin/api-keys'));
const DeliveryTargetsPage = lazy(() => import('./routes/admin/delivery-targets'));
const TargetSettingPage = lazy(() => import('./routes/targets/index'));
const PlanNewPage = lazy(() => import('./routes/targets/plan-new'));
const PlanWorkspacePage = lazy(() => import('./routes/targets/plan-detail'));
const RecipesPage = lazy(() => import('./routes/targets/recipes'));
const PlanningCalendarPage = lazy(() => import('./routes/targets/periods'));
const RevisionPoliciesPage = lazy(() => import('./routes/targets/revision-policies'));
const AchievementsPage = lazy(() => import('./routes/achievements/dashboard'));
const AchievementDrilldownPage = lazy(() => import('./routes/achievements/drilldown'));
const AlertRulesPage = lazy(() => import('./routes/achievements/alert-rules'));
const SchemesPage = lazy(() => import('./routes/incentives/schemes'));
const SipStructuresPage = lazy(() => import('./routes/incentives/sip-structures'));
const SchemeBuilderPage = lazy(() => import('./routes/incentives/scheme-builder'));
const VariablePayPage = lazy(() => import('./routes/incentives/variable-pay'));
const PayoutSummaryPage = lazy(() => import('./routes/incentives/payout-summary'));
const CycleWorkspacePage = lazy(() => import('./routes/incentives/cycles'));
const PayoutBreakdownPage = lazy(() => import('./routes/incentives/payout-breakdown'));
const ExceptionsPage = lazy(() => import('./routes/exceptions/index'));
const WorkflowsPendingPage = lazy(() => import('./routes/workflows/pending'));
const PartnerDashboard = lazy(() => import('./routes/partner/dashboard'));
const PartnerPayouts = lazy(() => import('./routes/partner/payouts'));
const PartnerProfilePage = lazy(() => import('./routes/partner/profile'));
const SettingsPage = lazy(() => import('./routes/settings/index'));


function FullPageSpinner() {
    return (
        <div className="flex min-h-screen items-center justify-center bg-gray-50">
            <Spinner size="lg"/>
        </div>
    );
}

function Forbidden() {
    return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 p-8 text-center">
            <p className="text-7xl font-bold text-gray-200">403</p>
            <h2 className="mt-4 text-xl font-semibold text-gray-900">Access Denied</h2>
            <p className="mt-2 text-sm text-gray-500">
                You don't have permission to view this page.
            </p>
        </div>
    );
}



function ProtectedRoute() {
    const {isAuthenticated, isLoading, user, fetchUser} = useAuth();

    useEffect(() => {
        if (isAuthenticated && !user) {
            void fetchUser();
        }
    }, [isAuthenticated, user, fetchUser]);

    if (!isAuthenticated) return <Navigate to="/login" replace/>;
    if (isLoading || !user) return <FullPageSpinner/>;

    return <Outlet/>;
}


function PortalLayout() {
    const {user} = useAuth();
    if (user?.portal_type === 'partner') return <PartnerLayout/>;
    return <AdminLayout/>;
}

function PortalHome() {
    const {user} = useAuth();
    return user?.portal_type === 'partner' ? <PartnerDashboard/> : <Dashboard/>;
}

function LegacyPersonRedirect() {
    const {id} = useParams();
    return <Navigate to={`/network/people/${id}`} replace/>;
}


function App() {
    return (
        <BrowserRouter>
            <Suspense fallback={<FullPageSpinner/>}>
                <Routes>
                    <Route path="/login" element={<Login/>}/>
                    <Route element={<ProtectedRoute/>}>
                        <Route element={<PortalLayout/>}>
                            <Route path="/" element={<PortalHome/>}/>
                            <Route path="/403" element={<Forbidden/>}/>
                            <Route path="/my-payouts" element={<PartnerPayouts/>}/>
                            <Route path="/profile" element={<PartnerProfilePage/>}/>


                            <Route path="/settings" element={<SettingsPage/>}/>

                            <Route element={<RequirePermission permission="hierarchy_management"/>}>
                                <Route path="/network" element={<NetworkWorkspaceLayout/>}>
                                    <Route index element={<Navigate to="/network/people" replace/>}/>
                                    <Route path="people" element={<PeoplePage/>}/>
                                    <Route path="people/:id" element={<PersonDetailPage/>}/>
                                    <Route path="territories" element={<TerritoriesPage/>}/>
                                    <Route path="owners" element={<OwnersPage/>}/>
                                    <Route path="setup" element={<NetworkSetupLayout/>}>
                                        <Route index element={<Navigate to="/network/setup/role-types" replace/>}/>
                                        <Route path="role-types" element={<EntityTypesPage/>}/>
                                        <Route path="channels" element={<ChannelsPage/>}/>
                                    </Route>
                                </Route>
                                {/* Legacy URLs — every pre-workspace path redirects. */}
                                <Route path="/hierarchy" element={<Navigate to="/network/people" replace/>}/>
                                <Route path="/hierarchy/:id" element={<LegacyPersonRedirect/>}/>
                                <Route path="/geography" element={<Navigate to="/network/territories" replace/>}/>
                                <Route path="/assignments" element={<Navigate to="/network/owners" replace/>}/>
                                <Route path="/admin/entity-types" element={<Navigate to="/network/setup/role-types" replace/>}/>
                                <Route path="/admin/channels" element={<Navigate to="/network/setup/channels" replace/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="user_management"/>}>
                                <Route path="/admin/users" element={<UsersPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="role_management"/>}>
                                <Route path="/admin/roles" element={<RolesPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="audit_logs"/>}>
                                <Route path="/admin/audit" element={<AuditLogsPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="report_generation"/>}>
                                <Route path="/reports" element={<ReportsPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="master_data"/>}>
                                <Route path="/master/skus" element={<SKUsPage/>}/>
                                <Route path="/master/sku-groups" element={<SKUGroupsPage/>}/>
                                <Route path="/master/uom-conversions" element={<UOMConversionsPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="kpi_definitions"/>}>
                                <Route path="/kpi/definitions" element={<KpiDefinitionsPage/>}/>
                                <Route path="/kpi/builder" element={<KpiBuilderPage/>}/>
                                <Route path="/kpi/builder/:id" element={<KpiBuilderPage/>}/>
                                <Route path="/kpi/transactions" element={<TransactionsPage/>}/>
                                {EXTERNAL_METRICS_ENABLED && (
                                    <Route path="/admin/external-metrics" element={<ExternalMetricsPage/>}/>
                                )}
                            </Route>

                            <Route element={<RequirePermission permission="integration_monitor"/>}>
                                <Route path="/admin/integration-monitor" element={<IntegrationMonitorPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="system_admin"/>}>
                                <Route path="/admin/api-keys" element={<ApiKeysPage/>}/>
                                <Route path="/admin/delivery-targets" element={<DeliveryTargetsPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="target_management"/>}>
                                <Route path="/targets" element={<TargetSettingPage/>}/>
                                <Route path="/targets/:id" element={<PlanWorkspacePage/>}/>
                            </Route>
                            <Route element={<RequirePlanningAdmin permission="target_management"/>}>
                                <Route path="/targets/new" element={<PlanNewPage/>}/>
                                <Route path="/targets/recipes" element={<RecipesPage/>}/>
                                <Route path="/targets/periods" element={<PlanningCalendarPage/>}/>
                                <Route path="/targets/revision-policies" element={<RevisionPoliciesPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="achievement_view"/>}>
                                <Route path="/achievements" element={<AchievementsPage/>}/>
                                <Route path="/achievements/:id" element={<AchievementDrilldownPage/>}/>
                            </Route>
                            <Route element={<RequirePlanningAdmin permission="achievement_view"/>}>
                                <Route path="/achievements/alert-rules" element={<AlertRulesPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="scheme_management"/>}>
                                <Route path="/incentives/schemes" element={<SchemesPage/>}/>
                                <Route path="/incentives/sip-structures" element={<SipStructuresPage/>}/>
                                <Route path="/incentives/schemes/builder" element={<SchemeBuilderPage/>}/>
                                <Route path="/incentives/schemes/builder/:id" element={<SchemeBuilderPage/>}/>
                                <Route path="/incentives/variable-pay" element={<VariablePayPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="final_payout"/>}>
                                <Route path="/incentives/cycles" element={<CycleWorkspacePage/>}/>
                                <Route path="/incentives/payouts" element={<PayoutSummaryPage/>}/>
                                <Route path="/incentives/payouts/:id" element={<PayoutBreakdownPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="exception_management"/>}>
                                <Route path="/exceptions" element={<ExceptionsPage/>}/>
                            </Route>

                            <Route element={<RequirePermission permission="workflow_management"/>}>
                                <Route path="/workflows/pending" element={<WorkflowsPendingPage/>}/>
                            </Route>

                        </Route>
                    </Route>


                    <Route path="*" element={<Navigate to="/login" replace/>}/>
                </Routes>
            </Suspense>

            <Toaster position="top-right" richColors/>
        </BrowserRouter>
    );
}

export default App;
