from decimal import Decimal, ROUND_HALF_UP
import datetime
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import (
    AccountHead, AccountType, PartyType,
    FiscalYear, AccountingPeriod,
    Voucher, VoucherType, VoucherStatus,
    JournalEntry, PaymentRecord,
    BankReconciliation, ReconciliationStatus
)

User = get_user_model()


class VoucherPostingService:
    @staticmethod
    def validate_period_and_fiscal_year(voucher_date):
        """
        Validates that the voucher_date is not inside a locked or closed AccountingPeriod or FiscalYear.
        Returns the matching AccountingPeriod if found.
        """
        fiscal_year = FiscalYear.objects.filter(
            start_date__lte=voucher_date,
            end_date__gte=voucher_date
        ).first()

        if fiscal_year and fiscal_year.is_locked:
            raise ValueError(f"Cannot post voucher: Fiscal Year '{fiscal_year.name}' is locked.")
        if fiscal_year and fiscal_year.is_closed:
            raise ValueError(f"Cannot post voucher: Fiscal Year '{fiscal_year.name}' is closed.")

        period = AccountingPeriod.objects.filter(
            start_date__lte=voucher_date,
            end_date__gte=voucher_date
        ).first()

        if period and period.is_locked:
            raise ValueError(f"Cannot post voucher: Accounting Period '{period.name}' is locked.")
        if period and period.is_closed:
            raise ValueError(f"Cannot post voucher: Accounting Period '{period.name}' is closed.")

        return period

    @staticmethod
    def create_and_post_voucher(
        voucher_type,
        voucher_date,
        narration,
        entries_data,
        reference_no="",
        attachment_url="",
        is_auto_generated=False,
        source_module="",
        source_id=None,
        cheque_number="",
        cheque_date=None,
        cheque_status=None,
        user=None,
        auto_post=True
    ):
        """
        Atomically creates a Voucher and its JournalEntry lines.
        Enforces double-entry equality: sum(Debit) == sum(Credit) > 0.
        Checks period lock constraints and commits to General Ledger if auto_post=True.
        """
        if not entries_data or len(entries_data) < 2:
            raise ValueError("A voucher must contain at least two line entries (Debit and Credit).")

        period = VoucherPostingService.validate_period_and_fiscal_year(voucher_date)

        total_debit = Decimal('0.00')
        total_credit = Decimal('0.00')

        # First pass validation
        validated_entries = []
        for line_no, item in enumerate(entries_data, start=1):
            acc_id = item.get('account_id') or item.get('accountId')
            account = AccountHead.objects.filter(id=acc_id, is_active=True).first()
            if not account:
                raise ValueError(f"Account with ID '{acc_id}' not found or is inactive.")
            if account.is_group:
                raise ValueError(f"Cannot post to header/group account '{account.name}' ({account.code}). Select a transactional account.")

            debit = Decimal(str(item.get('debit_amount') or item.get('debitAmount') or '0.00')).quantize(Decimal('0.01'))
            credit = Decimal(str(item.get('credit_amount') or item.get('creditAmount') or '0.00')).quantize(Decimal('0.01'))

            if debit > 0 and credit > 0:
                raise ValueError(f"Line {line_no}: A single entry cannot have both Debit and Credit amounts.")
            if debit <= 0 and credit <= 0:
                raise ValueError(f"Line {line_no}: Entry must have a non-zero Debit or Credit amount.")

            total_debit += debit
            total_credit += credit

            validated_entries.append({
                'line_no': line_no,
                'account': account,
                'debit_amount': debit,
                'credit_amount': credit,
                'description': item.get('description', ''),
                'party_type': item.get('party_type') or item.get('partyType'),
                'party_id': item.get('party_id') or item.get('partyId'),
                'foreign_currency': item.get('foreign_currency') or item.get('foreignCurrency'),
                'foreign_amount': item.get('foreign_amount') or item.get('foreignAmount'),
                'exchange_rate': item.get('exchange_rate') or item.get('exchangeRate'),
                'tax_rate': item.get('tax_rate') or item.get('taxRate'),
                'tax_amount': item.get('tax_amount') or item.get('taxAmount'),
                'cost_center': item.get('cost_center') or item.get('costCenter'),
                'product_id': item.get('product_id') or item.get('productId')
            })

        # Double-entry balance check
        if total_debit != total_credit:
            raise ValueError(
                f"Double-entry equation violated! Total Debits ({total_debit}) does not equal Total Credits ({total_credit}). "
                f"Difference: {abs(total_debit - total_credit)}."
            )
        if total_debit <= Decimal('0.00'):
            raise ValueError("Voucher total amount must be greater than zero.")

        with transaction.atomic():
            voucher = Voucher(
                voucher_type=voucher_type,
                voucher_date=voucher_date,
                period=period,
                reference_no=reference_no or "",
                narration=narration or "",
                total_debit=total_debit,
                total_credit=total_credit,
                attachment_url=attachment_url or "",
                is_auto_generated=is_auto_generated,
                source_module=source_module or "",
                source_id=source_id,
                cheque_number=cheque_number or "",
                cheque_date=cheque_date,
                cheque_status=cheque_status,
                status=VoucherStatus.POSTED if auto_post else VoucherStatus.DRAFT,
                created_by=user,
                posted_by=user if auto_post else None,
                posted_at=timezone.now() if auto_post else None
            )
            voucher.save()

            for entry in validated_entries:
                JournalEntry.objects.create(
                    voucher=voucher,
                    line_no=entry['line_no'],
                    account=entry['account'],
                    debit_amount=entry['debit_amount'],
                    credit_amount=entry['credit_amount'],
                    description=entry['description'] or "",
                    party_type=entry['party_type'],
                    party_id=entry['party_id'],
                    foreign_currency=entry['foreign_currency'],
                    foreign_amount=entry['foreign_amount'],
                    exchange_rate=entry['exchange_rate'],
                    tax_rate=entry['tax_rate'],
                    tax_amount=entry['tax_amount'],
                    cost_center=entry['cost_center'] or "",
                    product_id=entry['product_id']
                )

        return voucher

    @staticmethod
    def reverse_voucher(voucher, reason, user=None):
        """
        Creates a matching Reversal Voucher where Debits become Credits and Credits become Debits.
        Marks the original voucher as is_reversed = True.
        """
        if voucher.status != VoucherStatus.POSTED:
            raise ValueError(f"Only POSTED vouchers can be reversed. Current status is '{voucher.status}'.")
        if voucher.is_reversed:
            raise ValueError(f"Voucher '{voucher.voucher_number}' has already been reversed.")
        if not reason:
            raise ValueError("A reversal reason is mandatory.")

        today = timezone.now().date()
        period = VoucherPostingService.validate_period_and_fiscal_year(today)

        with transaction.atomic():
            rev_voucher = Voucher(
                voucher_type=VoucherType.JOURNAL,
                voucher_date=today,
                period=period,
                reference_no=f"REV-{voucher.voucher_number}",
                narration=f"Reversal of {voucher.voucher_number}. Reason: {reason}",
                total_debit=voucher.total_credit,
                total_credit=voucher.total_debit,
                is_auto_generated=True,
                source_module='ACCOUNTING_REVERSAL',
                source_id=voucher.id,
                reversal_of=voucher,
                status=VoucherStatus.POSTED,
                created_by=user,
                posted_by=user,
                posted_at=timezone.now()
            )
            rev_voucher.save()

            for entry in voucher.entries.all():
                JournalEntry.objects.create(
                    voucher=rev_voucher,
                    line_no=entry.line_no,
                    account=entry.account,
                    debit_amount=entry.credit_amount,
                    credit_amount=entry.debit_amount,
                    description=f"Reversal of Line {entry.line_no}: {entry.description or ''}".strip(),
                    party_type=entry.party_type,
                    party_id=entry.party_id,
                    cost_center=entry.cost_center,
                    product=entry.product
                )

            voucher.is_reversed = True
            voucher.save(update_fields=['is_reversed'])

        return rev_voucher


class AccountingIntegrationService:
    @staticmethod
    def get_or_create_head(code, name, account_type, is_reconciliation=False, is_group=False, parent=None):
        """
        Helper method to guarantee that standard Chart of Accounts heads exist.
        """
        head, _ = AccountHead.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'account_type': account_type,
                'is_reconciliation': is_reconciliation,
                'is_group': is_group,
                'parent': parent,
                'is_system_locked': True
            }
        )
        return head

    @staticmethod
    def post_sales_order_delivery(order, user=None):
        """
        Automatically posts accounting ledger entries when a CustomerOrder is DELIVERED.
        - Debit: Accounts Receivable (1120) [Net Total Amount]
        - Debit: Sales Discount Expense (5200) [If discount applied]
        - Credit: Pharma Sales Revenue (4100) [Subtotal]
        - Credit: Output VAT Payable (2150) [Tax Amount]
        """
        ar_account = AccountingIntegrationService.get_or_create_head(
            '1120', 'Accounts Receivable (Trade Debtors)', AccountType.ASSET
        )
        sales_account = AccountingIntegrationService.get_or_create_head(
            '4100', 'Pharmaceutical Sales Revenue', AccountType.REVENUE
        )
        vat_account = AccountingIntegrationService.get_or_create_head(
            '2150', 'Output VAT Payable (Govt Tax)', AccountType.LIABILITY
        )
        discount_account = AccountingIntegrationService.get_or_create_head(
            '5200', 'Sales Discounts & Rebates', AccountType.EXPENSE
        )

        subtotal = Decimal(str(order.subtotal or '0.00')).quantize(Decimal('0.01'))
        tax_amount = Decimal(str(order.tax_amount or '0.00')).quantize(Decimal('0.01'))
        net_total = Decimal(str(order.total_amount or '0.00')).quantize(Decimal('0.01'))
        
        # Calculate discount given
        discount_amount = max(Decimal('0.00'), (subtotal + tax_amount) - net_total).quantize(Decimal('0.01'))

        entries = []
        # 1. Debit Accounts Receivable
        entries.append({
            'account_id': ar_account.id,
            'debit_amount': net_total,
            'credit_amount': Decimal('0.00'),
            'description': f"Sales Receivable for {order.customer.name} (Order: {order.order_number})",
            'party_type': PartyType.CUSTOMER,
            'party_id': order.customer_id
        })

        # 2. Debit Sales Discount (if any)
        if discount_amount > 0:
            entries.append({
                'account_id': discount_account.id,
                'debit_amount': discount_amount,
                'credit_amount': Decimal('0.00'),
                'description': f"Discount granted on Order {order.order_number}"
            })

        # 3. Credit Pharma Sales Revenue
        entries.append({
            'account_id': sales_account.id,
            'debit_amount': Decimal('0.00'),
            'credit_amount': subtotal,
            'description': f"Sales fulfillment of Order {order.order_number}"
        })

        # 4. Credit Output VAT Payable (if any)
        if tax_amount > 0:
            entries.append({
                'account_id': vat_account.id,
                'debit_amount': Decimal('0.00'),
                'credit_amount': tax_amount,
                'description': f"Output VAT on Order {order.order_number}"
            })

        voucher = VoucherPostingService.create_and_post_voucher(
            voucher_type=VoucherType.SALES_INVOICE,
            voucher_date=order.delivery_date or timezone.now().date(),
            narration=f"Sales Order Delivery Fulfillment for {order.customer.name} ({order.order_number})",
            entries_data=entries,
            reference_no=order.order_number,
            is_auto_generated=True,
            source_module='SALES',
            source_id=order.id,
            user=user,
            auto_post=True
        )

        return voucher

    @staticmethod
    def post_customer_payment(
        order,
        amount,
        payment_method,
        deposit_account,
        reference_no="",
        notes="",
        user=None
    ):
        """
        Records customer collection via PaymentRecord and posts double-entry Receipt Voucher:
        - Debit: Cash in Hand (1111) or Bank Account (1112)
        - Credit: Accounts Receivable (1120)
        Automatically updates CustomerOrder.paid_amount and payment_status.
        """
        amount = Decimal(str(amount)).quantize(Decimal('0.01'))
        if amount <= Decimal('0.00'):
            raise ValueError("Payment amount must be greater than zero.")

        ar_account = AccountingIntegrationService.get_or_create_head(
            '1120', 'Accounts Receivable (Trade Debtors)', AccountType.ASSET
        )

        today = timezone.now().date()

        with transaction.atomic():
            # Create double-entry receipt voucher
            entries = [
                {
                    'account_id': deposit_account.id,
                    'debit_amount': amount,
                    'credit_amount': Decimal('0.00'),
                    'description': f"Payment Collection ({payment_method}) from {order.customer.name} (Order: {order.order_number})",
                    'party_type': PartyType.CUSTOMER,
                    'party_id': order.customer_id
                },
                {
                    'account_id': ar_account.id,
                    'debit_amount': Decimal('0.00'),
                    'credit_amount': amount,
                    'description': f"Settlement of Receivable for Order {order.order_number}",
                    'party_type': PartyType.CUSTOMER,
                    'party_id': order.customer_id
                }
            ]

            voucher = VoucherPostingService.create_and_post_voucher(
                voucher_type=VoucherType.RECEIPT,
                voucher_date=today,
                narration=f"Customer Collection from {order.customer.name} (Order: {order.order_number}, Ref: {reference_no or 'N/A'})",
                entries_data=entries,
                reference_no=reference_no or order.order_number,
                is_auto_generated=True,
                source_module='SALES_PAYMENT',
                source_id=order.id,
                user=user,
                auto_post=True
            )

            payment_record = PaymentRecord.objects.create(
                payment_type='RECEIPT',
                party_type=PartyType.CUSTOMER,
                party_id=order.customer_id,
                order=order,
                payment_date=today,
                amount=amount,
                payment_method=payment_method,
                deposit_to_account=deposit_account,
                voucher=voucher,
                reference_no=reference_no,
                notes=notes,
                created_by=user
            )

            # Update Order Paid Amount & Payment Status
            order.paid_amount = (Decimal(str(order.paid_amount or '0.00')) + amount).quantize(Decimal('0.01'))
            if order.paid_amount >= order.total_amount:
                order.payment_status = 'PAID'
            elif order.paid_amount > Decimal('0.00'):
                order.payment_status = 'PARTIAL'
            order.save(update_fields=['paid_amount', 'payment_status'])

        return payment_record, voucher

    @staticmethod
    def post_payroll_disbursement(payroll, user=None):
        """
        Automatically posts accounting ledger entries when Payroll is disbursed/approved:
        - Debit: Basic Salary Expense (6100)
        - Debit: Housing & Medical Allowances Expense (6110)
        - Debit: Daily TA & Tour Expense (6120)
        - Credit: Employee Loan Recoveries (1130) [If loan deducted]
        - Credit: Salaries Payable / Bank Account (2120 / 1112) [Net Payable]
        """
        salary_exp = AccountingIntegrationService.get_or_create_head(
            '6100', 'Employee Basic Salaries', AccountType.EXPENSE
        )
        allowance_exp = AccountingIntegrationService.get_or_create_head(
            '6110', 'Housing, Transport & Medical Allowances', AccountType.EXPENSE
        )
        ta_tour_exp = AccountingIntegrationService.get_or_create_head(
            '6120', 'Travel & Tour Allowances (TA/DA)', AccountType.EXPENSE
        )
        loan_rec = AccountingIntegrationService.get_or_create_head(
            '1130', 'Employee Advances & Loans Receivable', AccountType.ASSET
        )
        bank_payable = AccountingIntegrationService.get_or_create_head(
            '1112', 'Bank Current Accounts (Corporate Disbursement)', AccountType.ASSET, is_reconciliation=True
        )

        base_salary = Decimal(str(payroll.base_salary or '0.00')).quantize(Decimal('0.01'))
        allowances = (
            Decimal(str(payroll.housing_allowance or '0.00')) +
            Decimal(str(payroll.transport_allowance or '0.00')) +
            Decimal(str(payroll.medical_benefits or '0.00')) +
            Decimal(str(payroll.utility_allowance or '0.00'))
        ).quantize(Decimal('0.01'))
        ta_tour = (
            Decimal(str(payroll.total_ta_allowance or '0.00')) +
            Decimal(str(payroll.total_tour_allowance or '0.00'))
        ).quantize(Decimal('0.01'))
        
        loan_ded = Decimal(str(payroll.loan_deduction or '0.00')).quantize(Decimal('0.01'))
        unpaid_ded = Decimal(str(payroll.unpaid_deduction or '0.00')).quantize(Decimal('0.01'))
        net_payable = Decimal(str(payroll.amount or '0.00')).quantize(Decimal('0.01'))

        entries = []
        # Debits
        adjusted_base = max(Decimal('0.00'), base_salary - unpaid_ded)
        if adjusted_base > 0:
            entries.append({
                'account_id': salary_exp.id,
                'debit_amount': adjusted_base,
                'credit_amount': Decimal('0.00'),
                'description': f"Basic Salary for {payroll.user.username} ({payroll.month}/{payroll.year})",
                'party_type': PartyType.EMPLOYEE,
                'party_id': payroll.user_id
            })

        if allowances > 0:
            entries.append({
                'account_id': allowance_exp.id,
                'debit_amount': allowances,
                'credit_amount': Decimal('0.00'),
                'description': f"Allowances for {payroll.user.username} ({payroll.month}/{payroll.year})"
            })

        if ta_tour > 0:
            entries.append({
                'account_id': ta_tour_exp.id,
                'debit_amount': ta_tour,
                'credit_amount': Decimal('0.00'),
                'description': f"TA & Tour Expenses for {payroll.user.username} ({payroll.month}/{payroll.year})"
            })

        # Credits
        if loan_ded > 0:
            entries.append({
                'account_id': loan_rec.id,
                'debit_amount': Decimal('0.00'),
                'credit_amount': loan_ded,
                'description': f"Loan EMI deduction for {payroll.user.username}",
                'party_type': PartyType.EMPLOYEE,
                'party_id': payroll.user_id
            })

        entries.append({
            'account_id': bank_payable.id,
            'debit_amount': Decimal('0.00'),
            'credit_amount': net_payable,
            'description': f"Net Salary Disbursement to {payroll.user.username} ({payroll.month}/{payroll.year})",
            'party_type': PartyType.EMPLOYEE,
            'party_id': payroll.user_id
        })

        voucher = VoucherPostingService.create_and_post_voucher(
            voucher_type=VoucherType.PAYROLL,
            voucher_date=timezone.now().date(),
            narration=f"Monthly Payroll Disbursement for {payroll.user.username} ({payroll.month}/{payroll.year})",
            entries_data=entries,
            reference_no=f"PAY-{payroll.year}-{payroll.month:02d}-{payroll.user_id}",
            is_auto_generated=True,
            source_module='PAYROLL',
            source_id=payroll.id,
            user=user,
            auto_post=True
        )

        return voucher

    @staticmethod
    def post_inventory_damage_loss(product, warehouse, batch_number, quantity, financial_loss, reference_no="", notes="", user=None):
        """
        Automatically posts accounting loss when damaged or expired inventory is written off:
        - Debit: Damaged & Expired Stock Loss (5300)
        - Credit: Finished Goods Inventory Asset (1140)
        """
        financial_loss = Decimal(str(financial_loss)).quantize(Decimal('0.01'))
        if financial_loss <= Decimal('0.00'):
            return None

        loss_account = AccountingIntegrationService.get_or_create_head(
            '5300', 'Damaged & Expired Medicines Loss', AccountType.EXPENSE
        )
        inventory_account = AccountingIntegrationService.get_or_create_head(
            '1140', 'Finished Goods Inventory Stock', AccountType.ASSET
        )

        today = timezone.now().date()

        entries = [
            {
                'account_id': loss_account.id,
                'debit_amount': financial_loss,
                'credit_amount': Decimal('0.00'),
                'description': f"Damage write-off: {product.name} ({quantity} units, Batch: {batch_number}) @ {warehouse.name}",
                'product_id': product.id
            },
            {
                'account_id': inventory_account.id,
                'debit_amount': Decimal('0.00'),
                'credit_amount': financial_loss,
                'description': f"Inventory reduction for damaged stock ({product.name})"
            }
        ]

        voucher = VoucherPostingService.create_and_post_voucher(
            voucher_type=VoucherType.JOURNAL,
            voucher_date=today,
            narration=f"Damaged Inventory Write-off: {product.name} ({quantity} units, Ref: {reference_no or 'N/A'}) - {notes or ''}",
            entries_data=entries,
            reference_no=reference_no,
            is_auto_generated=True,
            source_module='INVENTORY_DAMAGE',
            source_id=product.id,
            user=user,
            auto_post=True
        )

        return voucher


class FinancialReportEngine:
    @staticmethod
    def get_general_ledger(account_id, start_date=None, end_date=None, party_type=None, party_id=None):
        """
        Computes General Ledger Statement for a specific AccountHead:
        - Opening Balance (accumulated prior to start_date)
        - Line-by-line Journal Entries
        - Running Balance
        - Closing Balance
        """
        account = AccountHead.objects.get(id=account_id)
        
        # Base entries query
        base_qs = JournalEntry.objects.filter(
            account=account,
            voucher__status=VoucherStatus.POSTED
        )

        if party_type:
            base_qs = base_qs.filter(party_type=party_type)
        if party_id:
            base_qs = base_qs.filter(party_id=party_id)

        # 1. Opening Balance
        opening_debit = Decimal('0.00')
        opening_credit = Decimal('0.00')

        if start_date:
            prior_entries = base_qs.filter(voucher__voucher_date__lt=start_date)
            prior_agg = prior_entries.aggregate(
                total_dr=Sum('debit_amount'),
                total_cr=Sum('credit_amount')
            )
            opening_debit = prior_agg['total_dr'] or Decimal('0.00')
            opening_credit = prior_agg['total_cr'] or Decimal('0.00')

        # Determine nature of account (Assets/Expenses = Debit nature; Liabilities/Equity/Revenue = Credit nature)
        is_debit_nature = account.account_type in [AccountType.ASSET, AccountType.EXPENSE]
        if is_debit_nature:
            opening_balance = (opening_debit - opening_credit).quantize(Decimal('0.01'))
        else:
            opening_balance = (opening_credit - opening_debit).quantize(Decimal('0.01'))

        # 2. Current Period Entries
        current_qs = base_qs.select_related('voucher').order_by('voucher__voucher_date', 'voucher__id', 'line_no')
        if start_date:
            current_qs = current_qs.filter(voucher__voucher_date__gte=start_date)
        if end_date:
            current_qs = current_qs.filter(voucher__voucher_date__lte=end_date)

        running_balance = opening_balance
        statement_entries = []
        total_period_debit = Decimal('0.00')
        total_period_credit = Decimal('0.00')

        for entry in current_qs:
            dr = entry.debit_amount
            cr = entry.credit_amount
            total_period_debit += dr
            total_period_credit += cr

            if is_debit_nature:
                running_balance += (dr - cr)
            else:
                running_balance += (cr - dr)

            statement_entries.append({
                'entryId': entry.id,
                'voucherId': entry.voucher_id,
                'voucherNumber': entry.voucher.voucher_number,
                'voucherType': entry.voucher.voucher_type,
                'voucherDate': entry.voucher.voucher_date.isoformat(),
                'referenceNo': entry.voucher.reference_no,
                'narration': entry.voucher.narration,
                'lineDescription': entry.description,
                'partyType': entry.party_type,
                'partyId': entry.party_id,
                'debitAmount': str(dr),
                'creditAmount': str(cr),
                'runningBalance': str(running_balance.quantize(Decimal('0.01')))
            })

        return {
            'accountId': account.id,
            'accountCode': account.code,
            'accountName': account.name,
            'accountType': account.account_type,
            'currency': account.currency,
            'startDate': str(start_date) if start_date else None,
            'endDate': str(end_date) if end_date else None,
            'openingBalance': str(opening_balance),
            'totalPeriodDebit': str(total_period_debit.quantize(Decimal('0.01'))),
            'totalPeriodCredit': str(total_period_credit.quantize(Decimal('0.01'))),
            'closingBalance': str(running_balance.quantize(Decimal('0.01'))),
            'entriesCount': len(statement_entries),
            'entries': statement_entries
        }

    @staticmethod
    def get_cash_and_bank_book(start_date=None, end_date=None):
        """
        Specialized report for all liquid Cash and Bank accounts.
        """
        liquid_accounts = AccountHead.objects.filter(
            Q(is_reconciliation=True) | Q(code__startswith='111'),
            is_active=True,
            is_group=False
        ).order_by('code')

        accounts_data = [
            FinancialReportEngine.get_general_ledger(
                account_id=acc.id,
                start_date=start_date,
                end_date=end_date
            )
            for acc in liquid_accounts
        ]

        total_cash_and_bank = sum((Decimal(str(item['closingBalance'])) for item in accounts_data), Decimal('0.00'))

        return {
            'asOfDate': str(end_date or timezone.now().date()),
            'totalCashAndBankBalance': str(total_cash_and_bank.quantize(Decimal('0.01'))),
            'accountsCount': len(accounts_data),
            'accounts': accounts_data
        }

    @staticmethod
    def get_trial_balance(as_of_date=None):
        """
        Generates Trial Balance as of a specific date.
        Enforces and verifies: Total Debits == Total Credits (Difference = 0.00).
        """
        if not as_of_date:
            as_of_date = timezone.now().date()

        accounts = AccountHead.objects.filter(is_active=True, is_group=False).order_by('code')
        trial_entries = []
        grand_total_debit = Decimal('0.00')
        grand_total_credit = Decimal('0.00')

        for acc in accounts:
            qs = JournalEntry.objects.filter(
                account=acc,
                voucher__status=VoucherStatus.POSTED,
                voucher__voucher_date__lte=as_of_date
            )
            agg = qs.aggregate(
                tot_dr=Sum('debit_amount'),
                tot_cr=Sum('credit_amount')
            )
            tot_dr = agg['tot_dr'] or Decimal('0.00')
            tot_cr = agg['tot_cr'] or Decimal('0.00')

            if tot_dr == 0 and tot_cr == 0:
                continue

            is_debit_nature = acc.account_type in [AccountType.ASSET, AccountType.EXPENSE]
            net_balance = (tot_dr - tot_cr) if is_debit_nature else (tot_cr - tot_dr)

            # Assign to Debit or Credit column of Trial Balance
            if net_balance >= 0:
                tb_debit = net_balance if is_debit_nature else Decimal('0.00')
                tb_credit = Decimal('0.00') if is_debit_nature else net_balance
            else:
                tb_debit = Decimal('0.00') if is_debit_nature else abs(net_balance)
                tb_credit = abs(net_balance) if is_debit_nature else Decimal('0.00')

            grand_total_debit += tb_debit
            grand_total_credit += tb_credit

            trial_entries.append({
                'accountId': acc.id,
                'accountCode': acc.code,
                'accountName': acc.name,
                'accountType': acc.account_type,
                'totalDebit': str(tb_debit.quantize(Decimal('0.01'))),
                'totalCredit': str(tb_credit.quantize(Decimal('0.01'))),
                'netBalance': str(net_balance.quantize(Decimal('0.01')))
            })

        difference = (grand_total_debit - grand_total_credit).quantize(Decimal('0.01'))

        return {
            'asOfDate': str(as_of_date),
            'totalDebit': str(grand_total_debit.quantize(Decimal('0.01'))),
            'totalCredit': str(grand_total_credit.quantize(Decimal('0.01'))),
            'difference': str(difference),
            'isBalanced': difference == Decimal('0.00'),
            'accounts': trial_entries
        }

    @staticmethod
    def get_profit_and_loss_statement(start_date=None, end_date=None):
        """
        Generates Profit and Loss (Income) Statement:
        1. Operating Revenue (4000)
        2. Cost of Goods Sold (5000)
        3. Gross Profit = Revenue - COGS
        4. Operating & Administrative Expenses (6000)
        5. Net Profit = Gross Profit - Operating Expenses
        """
        if not start_date:
            start_date = timezone.now().date().replace(month=1, day=1)
        if not end_date:
            end_date = timezone.now().date()

        def get_group_total(account_type_filter, code_prefix=None):
            qs = JournalEntry.objects.filter(
                account__account_type=account_type_filter,
                voucher__status=VoucherStatus.POSTED,
                voucher__voucher_date__gte=start_date,
                voucher__voucher_date__lte=end_date
            )
            if code_prefix:
                qs = qs.filter(account__code__startswith=code_prefix)

            accounts_map = {}
            for entry in qs.select_related('account'):
                acc = entry.account
                if acc.id not in accounts_map:
                    accounts_map[acc.id] = {
                        'accountId': acc.id,
                        'accountCode': acc.code,
                        'accountName': acc.name,
                        'amount': Decimal('0.00')
                    }
                if account_type_filter == AccountType.REVENUE:
                    accounts_map[acc.id]['amount'] += (entry.credit_amount - entry.debit_amount)
                else:
                    accounts_map[acc.id]['amount'] += (entry.debit_amount - entry.credit_amount)

            items_list = [
                {
                    'accountId': v['accountId'],
                    'accountCode': v['accountCode'],
                    'accountName': v['accountName'],
                    'amount': str(v['amount'].quantize(Decimal('0.01')))
                }
                for v in accounts_map.values() if v['amount'] != 0
            ]
            total_sum = sum((Decimal(i['amount']) for i in items_list), Decimal('0.00'))
            return total_sum.quantize(Decimal('0.01')), items_list

        total_revenue, revenue_items = get_group_total(AccountType.REVENUE)
        total_cogs, cogs_items = get_group_total(AccountType.EXPENSE, code_prefix='5')
        gross_profit = (total_revenue - total_cogs).quantize(Decimal('0.01'))

        total_opex, opex_items = get_group_total(AccountType.EXPENSE, code_prefix='6')
        net_profit = (gross_profit - total_opex).quantize(Decimal('0.01'))

        return {
            'startDate': str(start_date),
            'endDate': str(end_date),
            'totalRevenue': str(total_revenue),
            'revenueBreakdown': revenue_items,
            'totalCostOfGoodsSold': str(total_cogs),
            'cogsBreakdown': cogs_items,
            'grossProfit': str(gross_profit),
            'totalOperatingExpenses': str(total_opex),
            'expenseBreakdown': opex_items,
            'netProfit': str(net_profit),
            'isProfitable': net_profit >= 0
        }

    @staticmethod
    def get_balance_sheet(as_of_date=None):
        """
        Generates Balance Sheet as of a specific date:
        Total Assets = Total Liabilities + Total Equity (including Retained Net Profit)
        """
        if not as_of_date:
            as_of_date = timezone.now().date()

        def get_category_data(acc_type):
            accounts = AccountHead.objects.filter(account_type=acc_type, is_active=True, is_group=False)
            items = []
            total_cat = Decimal('0.00')

            for acc in accounts:
                qs = JournalEntry.objects.filter(
                    account=acc,
                    voucher__status=VoucherStatus.POSTED,
                    voucher__voucher_date__lte=as_of_date
                )
                agg = qs.aggregate(tot_dr=Sum('debit_amount'), tot_cr=Sum('credit_amount'))
                dr = agg['tot_dr'] or Decimal('0.00')
                cr = agg['tot_cr'] or Decimal('0.00')

                if dr == 0 and cr == 0:
                    continue

                if acc_type == AccountType.ASSET:
                    bal = (dr - cr).quantize(Decimal('0.01'))
                else:
                    bal = (cr - dr).quantize(Decimal('0.01'))

                total_cat += bal
                items.append({
                    'accountId': acc.id,
                    'accountCode': acc.code,
                    'accountName': acc.name,
                    'balance': str(bal)
                })

            return total_cat.quantize(Decimal('0.01')), items

        total_assets, asset_items = get_category_data(AccountType.ASSET)
        total_liabilities, liability_items = get_category_data(AccountType.LIABILITY)
        total_equity, equity_items = get_category_data(AccountType.EQUITY)

        # Compute retained net profit up to as_of_date
        pnl = FinancialReportEngine.get_profit_and_loss_statement(
            start_date=as_of_date.replace(month=1, day=1),
            end_date=as_of_date
        )
        current_period_net_income = Decimal(str(pnl['netProfit'])).quantize(Decimal('0.01'))

        total_equity_and_liabilities = (total_liabilities + total_equity + current_period_net_income).quantize(Decimal('0.01'))
        equation_difference = (total_assets - total_equity_and_liabilities).quantize(Decimal('0.01'))

        return {
            'asOfDate': str(as_of_date),
            'totalAssets': str(total_assets),
            'assetsBreakdown': asset_items,
            'totalLiabilities': str(total_liabilities),
            'liabilitiesBreakdown': liability_items,
            'totalEquity': str(total_equity),
            'equityBreakdown': equity_items,
            'currentPeriodNetIncome': str(current_period_net_income),
            'totalEquityAndLiabilities': str(total_equity_and_liabilities),
            'equationDifference': str(equation_difference),
            'isBalanced': equation_difference == Decimal('0.00')
        }

    @staticmethod
    def get_vat_report(start_date=None, end_date=None):
        """
        VAT & Tax Sub-ledger report for government Mushak compliance:
        - Output VAT collected from customer sales orders
        - Input VAT paid on purchases
        - Net VAT Payable / Refundable
        """
        output_vat_acc = AccountHead.objects.filter(code='2150').first()
        input_vat_acc = AccountHead.objects.filter(code='1150').first()

        output_vat_entries = JournalEntry.objects.filter(
            account=output_vat_acc,
            voucher__status=VoucherStatus.POSTED
        ) if output_vat_acc else JournalEntry.objects.none()

        input_vat_entries = JournalEntry.objects.filter(
            account=input_vat_acc,
            voucher__status=VoucherStatus.POSTED
        ) if input_vat_acc else JournalEntry.objects.none()

        if start_date:
            output_vat_entries = output_vat_entries.filter(voucher__voucher_date__gte=start_date)
            input_vat_entries = input_vat_entries.filter(voucher__voucher_date__gte=start_date)
        if end_date:
            output_vat_entries = output_vat_entries.filter(voucher__voucher_date__lte=end_date)
            input_vat_entries = input_vat_entries.filter(voucher__voucher_date__lte=end_date)

        total_output_vat = (output_vat_entries.aggregate(tot=Sum('credit_amount'))['tot'] or Decimal('0.00')).quantize(Decimal('0.01'))
        total_input_vat = (input_vat_entries.aggregate(tot=Sum('debit_amount'))['tot'] or Decimal('0.00')).quantize(Decimal('0.01'))
        net_vat_payable = (total_output_vat - total_input_vat).quantize(Decimal('0.01'))

        return {
            'startDate': str(start_date) if start_date else None,
            'endDate': str(end_date) if end_date else None,
            'totalOutputVatCollected': str(total_output_vat),
            'totalInputVatPaid': str(total_input_vat),
            'netVatPayable': str(net_vat_payable),
            'isRefundable': net_vat_payable < 0
        }
