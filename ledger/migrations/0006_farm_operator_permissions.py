from django.db import migrations


def grant_existing_operators(apps, schema_editor):
    alias = schema_editor.connection.alias
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    group = Group.objects.using(alias).filter(name='Operadores').first()
    if not group:
        return
    # Conserva todos los permisos anteriores; agrega solo los de operación agrícola.
    for model in ('worker', 'attendance', 'payroll', 'sprayproduct', 'sprayapplication'):
        content_type, _ = ContentType.objects.using(alias).get_or_create(app_label='ledger', model=model)
        for action in ('view', 'add', 'change'):
            permission, _ = Permission.objects.using(alias).get_or_create(
                content_type=content_type, codename=f'{action}_{model}',
                defaults={'name': f'Can {action} {model}'})
            group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [('ledger', '0005_attendance_payroll_payrollday_payrollsettings_and_more'),
                    ('auth', '0012_alter_user_first_name_max_length')]
    operations = [migrations.RunPython(grant_existing_operators, migrations.RunPython.noop)]
