from django.urls import path, include
from rest_framework.routers import DefaultRouter
from hr.views import (
    AttendanceViewSet, PayrollViewSet, LoanViewSet, TourAllowanceViewSet,
    HolidayViewSet, WeekendConfigViewSet,
    OfficeLocationViewSet, SalaryStructureViewSet, PayrollApprovalViewSet,
    LeaveRequestViewSet, TrackingViewSet,
    TAComponentViewSet, EmployeeTARateViewSet, AllowanceBillViewSet,
    BonusTypeViewSet
)

router = DefaultRouter()
router.register(r'attendance', AttendanceViewSet, basename='attendance')
router.register(r'tracking', TrackingViewSet, basename='tracking')
router.register(r'leave-requests', LeaveRequestViewSet, basename='leaverequests')
router.register(r'payroll', PayrollViewSet, basename='payroll')
router.register(r'loans', LoanViewSet, basename='loans')
router.register(r'tour-allowance', TourAllowanceViewSet, basename='tourallowance')
router.register(r'holidays', HolidayViewSet, basename='holidays')
router.register(r'weekend-configs', WeekendConfigViewSet, basename='weekendconfigs')
router.register(r'office-locations', OfficeLocationViewSet, basename='officelocations')
router.register(r'salary-structures', SalaryStructureViewSet, basename='salarystructures')
router.register(r'payroll-approvals', PayrollApprovalViewSet, basename='payrollapprovals')
router.register(r'ta-components', TAComponentViewSet, basename='tacomponents')
router.register(r'employee-ta-rates', EmployeeTARateViewSet, basename='employeetarates')
router.register(r'allowance-bills', AllowanceBillViewSet, basename='allowancebills')
router.register(r'bonus-types', BonusTypeViewSet, basename='bonustypes')

urlpatterns = [
    path('', include(router.urls)),
]
