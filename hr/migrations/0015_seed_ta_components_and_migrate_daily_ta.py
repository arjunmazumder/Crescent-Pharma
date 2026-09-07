from decimal import Decimal

from django.db import migrations


# (code, name, description, display_order)
DEFAULT_COMPONENTS = [
    (
        'TRANSPORT',
        'Transport / Conveyance',
        'Daily fare for field travel — bus, CNG, rickshaw, or fuel reimbursement.',
        10,
    ),
    (
        'MEAL',
        'Meal / Food',
        'Daily food allowance while working in the field.',
        20,
    ),
    (
        'HOTEL',
        'Hotel / Accommodation',
        'Daily lodging allowance for overnight field duty.',
        30,
    ),
    (
        'DAILY',
        'General Daily Allowance',
        'Standing daily allowance. Carries the value migrated from the old '
        'SalaryStructure.daily_ta_allowance field.',
        40,
    ),
]


def seed_components_and_migrate_rates(apps, schema_editor):
    TAComponent = apps.get_model('hr', 'TAComponent')
    EmployeeTARate = apps.get_model('hr', 'EmployeeTARate')
    SalaryStructure = apps.get_model('hr', 'SalaryStructure')

    for code, name, description, order in DEFAULT_COMPONENTS:
        TAComponent.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'description': description,
                'display_order': order,
                'is_active': True,
            },
        )

    daily = TAComponent.objects.get(code='DAILY')

    # Carry every non-zero legacy daily TA across to the DAILY component,
    # preserving the salary structure's own effective_from so historical months
    # resolve to the rate that was actually in force.
    structures = (
        SalaryStructure.objects
        .filter(daily_ta_allowance__gt=Decimal('0.00'))
        .order_by('user_id', 'effective_from', 'id')
    )

    for structure in structures:
        EmployeeTARate.objects.update_or_create(
            user_id=structure.user_id,
            component=daily,
            effective_from=structure.effective_from,
            defaults={
                'daily_amount': structure.daily_ta_allowance,
                'is_active': True,
            },
        )


def reverse_seed(apps, schema_editor):
    TAComponent = apps.get_model('hr', 'TAComponent')
    EmployeeTARate = apps.get_model('hr', 'EmployeeTARate')

    codes = [code for code, _, _, _ in DEFAULT_COMPONENTS]
    EmployeeTARate.objects.filter(component__code__in=codes).delete()
    TAComponent.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0014_tacomponent_alter_salarystructure_daily_ta_allowance_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_components_and_migrate_rates, reverse_seed),
    ]
