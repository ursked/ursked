import importlib.util

from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.auth import router as auth_router
from app.api.v1.leave import router as leave_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.schedules import router as schedules_router
from app.api.v1.settings import router as settings_router
from app.api.v1.configurable_types import router as configurable_types_router
from app.api.v1.payroll import router as payroll_router
from app.api.v1.compensation import router as compensation_router
from app.api.v1.permissions import router as permissions_router
from app.api.v1.attendance import router as attendance_router
from app.api.v1.policy_rules import router as policy_rules_router
from app.api.v1.data_export import router as data_export_router
from app.api.v1.site import router as site_router
from app.api.v1.users import router as users_router
from app.api.v1.salary_enrollment import router as salary_enrollment_router
from app.api.v1.notifications import router as notifications_router

# Enterprise routes live in app/ee/, a package the Community Edition build does not
# contain. That absence IS the gate: no package, no import, no routes — there is no
# edition flag to flip and nothing to patch back on.
#
# find_spec() rather than try/except ImportError on the routers themselves: a real
# broken import inside ee/ must still raise loudly, instead of silently degrading an
# Enterprise build into a Community one and nobody noticing until a customer does.
EE = importlib.util.find_spec("app.ee") is not None
if EE:
    from app.ee.api.superadmin import router as superadmin_router
    from app.ee.api.tenants import router as tenants_router

api_router = APIRouter()

api_router.include_router(site_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(schedules_router)
api_router.include_router(leave_router)
api_router.include_router(organizations_router)
api_router.include_router(analytics_router)
api_router.include_router(settings_router)
api_router.include_router(configurable_types_router)
api_router.include_router(payroll_router)
api_router.include_router(compensation_router)
api_router.include_router(permissions_router)
api_router.include_router(attendance_router)
api_router.include_router(policy_rules_router)
api_router.include_router(data_export_router)
api_router.include_router(salary_enrollment_router)
api_router.include_router(notifications_router)

if EE:
    api_router.include_router(tenants_router)
    api_router.include_router(superadmin_router)
