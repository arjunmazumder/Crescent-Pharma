from django.urls import path, include
from rest_framework.routers import DefaultRouter
from hr.views import (
    AttendanceViewSet, PayrollViewSet, LoanViewSet, TourAllowanceViewSet,
    HolidayViewSet, WeekendConfigViewSet,
    OfficeLocationViewSet, SalaryStructureViewSet, PayrollApprovalViewSet,
    LeaveRequestViewSet
)

router = DefaultRouter()
router.register(r'attendance', AttendanceViewSet, basename='attendance')
router.register(r'leave-requests', LeaveRequestViewSet, basename='leaverequests')
router.register(r'payroll', PayrollViewSet, basename='payroll')
router.register(r'loans', LoanViewSet, basename='loans')
router.register(r'tour-allowance', TourAllowanceViewSet, basename='tourallowance')
router.register(r'holidays', HolidayViewSet, basename='holidays')
router.register(r'weekend-configs', WeekendConfigViewSet, basename='weekendconfigs')
router.register(r'office-locations', OfficeLocationViewSet, basename='officelocations')
router.register(r'salary-structures', SalaryStructureViewSet, basename='salarystructures')
router.register(r'payroll-approvals', PayrollApprovalViewSet, basename='payrollapprovals')

urlpatterns = [
    path('', include(router.urls)),
]
