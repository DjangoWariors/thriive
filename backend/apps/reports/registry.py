"""Generator registry. Each FMCG report is a thin BaseReportGenerator that turns
validated params + an RBAC scope into a ReportResult. The engine (services/tasks)
renders the result to XLSX/PDF/CSV — generators never touch files or formatting.
"""
from apps.reports.renderers.base import ReportResult
from apps.reports.scope import ReportScope

REGISTRY: dict[str, type['BaseReportGenerator']] = {}


def register(code: str):
    def deco(cls):
        cls.code = code
        REGISTRY[code] = cls
        return cls
    return deco


def get_generator(code: str) -> type['BaseReportGenerator'] | None:
    # Ensure generator modules are imported (and thus registered).
    import apps.reports.generators  # noqa: F401
    return REGISTRY.get(code)


class BaseReportGenerator:
    code: str = ''

    def run(self, params: dict, scope: ReportScope, user) -> ReportResult:  # pragma: no cover
        raise NotImplementedError
