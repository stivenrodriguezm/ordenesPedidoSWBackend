"""Elimina Conteos de inventario y los abonos parciales a facturas (Cuentas por pagar):
módulos declarados innecesarios por el usuario (2026-10-06, D-ALCANCE). No volver a crearlos."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('suministros', '0038_rechazos_recepcion'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='facturaproveedor',
            name='usa_aplicaciones',
        ),
        migrations.AlterField(
            model_name='facturaproveedor',
            name='estado',
            field=models.CharField(choices=[('pagada', 'Pagada'), ('pendiente', 'Pendiente'), ('atrasada', 'Atrasada'), ('pago_en_proceso', 'Pago en proceso'), ('anulada', 'Anulada')], db_index=True, default='pendiente', max_length=50),
        ),
        migrations.AlterField(
            model_name='movimientoinventario',
            name='tipo',
            field=models.CharField(choices=[('ingreso', 'Ingreso'), ('edicion', 'Edición'), ('traslado', 'Traslado'), ('reserva', 'Reservado en remisión'), ('despacho', 'Despachado'), ('entrega', 'Entregado'), ('liberacion', 'Vuelve a bodega'), ('devolucion_proveedor', 'Devuelto al proveedor')], max_length=30),
        ),
        migrations.DeleteModel(
            name='LineaConteo',
        ),
        migrations.DeleteModel(
            name='ConteoInventario',
        ),
    ]
