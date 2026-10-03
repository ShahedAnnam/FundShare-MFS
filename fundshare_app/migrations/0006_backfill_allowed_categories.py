"""
Data migration: Backfill allowed_categories for existing FamilyPass records.

Applies the canonical PURPOSE_TO_CATEGORIES mapping:
    Grocery           → ['Grocery']
    Medical           → ['Medicine', 'Treatment']
    Dining            → ['Restaurant/Food']
    Bills & Utilities → ['Electricity', 'Rent']
    Education         → ['Education']
    Transport         → ['Transport']
    Shopping          → ['Shopping']
    Emergency         → [] (unrestricted)
    Other             → [] (unrestricted)

This migration is non-destructive:
    - It only updates the `allowed_categories` JSONField.
    - It never deletes data or alters schema.
    - It is idempotent (re-running it has no additional effect).
"""

from django.db import migrations


# Canonical mapping: FamilyPassPurpose -> BusinessCategory values
PURPOSE_TO_CATEGORIES = {
    'Grocery': ['Grocery'],
    'Medical': ['Medicine', 'Treatment'],
    'Dining': ['Restaurant/Food'],
    'Bills & Utilities': ['Electricity', 'Rent'],
    'Education': ['Education'],
    'Transport': ['Transport'],
    'Shopping': ['Shopping'],
    'Emergency': [],  # unrestricted
    'Other': [],      # unrestricted
}


def backfill_allowed_categories(apps, schema_editor):
    FamilyPass = apps.get_model('fundshare_app', 'FamilyPass')
    for fp in FamilyPass.objects.filter(allowed_categories=[]):
        mapping = PURPOSE_TO_CATEGORIES.get(fp.purpose)
        if mapping:
            fp.allowed_categories = mapping
            fp.save(update_fields=['allowed_categories'])


def reverse_backfill(apps, schema_editor):
    """Reverse: clear the categories that were backfilled."""
    FamilyPass = apps.get_model('fundshare_app', 'FamilyPass')
    for purpose, categories in PURPOSE_TO_CATEGORIES.items():
        if categories:
            FamilyPass.objects.filter(
                purpose=purpose,
                allowed_categories=categories,
            ).update(allowed_categories=[])


class Migration(migrations.Migration):

    dependencies = [
        ('fundshare_app', '0005_familypass_allowed_categories_and_more'),
    ]

    operations = [
        migrations.RunPython(
            backfill_allowed_categories,
            reverse_code=reverse_backfill,
        ),
    ]
