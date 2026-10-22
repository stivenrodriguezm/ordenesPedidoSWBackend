from django.db import migrations


def crear(apps, schema_editor):
    apps.get_model('pagos', 'ProgramacionNomina').objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [('pagos', '0001_initial')]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
