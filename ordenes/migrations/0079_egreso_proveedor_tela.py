import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('ordenes', '0078_comprobante_cuenta_destino'), ('pagos', '0005_cuenta_proveedor_tela')]
    operations = [migrations.AddField(model_name='comprobanteegreso', name='proveedor_tela', field=models.ForeignKey(to='ordenes.proveedortela', on_delete=django.db.models.deletion.PROTECT, related_name='comprobantes_egreso', null=True, blank=True))]
