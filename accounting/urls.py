from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AccountHeadViewSet, FiscalYearViewSet, AccountingPeriodViewSet,
    VoucherViewSet, PaymentRecordViewSet, BankReconciliationViewSet,
    FinancialReportViewSet
)

router = DefaultRouter()
router.register(r'accounting/chart-of-accounts', AccountHeadViewSet, basename='chart-of-accounts')
router.register(r'accounting/fiscal-years', FiscalYearViewSet, basename='fiscal-years')
router.register(r'accounting/periods', AccountingPeriodViewSet, basename='accounting-periods')
router.register(r'accounting/vouchers', VoucherViewSet, basename='accounting-vouchers')
router.register(r'accounting/payments', PaymentRecordViewSet, basename='accounting-payments')
router.register(r'accounting/bank-reconciliation', BankReconciliationViewSet, basename='bank-reconciliation')
router.register(r'accounting/reports', FinancialReportViewSet, basename='accounting-reports')

urlpatterns = [
    path('', include(router.urls)),
]
