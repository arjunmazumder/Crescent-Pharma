import datetime
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.management import call_command

from accounting.models import (
    AccountHead, AccountType, FiscalYear, AccountingPeriod,
    Voucher, VoucherType, VoucherStatus, JournalEntry,
    PaymentRecord, BankReconciliation, PartyType
)
from accounting.services import (
    VoucherPostingService, AccountingIntegrationService,
    FinancialReportEngine
)
from sales.models import Customer, CustomerOrder, CustomerOrderItem, OrderStatus, PaymentStatus
from hr.models import Payroll, SalaryStructure, Role
from inventory.models import Product, Category, Warehouse

User = get_user_model()


class AccountingModuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='accountant_admin',
            email='accountant@crescentpharma.com',
            password='Password123!',
            is_staff=True,
            is_superuser=True
        )

        # Seed standard chart of accounts & fiscal year
        call_command('seed_chart_of_accounts')

        self.cash_acc = AccountHead.objects.get(code='1111')
        self.bank_acc = AccountHead.objects.get(code='1112')
        self.ar_acc = AccountHead.objects.get(code='1120')
        self.sales_acc = AccountHead.objects.get(code='4100')
        self.vat_acc = AccountHead.objects.get(code='2150')
        self.discount_acc = AccountHead.objects.get(code='5200')
        self.salary_exp_acc = AccountHead.objects.get(code='6100')
        self.loan_rec_acc = AccountHead.objects.get(code='1130')

    def test_seed_chart_of_accounts_and_fiscal_year(self):
        """Verifies that all 5 standard categories are seeded with correct parent-child relationships."""
        self.assertTrue(AccountHead.objects.filter(code='1000', account_type=AccountType.ASSET, is_group=True).exists())
        self.assertTrue(AccountHead.objects.filter(code='2000', account_type=AccountType.LIABILITY, is_group=True).exists())
        self.assertTrue(AccountHead.objects.filter(code='3000', account_type=AccountType.EQUITY, is_group=True).exists())
        self.assertTrue(AccountHead.objects.filter(code='4000', account_type=AccountType.REVENUE, is_group=True).exists())
        self.assertTrue(AccountHead.objects.filter(code='5000', account_type=AccountType.EXPENSE, is_group=True).exists())
        self.assertTrue(AccountHead.objects.filter(code='6000', account_type=AccountType.EXPENSE, is_group=True).exists())

        # Check Fiscal Year & Periods
        fy = FiscalYear.objects.filter(code='FY26-27').first()
        self.assertIsNotNone(fy)
        self.assertEqual(fy.periods.count(), 12)

    def test_double_entry_unbalanced_voucher_rejection(self):
        """Validates that any unbalanced voucher (Dr != Cr) is atomically rejected."""
        today = datetime.date(2026, 8, 20)
        unbalanced_entries = [
            {'account_id': self.cash_acc.id, 'debit_amount': Decimal('5000.00')},
            {'account_id': self.sales_acc.id, 'credit_amount': Decimal('4000.00')}  # Difference of 1000
        ]

        with self.assertRaises(ValueError) as ctx:
            VoucherPostingService.create_and_post_voucher(
                voucher_type=VoucherType.JOURNAL,
                voucher_date=today,
                narration="Test Unbalanced Voucher",
                entries_data=unbalanced_entries,
                user=self.user
            )

        self.assertIn("Double-entry equation violated", str(ctx.exception))
        self.assertFalse(Voucher.objects.filter(narration="Test Unbalanced Voucher").exists())

    def test_manual_voucher_creation_and_reversal(self):
        """Tests posting a balanced manual Journal Voucher and reversing it."""
        today = datetime.date(2026, 8, 20)
        entries = [
            {'account_id': self.cash_acc.id, 'debit_amount': Decimal('10000.00'), 'description': 'Deposit Cash'},
            {'account_id': self.sales_acc.id, 'credit_amount': Decimal('10000.00'), 'description': 'OTC Sales'}
        ]

        voucher = VoucherPostingService.create_and_post_voucher(
            voucher_type=VoucherType.RECEIPT,
            voucher_date=today,
            narration="Daily OTC Cash Sales",
            entries_data=entries,
            user=self.user
        )

        self.assertEqual(voucher.status, VoucherStatus.POSTED)
        self.assertEqual(voucher.total_debit, Decimal('10000.00'))
        self.assertEqual(voucher.total_credit, Decimal('10000.00'))
        self.assertEqual(voucher.entries.count(), 2)

        # Test Reversal
        rev_voucher = VoucherPostingService.reverse_voucher(
            voucher=voucher,
            reason="Incorrect OTC category recorded",
            user=self.user
        )

        voucher.refresh_from_db()
        self.assertTrue(voucher.is_reversed)
        self.assertEqual(rev_voucher.reversal_of, voucher)
        self.assertEqual(rev_voucher.total_debit, Decimal('10000.00'))

        # Check that GL balance after reversal is 0.00
        gl_cash = FinancialReportEngine.get_general_ledger(self.cash_acc.id)
        self.assertEqual(gl_cash['closingBalance'], '0.00')

    def test_sales_order_auto_posting(self):
        """Tests that fulfilling a sales order automatically creates an accurate Sales Invoice Voucher."""
        customer = Customer.objects.create(
            name='Popular Pharmacy Gulshan',
            phone='01700000001',
            drug_license_no='DL-12345',
            drug_license_expiry_date=datetime.date(2028, 1, 1)
        )
        cat = Category.objects.create(name='Antibiotics')
        prod = Product.objects.create(
            name='Cresclav 625',
            generic_name='Amoxicillin + Clavulanic Acid',
            category=cat,
            purchase_price=Decimal('100.00'),
            selling_price=Decimal('150.00'),
            vat_percentage=Decimal('15.00')
        )
        wh = Warehouse.objects.create(name='Central Warehouse Dhaka', code='WH-DHK')

        order = CustomerOrder.objects.create(
            customer=customer,
            order_date=datetime.date(2026, 8, 20),
            delivery_date=datetime.date(2026, 8, 20),
            subtotal=Decimal('15000.00'),
            discount_flat=Decimal('500.00'),
            tax_amount=Decimal('2175.00'),
            total_amount=Decimal('16675.00'),
            status=OrderStatus.DELIVERED
        )

        voucher = AccountingIntegrationService.post_sales_order_delivery(order=order, user=self.user)

        self.assertIsNotNone(voucher)
        self.assertEqual(voucher.voucher_type, VoucherType.SALES_INVOICE)
        self.assertEqual(voucher.status, VoucherStatus.POSTED)
        self.assertEqual(voucher.total_debit, Decimal('17175.00'))  # Net 16,675 + Discount 500
        self.assertEqual(voucher.total_credit, Decimal('17175.00'))  # Subtotal 15,000 + VAT 2,175

        # Check GL for Accounts Receivable
        gl_ar = FinancialReportEngine.get_general_ledger(self.ar_acc.id)
        self.assertEqual(gl_ar['closingBalance'], '16675.00')

    def test_customer_payment_collection_reconciliation(self):
        """Tests customer payment collection and auto-reconciliation of order balance."""
        customer = Customer.objects.create(name='Labaid Hospital Pharmacy', phone='01800000002')
        order = CustomerOrder.objects.create(
            customer=customer,
            order_date=datetime.date(2026, 8, 20),
            subtotal=Decimal('10000.00'),
            total_amount=Decimal('10000.00'),
            paid_amount=Decimal('0.00'),
            payment_status=PaymentStatus.UNPAID,
            status=OrderStatus.DELIVERED
        )

        # Post delivery first
        AccountingIntegrationService.post_sales_order_delivery(order=order, user=self.user)

        # Customer pays 6,000 partial payment
        payment_rec, voucher = AccountingIntegrationService.post_customer_payment(
            order=order,
            amount=Decimal('6000.00'),
            payment_method='MFS_BKASH',
            deposit_account=self.cash_acc,
            reference_no='BKASH-TRX-998877',
            user=self.user
        )

        order.refresh_from_db()
        self.assertEqual(order.paid_amount, Decimal('6000.00'))
        self.assertEqual(order.payment_status, PaymentStatus.PARTIAL)
        self.assertEqual(payment_rec.amount, Decimal('6000.00'))

        # Remaining AR balance should now be 4,000
        gl_ar = FinancialReportEngine.get_general_ledger(self.ar_acc.id)
        self.assertEqual(gl_ar['closingBalance'], '4000.00')

        # Pay remaining 4,000
        AccountingIntegrationService.post_customer_payment(
            order=order,
            amount=Decimal('4000.00'),
            payment_method='CASH',
            deposit_account=self.cash_acc,
            user=self.user
        )

        order.refresh_from_db()
        self.assertEqual(order.paid_amount, Decimal('10000.00'))
        self.assertEqual(order.payment_status, PaymentStatus.PAID)

        # AR balance should now be 0.00
        gl_ar_after = FinancialReportEngine.get_general_ledger(self.ar_acc.id)
        self.assertEqual(gl_ar_after['closingBalance'], '0.00')

    def test_payroll_auto_posting(self):
        """Tests that disbursed payroll posts proper debits to salary expense and credits to bank/loan."""
        emp = User.objects.create_user(username='mpo_rakib', email='rakib@crescent.com', password='Pass123')
        role = Role.objects.create(role_name='Field Marketing Officer')

        payroll = Payroll.objects.create(
            user=emp,
            month=8,
            year=2026,
            base_salary=Decimal('30000.00'),
            housing_allowance=Decimal('10000.00'),
            transport_allowance=Decimal('5000.00'),
            medical_benefits=Decimal('3000.00'),
            utility_allowance=Decimal('2000.00'),
            total_ta_allowance=Decimal('4000.00'),
            total_tour_allowance=Decimal('6000.00'),
            per_day_salary=Decimal('1200.00'),
            per_hour_salary=Decimal('150.00'),
            loan_deduction=Decimal('5000.00'),
            unpaid_deduction=Decimal('0.00'),
            amount=Decimal('55000.00'),  # 30k + 20k allowances + 10k TA/Tour - 5k loan = 55k
            status='PAID'
        )

        voucher = AccountingIntegrationService.post_payroll_disbursement(payroll=payroll, user=self.user)

        self.assertIsNotNone(voucher)
        self.assertEqual(voucher.voucher_type, VoucherType.PAYROLL)
        self.assertEqual(voucher.total_debit, Decimal('60000.00'))   # 30k base + 20k allow + 10k tour
        self.assertEqual(voucher.total_credit, Decimal('60000.00'))  # 55k net bank + 5k loan recovery

    def test_trial_balance_and_balance_sheet_integrity(self):
        """Verifies that Trial Balance is balanced (difference=0.00) and Balance Sheet holds true."""
        today = datetime.date(2026, 8, 20)
        
        # Post initial capital
        capital_acc = AccountHead.objects.get(code='3100')
        entries = [
            {'account_id': self.bank_acc.id, 'debit_amount': Decimal('500000.00')},
            {'account_id': capital_acc.id, 'credit_amount': Decimal('500000.00')}
        ]
        VoucherPostingService.create_and_post_voucher(
            voucher_type=VoucherType.RECEIPT,
            voucher_date=today,
            narration="Initial Share Capital Deposit",
            entries_data=entries,
            user=self.user
        )

        tb = FinancialReportEngine.get_trial_balance(as_of_date=today)
        self.assertTrue(tb['isBalanced'])
        self.assertEqual(tb['difference'], '0.00')

        bs = FinancialReportEngine.get_balance_sheet(as_of_date=today)
        self.assertTrue(bs['isBalanced'])
        self.assertEqual(bs['equationDifference'], '0.00')
        self.assertEqual(bs['totalAssets'], '500000.00')
        self.assertEqual(bs['totalEquity'], '500000.00')

    def test_locked_accounting_period_prevents_postings(self):
        """Validates that a locked Accounting Period strictly blocks any back-dated postings."""
        period_july = AccountingPeriod.objects.filter(name__icontains='July 2026').first()
        self.assertIsNotNone(period_july)

        # Lock July period
        period_july.is_locked = True
        period_july.save()

        entries = [
            {'account_id': self.cash_acc.id, 'debit_amount': Decimal('1000.00')},
            {'account_id': self.sales_acc.id, 'credit_amount': Decimal('1000.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            VoucherPostingService.create_and_post_voucher(
                voucher_type=VoucherType.RECEIPT,
                voucher_date=datetime.date(2026, 7, 15),  # Inside locked July
                narration="Back-dated transaction attempt",
                entries_data=entries,
                user=self.user
            )

        self.assertIn("is locked", str(ctx.exception))

    def test_auto_generate_monthly_periods_on_fiscal_year_creation(self):
        """Validates that creating a new Fiscal Year automatically generates all 12 monthly Accounting Periods."""
        new_fy = FiscalYear.objects.create(
            name="FY 2027-2028 Test",
            code="FY27-28-TEST",
            start_date=datetime.date(2027, 7, 1),
            end_date=datetime.date(2028, 6, 30)
        )
        self.assertEqual(new_fy.periods.count(), 12)
        p1 = new_fy.periods.get(period_number=1)
        self.assertEqual(p1.name, "July 2027")
        self.assertEqual(p1.start_date, datetime.date(2027, 7, 1))
        self.assertEqual(p1.end_date, datetime.date(2027, 7, 31))

        p12 = new_fy.periods.get(period_number=12)
        self.assertEqual(p12.name, "June 2028")
        self.assertEqual(p12.start_date, datetime.date(2028, 6, 1))
        self.assertEqual(p12.end_date, datetime.date(2028, 6, 30))

    def test_auto_calculate_end_date_and_periods_calendar_year(self):
        """Validates calendar year auto-calculation: providing only start_date calculates end_date and generates periods."""
        cal_fy = FiscalYear.objects.create(
            name="FY 2029 Calendar Year",
            code="FY2029",
            start_date=datetime.date(2029, 1, 1)
            # end_date omitted!
        )
        self.assertEqual(cal_fy.end_date, datetime.date(2029, 12, 31))
        self.assertEqual(cal_fy.periods.count(), 12)
        self.assertEqual(cal_fy.periods.get(period_number=1).name, "January 2029")
        self.assertEqual(cal_fy.periods.get(period_number=12).name, "December 2029")
