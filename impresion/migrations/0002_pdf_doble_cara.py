from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('impresion', '0001_initial')]
    operations = [
        migrations.AddField(model_name='trabajoimpresion', name='pdf', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='trabajoimpresion', name='doble_cara', field=models.BooleanField(default=False)),
        # Conservar compatibilidad con procesos anteriores durante el despliegue.
        migrations.RunSQL("ALTER TABLE impresion_trabajoimpresion ALTER COLUMN pdf SET DEFAULT ''", migrations.RunSQL.noop),
        migrations.RunSQL('ALTER TABLE impresion_trabajoimpresion ALTER COLUMN doble_cara SET DEFAULT 0', migrations.RunSQL.noop),
    ]
