"""Importing this package registers every generator with the registry."""
from apps.reports.generators import (  # noqa: F401
    compliance,
    incentive,
    master,
    sales,
    targets,
)
