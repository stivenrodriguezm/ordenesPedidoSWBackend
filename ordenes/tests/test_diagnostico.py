"""El diagnóstico es de solo lectura y detecta los estados que el informe
demostró posibles (P06-01)."""
import io
import json

from django.core.management import call_command

from ordenes.models import Caja, CuentaCaja, RegistroAuditoria
from ordenes.tests.utils import LottusTestCase


class DiagnosticoTests(LottusTestCase):
    def test_detecta_y_no_escribe(self):
        admin = self.crear_usuario('admin', role='administrador')
        Caja.objects.create(usuario=admin, tipo='ingreso', valor=-100, total_acumulado=-100, concepto='heredado')
        v = self.venta(admin)
        v.abono = 50  # abono sin pagos que lo expliquen
        v.save()
        antes = (Caja.objects.count(), CuentaCaja.objects.count(), RegistroAuditoria.objects.count())
        out = io.StringIO()
        call_command('diagnostico_auditoria', '--json', stdout=out)
        datos = json.loads(out.getvalue())
        self.assertEqual(datos['caja_movimientos_valor_negativo']['total'], 1)
        self.assertEqual(datos['caja_movimientos_con_saldo_negativo']['total'], 1)
        self.assertIn(v.id, datos['ventas_abono_o_saldo_descuadrado']['ids'])
        self.assertEqual((Caja.objects.count(), CuentaCaja.objects.count(), RegistroAuditoria.objects.count()), antes)
