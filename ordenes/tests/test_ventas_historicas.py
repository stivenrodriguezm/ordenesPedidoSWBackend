"""Ventas históricas frente a cambios de la lista de precios (2026-10-24): cambiar o eliminar
un multiplicador no altera las ventas ya guardadas, ni siquiera al editarlas; el precio
actual solo se aplica a una línea cuando se pide («Actualizar precio»)."""
from decimal import Decimal

from listaprecios.models import Multiplicador, VarianteProducto
from ordenes.models import LineaVenta, RolePermission
from ordenes.tests import test_productos_venta as base
from ordenes.tests import test_productos_venta_conjuntos as conjuntos
from ordenes.tests import test_conjuntos_por_piezas as piezas
from ordenes.tests.utils import LottusTestCase


def con_ids(filas, d, **cambios):
    """Las mismas filas, ya guardadas (con su id), y con algún cambio."""
    return [{**f, 'id': l['id'], **cambios} for f, l in zip(filas, d['lineas'])]


class ProductoHistoricoTests(LottusTestCase):
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar

    def setUp(self):
        base.ProductosVentaTests.setUp(self)
        RolePermission.objects.filter(role='administrador').delete()  # sin configuración = acceso total

    def test_cambiar_el_multiplicador_no_cambia_la_venta_hasta_actualizar(self):
        filas = [self.fila()]
        d = self.guardar(filas)
        self.assertEqual(Decimal(d['valor_lista']), Decimal(460))
        Multiplicador.objects.filter(es_general=True).update(valor=3)

        # Editar un texto conserva el precio con que se vendió.
        d = self.guardar(con_ids(filas, d, texto_cliente='Otro texto'), revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(460))
        self.assertEqual(LineaVenta.objects.get().precio_lista_unitario, Decimal(230))

        # El editor muestra el guardado y avisa el actual: (100 + 2×10 + 5 − 10) × 3 = 345.
        r = self.api_asesor.post(self.url + 'calcular/', {**filas[0], 'id': d['lineas'][0]['id'], 'cantidad': 1}, format='json')
        self.assertEqual((r.data['precio_lista_unitario'], r.data['precio_lista_vigente']), ('230.00', '345.00'))

        # Solo al pedirlo se aplica la lista actual.
        d = self.guardar(con_ids(filas, d, recalcular=True), revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(690))
        r = self.api_asesor.post(self.url + 'calcular/', {**filas[0], 'id': d['lineas'][0]['id'], 'cantidad': 1}, format='json')
        self.assertNotIn('precio_lista_vigente', r.data)

    def test_eliminar_un_multiplicador_en_uso_reasigna_sus_productos(self):
        especial = Multiplicador.objects.create(nombre='Especial', valor=Decimal('2.5'))
        otro = Multiplicador.objects.create(nombre='Otro', valor=Decimal('1.9'))
        VarianteProducto.objects.filter(pk=self.variante.pk).update(multiplicador=especial)
        d = self.guardar()
        vendida = LineaVenta.objects.get()
        url = f'/api/listaprecios/multiplicadores/{especial.pk}/'

        self.assertEqual(self.api_admin.get(url + 'impacto/').data['productos_asignados'], 1)
        self.assertEqual(self.api_admin.delete(url + '?reasignar_a=999999').status_code, 400)
        r = self.api_admin.delete(url + f'?reasignar_a={otro.pk}')
        self.assertEqual((r.status_code, r.data['reasignados'], r.data['destino']), (200, 1, 'Otro'))
        self.assertFalse(Multiplicador.objects.filter(pk=especial.pk).exists())
        self.variante.refresh_from_db()
        self.assertEqual(self.variante.multiplicador_id, otro.pk)

        # La venta sigue igual, también al volver a guardarla.
        linea = LineaVenta.objects.get()
        self.assertEqual((linea.precio_lista_unitario, linea.precio_snapshot['multiplicador']),
                         (vendida.precio_lista_unitario, '2.500'))
        d2 = self.guardar(con_ids([self.fila()], d, texto_cliente='Cambio de texto'), revision=d['revision'])
        self.assertEqual(d2['valor_lista'], d['valor_lista'])

        # Sin destino pasan al general; el general no se elimina.
        r = self.api_admin.delete(f'/api/listaprecios/multiplicadores/{otro.pk}/')
        self.assertEqual((r.status_code, r.data['destino']), (200, 'General'))
        self.variante.refresh_from_db()
        self.assertIsNone(self.variante.multiplicador_id)
        general = Multiplicador.objects.get(es_general=True)
        self.assertEqual(self.api_admin.delete(f'/api/listaprecios/multiplicadores/{general.pk}/').status_code, 400)


class TransporteHistoricoTests(LottusTestCase):
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar

    def setUp(self):
        conjuntos.TransportesVentaTests.setUp(self)

    def test_el_transporte_compartido_queda_como_se_vendio(self):
        filas = [self.fila(cantidad=3)]
        d = self.guardar(filas)
        self.assertEqual(Decimal(d['valor_lista']), Decimal(3 * 330 - 100))
        Multiplicador.objects.filter(es_general=True).update(valor=3)
        d = self.guardar(con_ids(filas, d, texto_proveedor='Otro texto'), revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(3 * 330 - 100))
        self.assertEqual(d['lineas'][0]['transporte_compartido'], {'transportes': 2, 'valor': '100.00'})
        # Con «Actualizar precio»: (115 + 50) × 3 = 495 c/u, se descuenta un transporte de 150.
        d = self.guardar(con_ids(filas, d, recalcular=True), revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(3 * 495 - 150))


    def test_cambiar_la_cantidad_usa_el_transporte_como_se_vendio(self):
        filas = [self.fila(cantidad=3)]
        d = self.guardar(filas)
        Multiplicador.objects.filter(es_general=True).update(valor=3)
        # 4 sofás a $330 (precio vendido), cupo 2: 2 transportes cobrados, se descuentan 2 de $100.
        d = self.guardar(con_ids(filas, d, cantidad=4), revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(4 * 330 - 200))

    def test_lineas_guardadas_antes_del_cambio_deducen_su_transporte(self):
        filas = [self.fila(cantidad=3)]
        d = self.guardar(filas)
        linea = LineaVenta.objects.get()
        for k in ('transporte_unidad', 'cupo_transporte', 'da_decorativos'):
            linea.precio_snapshot.pop(k)
        linea.save(update_fields=['precio_snapshot'])
        Multiplicador.objects.filter(es_general=True).update(valor=3)
        d = self.guardar(con_ids(filas, d, cantidad=4), revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(4 * 330 - 200))  # 50 × 2 guardados, no 50 × 3


class DecorativosHistoricoTests(LottusTestCase):
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar
    incluir = conjuntos.DecorativosTests.incluir
    filas = conjuntos.DecorativosTests.filas

    def setUp(self):
        conjuntos.DecorativosTests.setUp(self)

    def test_cojines_incluidos_agregados_despues_no_aplican_a_la_venta(self):
        filas = self.filas()
        d = self.guardar(filas)
        self.incluir()
        # Cambia la cantidad (se recalculan los descuentos) pero el sofá se vendió sin el cupo.
        filas = con_ids(filas, d)
        filas[1]['cantidad'] = 2
        d = self.guardar(filas, revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(230 + 2 * 40 + 200))


class ConjuntoHistoricoTests(LottusTestCase):
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar
    piezas = piezas.ConjuntoPorPiezasTests.piezas

    def setUp(self):
        piezas.ConjuntoPorPiezasTests.setUp(self)

    def test_los_costos_del_conjunto_quedan_como_se_vendieron(self):
        filas = self.piezas()
        d = self.guardar(filas)
        antes = d['valor_lista']
        Multiplicador.objects.filter(es_general=True).update(valor=3)
        d = self.guardar(con_ids(filas, d, texto_cliente=''), revision=d['revision'])
        self.assertEqual(d['valor_lista'], antes)
        self.assertEqual(LineaVenta.objects.get(tipo='transporte').precio_lista_unitario, Decimal(120))
        # Dos conjuntos: el costo guardado por conjunto se duplica, sin tomar la lista nueva.
        dos = [dict(f, cantidad=f['cantidad'] * 2 if f.get('tipo') != 'transporte' else 1, conjunto_cantidad=2) for f in con_ids(filas, d)]
        d = self.guardar(dos, revision=d['revision'])
        self.assertEqual(LineaVenta.objects.get(tipo='transporte').precio_lista_unitario, Decimal(240))
        d = self.guardar([dict(f, recalcular=True) for f in con_ids(dos, d)], revision=d['revision'])
        self.assertEqual(LineaVenta.objects.get(tipo='transporte').precio_lista_unitario, Decimal(360))  # 60 × 3 × 2
