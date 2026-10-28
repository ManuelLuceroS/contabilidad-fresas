from django.db import migrations


def grant_sender_permission(apps, schema_editor):
    alias = schema_editor.connection.alias
    Group = apps.get_model('auth', 'Group')
    group = Group.objects.using(alias).filter(name='Operadores').first()
    if not group:
        return
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    content_type, _ = ContentType.objects.using(alias).get_or_create(app_label='ledger', model='whatsappmessage')
    permission, _ = Permission.objects.using(alias).get_or_create(content_type=content_type,
        codename='send_whatsappmessage', defaults={'name': 'Puede enviar comprobantes por WhatsApp'})
    group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [('ledger', '0007_customer_whatsapp_opt_in_worker_phone_and_more')]
    operations = [migrations.RunPython(grant_sender_permission, migrations.RunPython.noop)]
