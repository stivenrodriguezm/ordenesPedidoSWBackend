import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('pagos', '0004_detallepago_rechazado'), ('ordenes', '0078_comprobante_cuenta_destino')]
    operations = [
        migrations.RemoveConstraint(model_name='cuentabancaria', name='cuenta_un_solo_titular'),
        migrations.AddField(model_name='cuentabancaria', name='proveedor_tela', field=models.ForeignKey(to='ordenes.proveedortela', on_delete=django.db.models.deletion.PROTECT, related_name='cuentas_bancarias', null=True, blank=True)),
        migrations.AddConstraint(model_name='cuentabancaria', constraint=models.CheckConstraint(name='cuenta_un_solo_titular', check=(
            models.Q(empresa=True, proveedor__isnull=True, proveedor_tela__isnull=True, empleado__isnull=True) |
            models.Q(empresa=False, proveedor__isnull=False, proveedor_tela__isnull=True, empleado__isnull=True) |
            models.Q(empresa=False, proveedor__isnull=True, proveedor_tela__isnull=False, empleado__isnull=True) |
            models.Q(empresa=False, proveedor__isnull=True, proveedor_tela__isnull=True, empleado__isnull=False)))),
    ]
