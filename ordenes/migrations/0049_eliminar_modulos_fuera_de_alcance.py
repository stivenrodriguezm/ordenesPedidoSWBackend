"""Elimina los módulos que el usuario declaró innecesarios (2026-10-06, D-ALCANCE en
docs/auditoria-2026-10-02/decisiones.md): Cuentas por pagar (abonos y programación),
Cartera (promesas), Turnos de caja y Posventa. Nunca estuvieron en producción y la
copia de pruebas no tenía filas en estas tablas. No volver a crearlos."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0048_alter_evidenciaposventa_archivo'),
    ]

    operations = [
        migrations.RemoveField(model_name='caja', name='turno'),
        migrations.DeleteModel(name='ProgramacionPago'),
        migrations.DeleteModel(name='AplicacionEgreso'),
        migrations.DeleteModel(name='PromesaPago'),
        migrations.DeleteModel(name='TurnoCaja'),
        migrations.DeleteModel(name='SeguimientoPosventa'),
        migrations.DeleteModel(name='EvidenciaPosventa'),
        migrations.DeleteModel(name='CasoPosventa'),
    ]
