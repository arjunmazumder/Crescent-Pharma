from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CustomTokenObtainPairView, CustomTokenRefreshView,
    UserViewSet, LookupViewSet, RoleViewSet, PermissionViewSet,
    AttendanceViewSet, PayrollViewSet, LoanViewSet, TourAllowanceViewSet,
    HolidayViewSet, WeekendConfigViewSet,
    OfficeLocationViewSet, SalaryStructureViewSet, PayrollApprovalViewSet,
    LeaveRequestViewSet,
    CategoryViewSet, AttributeViewSet, AttributeValueViewSet,
    ProductViewSet, WarehouseViewSet, StockLevelViewSet, StockMovementViewSet
)

router = DefaultRouter()
router.register(r'employees', UserViewSet)
router.register(r'core/lookups', LookupViewSet, basename='lookups')
router.register(r'core/roles', RoleViewSet, basename='roles')
router.register(r'core/permissions', PermissionViewSet, basename='permissions')
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

# Products & Inventory routes
router.register(r'categories', CategoryViewSet, basename='categories')
router.register(r'attributes', AttributeViewSet, basename='attributes')
router.register(r'attribute-values', AttributeValueViewSet, basename='attributevalues')
router.register(r'products', ProductViewSet, basename='products')
router.register(r'warehouses', WarehouseViewSet, basename='warehouses')
router.register(r'stock-levels', StockLevelViewSet, basename='stocklevels')
router.register(r'stock-movements', StockMovementViewSet, basename='stockmovements')

urlpatterns = [
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('', include(router.urls)),
]
