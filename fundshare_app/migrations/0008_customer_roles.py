from django.db import migrations, models


def migrate_customers(apps, schema_editor):
    User = apps.get_model('fundshare_app', 'User')
    User.objects.using(schema_editor.connection.alias).filter(role='MEMBER').update(role='CUSTOMER')


class Migration(migrations.Migration):
    dependencies = [('fundshare_app', '0007_authentication_and_transaction_safety')]

    operations = [
        migrations.RunPython(migrate_customers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='user', name='role',
            field=models.CharField(
                choices=[('CUSTOMER', 'Customer / Wallet Owner'), ('MERCHANT', 'Merchant'), ('ADMIN', 'Admin / Hackathon Evaluator')],
                default='CUSTOMER', max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(condition=models.Q(role__in=['CUSTOMER', 'MERCHANT', 'ADMIN']), name='user_supported_role'),
        ),
    ]
