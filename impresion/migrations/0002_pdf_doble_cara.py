from django.db import migrations, models


def solo_mysql(sql):
    """El DEFAULT en la base es solo para MySQL (producción y pruebas); SQLite no admite ALTER COLUMN."""
    def ejecutar(apps, schema_editor):
        if schema_editor.connection.vendor == 'mysql':
            schema_editor.execute(sql)
    return ejecutar


class Migration(migrations.Migration):
    dependencies = [('impresion', '0001_initial')]
    operations = [
        migrations.AddField(model_name='trabajoimpresion', name='pdf', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='trabajoimpresion', name='doble_cara', field=models.BooleanField(default=False)),
        # Conservar compatibilidad con procesos anteriores durante el despliegue.
        migrations.RunPython(solo_mysql("ALTER TABLE impresion_trabajoimpresion ALTER COLUMN pdf SET DEFAULT ''"), migrations.RunPython.noop),
        migrations.RunPython(solo_mysql('ALTER TABLE impresion_trabajoimpresion ALTER COLUMN doble_cara SET DEFAULT 0'), migrations.RunPython.noop),
    ]
