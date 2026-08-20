import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from accounting.models import AccountHead, AccountType, FiscalYear, AccountingPeriod


class Command(BaseCommand):
    help = 'Seeds standard IFRS 5-tier pharmaceutical Chart of Accounts and current Fiscal Year'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding Standard Chart of Accounts (COA)..."))

        # Structure: (code, name, account_type, is_group, parent_code, is_reconciliation, is_system_locked, currency)
        COA_DEFINITIONS = [
            # 1000 - ASSETS
            ('1000', 'Assets (সম্পদ)', AccountType.ASSET, True, None, False, True, 'BDT'),
            ('1100', 'Current Assets (চলতি সম্পদ)', AccountType.ASSET, True, '1000', False, True, 'BDT'),
            ('1110', 'Cash & Cash Equivalents (নগদ ও ব্যাংক তহবিল)', AccountType.ASSET, True, '1100', False, True, 'BDT'),
            ('1111', 'Main Cash Vault & Petty Cash', AccountType.ASSET, False, '1110', True, True, 'BDT'),
            ('1112', 'Sonali Bank Corporate CD A/C', AccountType.ASSET, False, '1110', True, True, 'BDT'),
            ('1113', 'Dutch Bangla Bank Principal CD A/C', AccountType.ASSET, False, '1110', True, True, 'BDT'),
            ('1114', 'bKash / Nagad Merchant Collection A/C', AccountType.ASSET, False, '1110', True, True, 'BDT'),
            ('1120', 'Accounts Receivable (Trade Debtors)', AccountType.ASSET, False, '1100', False, True, 'BDT'),
            ('1130', 'Employee Advances & Loans Receivable', AccountType.ASSET, False, '1100', False, True, 'BDT'),
            ('1140', 'Finished Goods Inventory Stock', AccountType.ASSET, False, '1100', False, True, 'BDT'),
            ('1141', 'Raw & Packaging Material Inventory', AccountType.ASSET, False, '1100', False, True, 'BDT'),
            ('1150', 'Input VAT Paid on Purchases (Advance Tax)', AccountType.ASSET, False, '1100', False, True, 'BDT'),
            ('1200', 'Non-Current / Fixed Assets (স্থায়ী সম্পদ)', AccountType.ASSET, True, '1000', False, True, 'BDT'),
            ('1210', 'Factory Land & Industrial Buildings', AccountType.ASSET, False, '1200', False, True, 'BDT'),
            ('1220', 'Pharmaceutical Plant & Machinery', AccountType.ASSET, False, '1200', False, True, 'BDT'),
            ('1230', 'Office Equipment & Computers', AccountType.ASSET, False, '1200', False, True, 'BDT'),
            ('1240', 'Delivery Vehicles & Vans', AccountType.ASSET, False, '1200', False, True, 'BDT'),
            ('1290', 'Accumulated Depreciation', AccountType.ASSET, False, '1200', False, True, 'BDT'),

            # 2000 - LIABILITIES
            ('2000', 'Liabilities (দায়)', AccountType.LIABILITY, True, None, False, True, 'BDT'),
            ('2100', 'Current Liabilities (চলতি দায়)', AccountType.LIABILITY, True, '2000', False, True, 'BDT'),
            ('2110', 'Accounts Payable (Trade Creditors / Raw Material Suppliers)', AccountType.LIABILITY, False, '2100', False, True, 'BDT'),
            ('2120', 'Salaries & Wages Payable', AccountType.LIABILITY, False, '2100', False, True, 'BDT'),
            ('2130', 'Tour & Daily Allowances (TA/DA) Payable', AccountType.LIABILITY, False, '2100', False, True, 'BDT'),
            ('2140', 'Accrued Utilities & Factory Expenses', AccountType.LIABILITY, False, '2100', False, True, 'BDT'),
            ('2150', 'Output VAT Payable (Govt Tax)', AccountType.LIABILITY, False, '2100', False, True, 'BDT'),
            ('2200', 'Non-Current Liabilities (দীর্ঘমেয়াদী দায়)', AccountType.LIABILITY, True, '2000', False, True, 'BDT'),
            ('2210', 'Long Term Bank Borrowings / Project Loan', AccountType.LIABILITY, False, '2200', False, True, 'BDT'),

            # 3000 - EQUITY
            ('3000', 'Equity (মালিকানাস্বত্ব)', AccountType.EQUITY, True, None, False, True, 'BDT'),
            ('3100', 'Paid-up Share Capital', AccountType.EQUITY, False, '3000', False, True, 'BDT'),
            ('3200', 'Retained Earnings (পুঞ্জীভূত মুনাফা)', AccountType.EQUITY, False, '3000', False, True, 'BDT'),

            # 4000 - REVENUE
            ('4000', 'Revenue / Sales Income (বিক্রয় ও আয়)', AccountType.REVENUE, True, None, False, True, 'BDT'),
            ('4100', 'Pharmaceutical Sales Revenue', AccountType.REVENUE, False, '4000', False, True, 'BDT'),
            ('4200', 'Wholesale & Institutional Sales', AccountType.REVENUE, False, '4000', False, True, 'BDT'),
            ('4300', 'Scrap & By-product Sales', AccountType.REVENUE, False, '4000', False, True, 'BDT'),
            ('4400', 'Other Operating Income', AccountType.REVENUE, False, '4000', False, True, 'BDT'),

            # 5000 - COGS
            ('5000', 'Cost of Goods Sold (উৎপাদন ও বিক্রিত পণ্যের ব্যয়)', AccountType.EXPENSE, True, None, False, True, 'BDT'),
            ('5100', 'Raw Material Consumption Cost', AccountType.EXPENSE, False, '5000', False, True, 'BDT'),
            ('5110', 'Packaging Material Consumption', AccountType.EXPENSE, False, '5000', False, True, 'BDT'),
            ('5200', 'Sales Discounts & Trade Rebates', AccountType.EXPENSE, False, '5000', False, True, 'BDT'),
            ('5300', 'Damaged & Expired Medicines Loss', AccountType.EXPENSE, False, '5000', False, True, 'BDT'),
            ('5400', 'Direct Factory Wages & Labor', AccountType.EXPENSE, False, '5000', False, True, 'BDT'),

            # 6000 - OPERATING EXPENSES
            ('6000', 'Operating & Administrative Expenses (পরিচালন ব্যয়)', AccountType.EXPENSE, True, None, False, True, 'BDT'),
            ('6100', 'Employee Basic Salaries', AccountType.EXPENSE, False, '6000', False, True, 'BDT'),
            ('6110', 'Housing, Transport & Medical Allowances', AccountType.EXPENSE, False, '6000', False, True, 'BDT'),
            ('6120', 'Travel & Tour Allowances (TA/DA)', AccountType.EXPENSE, False, '6000', False, True, 'BDT'),
            ('6200', 'Electricity & Factory Utility Bills', AccountType.EXPENSE, False, '6000', False, True, 'BDT'),
            ('6210', 'Office Rent & Facility Maintenance', AccountType.EXPENSE, False, '6000', False, True, 'BDT'),
            ('6220', 'Promotional Drug Samples to Doctors', AccountType.EXPENSE, False, '6000', False, True, 'BDT'),
            ('6230', 'Postage, Printing & Office Stationery', AccountType.EXPENSE, False, '6000', False, True, 'BDT'),
            ('6240', 'Depreciation & Amortization Expense', AccountType.EXPENSE, False, '6000', False, True, 'BDT'),
            ('6250', 'Bank Charges & Transaction Fees', AccountType.EXPENSE, False, '6000', False, True, 'BDT'),
        ]

        created_count = 0
        with transaction.atomic():
            # Pass 1: create or update accounts
            for code, name, acc_type, is_grp, parent_code, is_rec, is_locked, cur in COA_DEFINITIONS:
                head, created = AccountHead.objects.get_or_create(
                    code=code,
                    defaults={
                        'name': name,
                        'account_type': acc_type,
                        'is_group': is_grp,
                        'is_reconciliation': is_rec,
                        'is_system_locked': is_locked,
                        'currency': cur
                    }
                )
                if not created:
                    head.name = name
                    head.account_type = acc_type
                    head.is_group = is_grp
                    head.is_reconciliation = is_rec
                    head.is_system_locked = is_locked
                    head.currency = cur
                    head.save()
                else:
                    created_count += 1

            # Pass 2: link parents
            for code, _, _, _, parent_code, _, _, _ in COA_DEFINITIONS:
                if parent_code:
                    head = AccountHead.objects.filter(code=code).first()
                    parent = AccountHead.objects.filter(code=parent_code).first()
                    if head and parent and head.parent != parent:
                        head.parent = parent
                        head.save(update_fields=['parent'])

        self.stdout.write(self.style.SUCCESS(f"Chart of Accounts seeded: {len(COA_DEFINITIONS)} total heads ({created_count} newly created)."))

        # Seed Current Fiscal Year & Periods (FY 2026-2027)
        self.stdout.write(self.style.NOTICE("Seeding Current Fiscal Year (FY 2026-2027)..."))
        retained_head = AccountHead.objects.filter(code='3200').first()

        fy, _ = FiscalYear.objects.get_or_create(
            code='FY26-27',
            defaults={
                'name': 'FY 2026-2027',
                'start_date': datetime.date(2026, 7, 1),
                'end_date': datetime.date(2027, 6, 30),
                'is_current': True,
                'retained_earnings_account': retained_head
            }
        )

        # 12 Monthly periods
        month_names = [
            'July 2026', 'August 2026', 'September 2026', 'October 2026',
            'November 2026', 'December 2026', 'January 2027', 'February 2027',
            'March 2027', 'April 2027', 'May 2027', 'June 2027'
        ]
        
        # Month start/end dates
        month_dates = [
            (datetime.date(2026, 7, 1), datetime.date(2026, 7, 31)),
            (datetime.date(2026, 8, 1), datetime.date(2026, 8, 31)),
            (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)),
            (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)),
            (datetime.date(2026, 11, 1), datetime.date(2026, 11, 30)),
            (datetime.date(2026, 12, 1), datetime.date(2026, 12, 31)),
            (datetime.date(2027, 1, 1), datetime.date(2027, 1, 31)),
            (datetime.date(2027, 2, 1), datetime.date(2027, 2, 28)),
            (datetime.date(2027, 3, 1), datetime.date(2027, 3, 31)),
            (datetime.date(2027, 4, 1), datetime.date(2027, 4, 30)),
            (datetime.date(2027, 5, 1), datetime.date(2027, 5, 31)),
            (datetime.date(2027, 6, 1), datetime.date(2027, 6, 30)),
        ]

        today = datetime.date.today()
        for idx, (m_name, (s_dt, e_dt)) in enumerate(zip(month_names, month_dates), start=1):
            is_cur = s_dt <= today <= e_dt
            AccountingPeriod.objects.get_or_create(
                fiscal_year=fy,
                period_number=idx,
                defaults={
                    'name': m_name,
                    'start_date': s_dt,
                    'end_date': e_dt,
                    'is_current': is_cur
                }
            )

        self.stdout.write(self.style.SUCCESS(f"Fiscal Year {fy.name} and 12 Accounting Periods seeded successfully!"))
