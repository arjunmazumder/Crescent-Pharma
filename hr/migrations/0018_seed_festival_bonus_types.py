from decimal import Decimal

from django.db import migrations


# (code, name, percentage_of_basic, description, display_order)
FESTIVAL_BONUSES = [
    (
        'EID_UL_FITR',
        'Eid-ul-Fitr Bonus',
        Decimal('100.00'),
        'Festival bonus paid with the payroll of the month in which Eid-ul-Fitr falls.',
        10,
    ),
    (
        'EID_UL_ADHA',
        'Eid-ul-Adha Bonus',
        Decimal('100.00'),
        'Festival bonus paid with the payroll of the month in which Eid-ul-Adha falls.',
        20,
    ),
]


def seed_bonus_types(apps, schema_editor):
    BonusType = apps.get_model('hr', 'BonusType')
    for code, name, percentage, description, order in FESTIVAL_BONUSES:
        BonusType.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'percentage_of_basic': percentage,
                'description': description,
                'display_order': order,
                'is_active': True,
            },
        )


def reverse_seed(apps, schema_editor):
    BonusType = apps.get_model('hr', 'BonusType')
    BonusType.objects.filter(
        code__in=[code for code, _, _, _, _ in FESTIVAL_BONUSES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0017_bonustype_payroll_bonus_percentage_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_bonus_types, reverse_seed),
    ]
