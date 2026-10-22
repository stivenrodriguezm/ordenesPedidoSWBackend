import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ordenes', '0077_quitar_cojines_linea_venta'), ('pagos', '0002_programacion_inicial')]
    operations = [
        migrations.AddField(model_name='comprobanteegreso', name='cuenta_destino', field=models.ForeignKey(
            to='pagos.cuentabancaria', on_delete=django.db.models.deletion.PROTECT, null=True, blank=True, related_name='+')),
        migrations.AddField(model_name='comprobanteegreso', name='cuenta_destino_snapshot', field=models.JSONField(default=dict, blank=True)),
    ]
