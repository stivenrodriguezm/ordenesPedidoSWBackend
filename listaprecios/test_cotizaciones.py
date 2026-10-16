"""Pruebas completas de Cotizaciones del Servidor (P09-01), Líneas de Venta (P09-03)
y Conversión a Venta (P09-04 / F01, F02, U01)."""
from decimal import Decimal

from listaprecios.models import (
    CategoriaLista, Cotizacion, GrupoTela, LineaCotizacion, LineaProducto,
    Multiplicador, VarianteProducto,
)
from ordenes.models import LineaVenta, Venta
from ordenes.tests.utils import LottusTestCase


class CotizacionesTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        self.general = Multiplicador.objects.create(nombre='General', valor=Decimal('1.80'), es_general=True)
        self.cat = CategoriaLista.objects.create(nombre='Salas', slug='salas')
        self.linea = LineaProducto.objects.create(nombre='Altus', slug='altus')
        self.variante1 = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.cat, nombre='Sofá 3 puestos', costo_base=Decimal('500000')
        )
        self.variante2 = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.cat, nombre='Poltrona', costo_base=Decimal('200000')
        )
        self.grupo = GrupoTela.objects.create(nombre='Grupo 2', precio_por_metro=Decimal('45000'))

        self.vendedor = self.crear_usuario('vendedor_cot', role='vendedor')
        self.vendedor2 = self.crear_usuario('vendedor_otro', role='vendedor')
        self.admin = self.crear_usuario('admin_cot', role='administrador')

        self.permisos('vendedor', ['VER_LISTA_PRECIOS', 'CREAR_VENTA', 'VER_VENTAS', 'VER_PROPIAS_VENTAS'])
        self.permisos('administrador', ['VER_LISTA_PRECIOS', 'CREAR_VENTA', 'VER_VENTAS', 'VER_TODAS_VENTAS', 'EDITAR_VENTA'])

        self.cli = self.cliente(cedula='12345678', nombre='Cliente Cotización')

    def test_crear_cotizacion_con_lineas_calcula_subtotal_y_total_con_descuento(self):
        payload = {
            'cliente': self.cli.id,
            'cliente_nombre': self.cli.nombre,
            'descuento': '50000.00',
            'notas': 'Cotización válida por 15 días.',
            'lineas': [
                {
                    'variante': self.variante1.id,
                    'linea_nombre': 'Altus',
                    'variante_nombre': 'Sofá 3 puestos',
                    'categoria_nombre': 'Salas',
                    'grupo_nombre': 'Grupo 2',
                    'cantidad': 1,
                    'precio_unitario': '1200000.00',
                    'opcionales': [{'descripcion': 'Patas metálicas', 'valor': 30000}],
                    'notas': 'Tela color beige',
                },
                {
                    'variante': self.variante2.id,
                    'linea_nombre': 'Altus',
                    'variante_nombre': 'Poltrona',
                    'categoria_nombre': 'Salas',
                    'grupo_nombre': 'Grupo 2',
                    'cantidad': 2,
                    'precio_unitario': '600000.00',
                    'opcionales': [],
                    'notas': '',
                },
            ]
        }
        r = self.api(self.vendedor).post('/api/listaprecios/cotizaciones/', payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        cot_id = r.data['id']
        cot = Cotizacion.objects.get(pk=cot_id)

        self.assertTrue(cot.numero.startswith('COT-'))
        self.assertEqual(cot.asesor, self.vendedor)
        self.assertEqual(cot.lineas.count(), 2)
        # Subtotal: 1 * 1200000 + 2 * 600000 = 2400000
        self.assertEqual(cot.subtotal, Decimal('2400000.00'))
        self.assertEqual(cot.descuento, Decimal('50000.00'))
        # Total: 2400000 - 50000 = 2350000
        self.assertEqual(cot.total, Decimal('2350000.00'))
        self.assertEqual(cot.version, 1)
        self.assertEqual(cot.estado, 'emitida')

    def test_cotizacion_requiere_al_menos_una_linea(self):
        payload = {
            'cliente': self.cli.id,
            'lineas': [],
        }
        r = self.api(self.vendedor).post('/api/listaprecios/cotizaciones/', payload, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('lineas', str(r.data))

    def test_control_de_concurrencia_optimista_version(self):
        cot = Cotizacion.objects.create(
            numero='COT-CONC-01', asesor=self.vendedor, total=Decimal('100000'), subtotal=Decimal('100000'), version=1
        )
        LineaCotizacion.objects.create(
            cotizacion=cot, linea_nombre='Altus', variante_nombre='P', cantidad=1,
            precio_unitario=Decimal('100000'), subtotal=Decimal('100000')
        )

        # Primer guardado envía version=1 -> éxito, pasa a version=2
        r1 = self.api(self.vendedor).patch(f'/api/listaprecios/cotizaciones/{cot.id}/', {
            'notas': 'Actualizado primero',
            'version': 1,
        }, format='json')
        self.assertEqual(r1.status_code, 200)
        cot.refresh_from_db()
        self.assertEqual(cot.version, 2)

        # Segundo guardado desfasado envía version=1 -> conflicto 409
        r2 = self.api(self.vendedor).patch(f'/api/listaprecios/cotizaciones/{cot.id}/', {
            'notas': 'Actualizado tarde',
            'version': 1,
        }, format='json')
        self.assertEqual(r2.status_code, 409)

    def test_cotizacion_aceptada_o_convertida_no_se_puede_editar(self):
        cot = Cotizacion.objects.create(
            numero='COT-ACEPT-01', asesor=self.vendedor, total=Decimal('100000'),
            subtotal=Decimal('100000'), version=1, estado='aceptada'
        )
        r = self.api(self.vendedor).patch(f'/api/listaprecios/cotizaciones/{cot.id}/', {
            'notas': 'Intentar modificar aceptada',
        }, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('no puede ser modificada', str(r.data))

    def test_vendedor_solo_ve_sus_cotizaciones_admin_ve_todas(self):
        cot1 = Cotizacion.objects.create(
            numero='COT-V1-01', asesor=self.vendedor, total=Decimal('100'), subtotal=Decimal('100')
        )
        cot2 = Cotizacion.objects.create(
            numero='COT-V2-01', asesor=self.vendedor2, total=Decimal('200'), subtotal=Decimal('200')
        )

        # Vendedor 1 solo ve cot1
        r_v1 = self.api(self.vendedor).get('/api/listaprecios/cotizaciones/')
        self.assertEqual(r_v1.status_code, 200)
        numeros_v1 = [c['numero'] for c in r_v1.data['results']] if 'results' in r_v1.data else [c['numero'] for c in r_v1.data]
        self.assertIn('COT-V1-01', numeros_v1)
        self.assertNotIn('COT-V2-01', numeros_v1)

        # Admin ve ambas
        r_adm = self.api(self.admin).get('/api/listaprecios/cotizaciones/')
        self.assertEqual(r_adm.status_code, 200)
        numeros_adm = [c['numero'] for c in r_adm.data['results']] if 'results' in r_adm.data else [c['numero'] for c in r_adm.data]
        self.assertIn('COT-V1-01', numeros_adm)
        self.assertIn('COT-V2-01', numeros_adm)

    def test_convertir_cotizacion_a_venta_exitoso_y_lineas_venta(self):
        referencia = self.referencia(self.proveedor(), 'Altus')
        self.linea.referencia = referencia
        self.linea.save()
        cot = Cotizacion.objects.create(
            numero='COT-CONV-99', asesor=self.vendedor, cliente=self.cli,
            subtotal=Decimal('1500000.00'), descuento=Decimal('100000.00'), total=Decimal('1400000.00'),
            estado='aceptada'
        )
        LineaCotizacion.objects.create(
            cotizacion=cot, variante=self.variante1, linea_nombre='Altus', variante_nombre='Sofá 3p',
            categoria_nombre='Salas', grupo_nombre='Grupo 2', cantidad=1,
            precio_unitario=Decimal('1500000.00'), subtotal=Decimal('1500000.00'), notas='Color Gris'
        )

        r = self.api(self.vendedor).post(f'/api/listaprecios/cotizaciones/{cot.id}/convertir-a-venta/', {
            'sede': 'Lottus 2',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        venta_id = r.data['venta_id']

        # Verificar Venta
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.cliente, self.cli)
        self.assertEqual(venta.vendedor, self.vendedor)
        self.assertEqual(venta.valor_total, Decimal('1400000.00'))
        self.assertEqual(venta.saldo, Decimal('1400000.00'))
        self.assertEqual(venta.sede, 'Lottus 2')

        # Verificar LineaVenta generada automáticamente
        self.assertEqual(venta.lineas.count(), 1)
        lv = venta.lineas.first()
        self.assertEqual(lv.producto_nombre, 'Altus')
        self.assertEqual(lv.referencia_id, referencia.pk)
        self.assertEqual(lv.variante_nombre, 'Sofá 3p')
        self.assertEqual(lv.precio_unitario, Decimal('1500000.00'))
        self.assertEqual(lv.cantidad, 1)

        # Cotización marcada como convertida
        cot.refresh_from_db()
        self.assertEqual(cot.estado, 'convertida')
        self.assertEqual(cot.venta_asociada, venta)
        self.assertIsNotNone(cot.fecha_conversion)

    def test_convertir_cotizacion_es_idempotente(self):
        cot = Cotizacion.objects.create(
            numero='COT-IDEMP-01', asesor=self.vendedor, cliente=self.cli,
            subtotal=Decimal('500000.00'), total=Decimal('500000.00'), estado='emitida'
        )
        LineaCotizacion.objects.create(
            cotizacion=cot, variante=self.variante2, linea_nombre='Altus', variante_nombre='Poltrona',
            cantidad=1, precio_unitario=Decimal('500000.00'), subtotal=Decimal('500000.00')
        )

        # Primera conversión
        r1 = self.api(self.vendedor).post(f'/api/listaprecios/cotizaciones/{cot.id}/convertir-a-venta/', format='json')
        self.assertEqual(r1.status_code, 201)
        v_id1 = r1.data['venta_id']

        # Segunda conversión con la misma cotización (idempotente)
        r2 = self.api(self.vendedor).post(f'/api/listaprecios/cotizaciones/{cot.id}/convertir-a-venta/', format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data['venta_id'], v_id1)
        self.assertIn('ya fue convertida', r2.data['message'])
        # No duplica la venta
        self.assertEqual(Venta.objects.filter(id=v_id1).count(), 1)

    def test_convertir_cotizacion_sin_permiso_crear_venta_falla(self):
        lector = self.crear_usuario('lector_sin_crear', role='auxiliar')
        self.permisos('auxiliar', ['VER_VENTAS']) # sin CREAR_VENTA
        cot = Cotizacion.objects.create(
            numero='COT-403-01', asesor=self.vendedor, cliente=self.cli, total=Decimal('100'), subtotal=Decimal('100')
        )
        r = self.api(lector).post(f'/api/listaprecios/cotizaciones/{cot.id}/convertir-a-venta/', format='json')
        self.assertEqual(r.status_code, 403)

    def test_expediente_venta_incluye_lineas_y_cotizaciones(self):
        cot = Cotizacion.objects.create(
            numero='COT-EXP-01', asesor=self.vendedor, cliente=self.cli,
            subtotal=Decimal('800000.00'), total=Decimal('800000.00'), estado='aceptada'
        )
        LineaCotizacion.objects.create(
            cotizacion=cot, linea_nombre='Altus', variante_nombre='Sofá 3p',
            cantidad=1, precio_unitario=Decimal('800000.00'), subtotal=Decimal('800000.00')
        )
        r_conv = self.api(self.vendedor).post(f'/api/listaprecios/cotizaciones/{cot.id}/convertir-a-venta/', format='json')
        venta_id = r_conv.data['venta_id']

        # Consultar detalle de la venta (expediente P09-05)
        r = self.api(self.vendedor).get(f'/api/ventas/{venta_id}/')
        self.assertEqual(r.status_code, 200)
        data = r.data
        self.assertIn('lineas', data)
        self.assertEqual(len(data['lineas']), 1)
        self.assertEqual(data['lineas'][0]['producto_nombre'], 'Altus')
        self.assertIn('cotizaciones', data)
        self.assertEqual(len(data['cotizaciones']), 1)
        self.assertEqual(data['cotizaciones'][0]['numero'], 'COT-EXP-01')

    def test_expediente_venta_historica_sin_lineas_ni_cotizaciones(self):
        """P09-06: Ventas históricas devuelven listas vacías sin inventar datos ni fallar."""
        venta_hist = self.venta(
            vendedor=self.vendedor, cliente=self.cli, valor='1200000.00', abono=Decimal('400000.00')
        )
        venta_hist.saldo = Decimal('800000.00')
        venta_hist.save(update_fields=['saldo'])
        r = self.api(self.vendedor).get(f'/api/ventas/{venta_hist.id}/')
        self.assertEqual(r.status_code, 200)
        data = r.data
        self.assertEqual(data['lineas'], [])
        self.assertEqual(data['cotizaciones'], [])
        self.assertEqual(Decimal(str(data['valor_total'])), Decimal('1200000.00'))
        self.assertEqual(Decimal(str(data['abono'])), Decimal('400000.00'))
        self.assertEqual(Decimal(str(data['saldo'])), Decimal('800000.00'))
