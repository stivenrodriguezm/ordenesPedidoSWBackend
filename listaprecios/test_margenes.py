"""Pruebas de Precio y Margen Explicables (P12-01 / F11):
- Topes de descuento (25% por defecto y configurable por variante)
- Costo estimado congelado y márgenes explicables
- Filtro de seguridad por permiso VER_MARGENES
- Prorrateo de descuentos en conversión a venta
- Simulación de multiplicador
"""
from decimal import Decimal

from listaprecios.models import (
    CategoriaLista, Cotizacion, GrupoTela, LineaCotizacion, LineaProducto,
    Multiplicador, VarianteProducto, CargoVariante,
)
from ordenes.models import LineaVenta, Venta
from ordenes.tests.utils import LottusTestCase


class MargenesYPreciosTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        self.general = Multiplicador.objects.create(nombre='General', valor=Decimal('2.00'), es_general=True)
        self.cat = CategoriaLista.objects.create(nombre='Salas', slug='salas')
        self.linea = LineaProducto.objects.create(nombre='Altus', slug='altus')
        self.grupo = GrupoTela.objects.create(nombre='Grupo 1', precio_por_metro=Decimal('50000'))

        # Variante estándar (sin tope explícito -> debe usar 25% por defecto)
        self.variante_std = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.cat, nombre='Sofá 3P Estándar',
            costo_base=Decimal('400000'), metraje_tela=Decimal('10.00'),
        )
        # Costo lista variante_std = 400.000 + (10 * 50.000) = 900.000
        # Precio de lista = 900.000 * 2.0 = 1.800.000

        # Variante con descuento restringido al 10%
        self.variante_restringida = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.cat, nombre='Poltrona Cuero Exclusiva',
            costo_base=Decimal('500000'), metraje_tela=Decimal('4.00'),
            descuento_maximo=Decimal('10.00'),
        )
        # Costo lista = 500.000 + (4 * 50.000) = 700.000
        # Precio lista = 700.000 * 2.0 = 1.400.000

        self.vendedor = self.crear_usuario('vendedor_user', role='vendedor')
        self.auxiliar = self.crear_usuario('auxiliar_user', role='auxiliar')
        self.admin = self.crear_usuario('admin_user', role='administrador')

        self.permisos('vendedor', ['VER_LISTA_PRECIOS', 'CREAR_VENTA', 'VER_VENTAS', 'VER_PROPIAS_VENTAS'])
        self.permisos('auxiliar', ['VER_LISTA_PRECIOS', 'CREAR_VENTA', 'VER_VENTAS', 'VER_TODAS_VENTAS', 'VER_MARGENES'])
        self.permisos('administrador', ['VER_LISTA_PRECIOS', 'EDITAR_LISTA_PRECIOS', 'CREAR_VENTA', 'VER_VENTAS', 'VER_TODAS_VENTAS', 'VER_MARGENES', 'EDITAR_VENTA'])

        self.cli = self.cliente(cedula='98765432', nombre='Cliente Margenes')

    def test_descuento_por_defecto_25_por_ciento_permite_y_rechaza(self):
        # Subtotal: 1 * 1.800.000 = 1.800.000. Tope 25% = 450.000.
        payload_ok = {
            'cliente': self.cli.id,
            'descuento': '450000.00',  # 25% exacto
            'lineas': [{
                'variante': self.variante_std.id,
                'linea_nombre': 'Altus',
                'variante_nombre': 'Sofá 3P Estándar',
                'grupo_tela': self.grupo.id,
                'cantidad': 1,
                'precio_unitario': '1800000.00',
            }],
        }
        r = self.api(self.vendedor).post('/api/listaprecios/cotizaciones/', payload_ok, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(str(r.data['descuento'])), Decimal('450000.00'))
        self.assertEqual(Decimal(str(r.data['descuento_porcentaje'])), Decimal('25.00'))

        # Descuento superior a 25% (450.001) debe fallar con 400
        payload_exceso = {
            'cliente': self.cli.id,
            'descuento': '450001.00',
            'lineas': [{
                'variante': self.variante_std.id,
                'linea_nombre': 'Altus',
                'variante_nombre': 'Sofá 3P Estándar',
                'grupo_tela': self.grupo.id,
                'cantidad': 1,
                'precio_unitario': '1800000.00',
            }],
        }
        r2 = self.api(self.vendedor).post('/api/listaprecios/cotizaciones/', payload_exceso, format='json')
        self.assertEqual(r2.status_code, 400)
        self.assertIn('descuento', r2.data)

    def test_descuento_maximo_personalizado_variante_restringida(self):
        # Variante restringida al 10%. Subtotal: 1 * 1.400.000. Tope 10% = 140.000.
        payload_ok = {
            'cliente': self.cli.id,
            'descuento': '140000.00',
            'lineas': [{
                'variante': self.variante_restringida.id,
                'linea_nombre': 'Altus',
                'variante_nombre': 'Poltrona Cuero Exclusiva',
                'grupo_tela': self.grupo.id,
                'cantidad': 1,
                'precio_unitario': '1400000.00',
            }],
        }
        r = self.api(self.vendedor).post('/api/listaprecios/cotizaciones/', payload_ok, format='json')
        self.assertEqual(r.status_code, 201)

        # 140.001 supera el 10% permitido para esta variante
        payload_fail = {
            'cliente': self.cli.id,
            'descuento': '140001.00',
            'lineas': [{
                'variante': self.variante_restringida.id,
                'linea_nombre': 'Altus',
                'variante_nombre': 'Poltrona Cuero Exclusiva',
                'grupo_tela': self.grupo.id,
                'cantidad': 1,
                'precio_unitario': '1400000.00',
            }],
        }
        r2 = self.api(self.vendedor).post('/api/listaprecios/cotizaciones/', payload_fail, format='json')
        self.assertEqual(r2.status_code, 400)
        self.assertIn('descuento', r2.data)

    def test_costo_estimado_congelado_y_margen_en_cotizacion(self):
        # Costo variante_std: 400.000 + 10*50.000 = 900.000
        # Precio: 1.800.000. Cantidad: 2 -> Subtotal = 3.600.000
        # Descuento: 200.000 -> Total = 3.400.000
        # Costo total estimado = 2 * 900.000 = 1.800.000
        # Margen total = 3.400.000 - 1.800.000 = 1.600.000
        payload = {
            'cliente': self.cli.id,
            'descuento': '200000.00',
            'lineas': [{
                'variante': self.variante_std.id,
                'linea_nombre': 'Altus',
                'variante_nombre': 'Sofá 3P Estándar',
                'grupo_tela': self.grupo.id,
                'cantidad': 2,
                'precio_unitario': '1800000.00',
            }],
        }
        r = self.api(self.admin).post('/api/listaprecios/cotizaciones/', payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        cot_id = r.data['id']

        cot = Cotizacion.objects.get(pk=cot_id)
        linea_cot = cot.lineas.first()
        self.assertEqual(linea_cot.costo_estimado, Decimal('900000.00'))

        # Modificar el catálogo en el tiempo: subir costo_base de la variante
        self.variante_std.costo_base = Decimal('800000')
        self.variante_std.save()

        # El costo estimado de la cotización debe permanecer congelado en 900.000
        linea_cot.refresh_from_db()
        self.assertEqual(linea_cot.costo_estimado, Decimal('900000.00'))

        # Ver detalle desde usuario con VER_MARGENES
        r_detalle = self.api(self.admin).get(f'/api/listaprecios/cotizaciones/{cot_id}/')
        self.assertEqual(r_detalle.status_code, 200)
        self.assertEqual(Decimal(str(r_detalle.data['margen_total'])), Decimal('1600000.00'))
        self.assertEqual(Decimal(str(r_detalle.data['lineas'][0]['costo_estimado'])), Decimal('900000.00'))

    def test_ocultamiento_de_margenes_sin_permiso(self):
        cot = Cotizacion.objects.create(
            numero='COT-MARG-01', asesor=self.vendedor, total=Decimal('1000000'), subtotal=Decimal('1000000'), version=1
        )
        LineaCotizacion.objects.create(
            cotizacion=cot, linea_nombre='Altus', variante_nombre='Sofá',
            cantidad=1, precio_unitario=Decimal('1000000'), subtotal=Decimal('1000000'),
            costo_estimado=Decimal('600000')
        )

        # Vendedor (sin VER_MARGENES): no debe recibir costo_estimado ni margen
        r_vend = self.api(self.vendedor).get(f'/api/listaprecios/cotizaciones/{cot.id}/')
        self.assertEqual(r_vend.status_code, 200)
        self.assertNotIn('margen_total', r_vend.data)
        self.assertNotIn('costo_estimado', r_vend.data['lineas'][0])
        self.assertNotIn('margen', r_vend.data['lineas'][0])

        # Auxiliar (con VER_MARGENES): debe recibir ambos
        r_aux = self.api(self.auxiliar).get(f'/api/listaprecios/cotizaciones/{cot.id}/')
        self.assertEqual(r_aux.status_code, 200)
        self.assertIn('margen_total', r_aux.data)
        self.assertEqual(Decimal(str(r_aux.data['margen_total'])), Decimal('400000.00'))
        self.assertIn('costo_estimado', r_aux.data['lineas'][0])
        self.assertEqual(Decimal(str(r_aux.data['lineas'][0]['costo_estimado'])), Decimal('600000.00'))
        self.assertEqual(Decimal(str(r_aux.data['lineas'][0]['margen'])), Decimal('400000.00'))

    def test_conversion_prorratea_descuento_y_preserva_costo_en_venta(self):
        # Cotización con 2 líneas:
        # Línea 1: Subtotal 1.000.000 (Costo est. 400.000)
        # Línea 2: Subtotal 3.000.000 (Costo est. 1.500.000)
        # Subtotal doc: 4.000.000. Descuento doc: 400.000 (10%). Total: 3.600.000.
        cot = Cotizacion.objects.create(
            numero='COT-CONV-01', asesor=self.vendedor,
            subtotal=Decimal('4000000.00'), descuento=Decimal('400000.00'),
            descuento_porcentaje=Decimal('10.00'), total=Decimal('3600000.00'),
            estado=Cotizacion.ESTADO_ACEPTADA, version=1, cliente=self.cli,
        )
        l1 = LineaCotizacion.objects.create(
            cotizacion=cot, variante=self.variante_std, linea_nombre='Altus', variante_nombre='Línea 1',
            cantidad=1, precio_unitario=Decimal('1000000.00'), subtotal=Decimal('1000000.00'),
            costo_estimado=Decimal('400000.00')
        )
        l2 = LineaCotizacion.objects.create(
            cotizacion=cot, variante=self.variante_std, linea_nombre='Altus', variante_nombre='Línea 2',
            cantidad=1, precio_unitario=Decimal('3000000.00'), subtotal=Decimal('3000000.00'),
            costo_estimado=Decimal('1500000.00')
        )

        r_conv = self.api(self.admin).post(f'/api/listaprecios/cotizaciones/{cot.id}/convertir-a-venta/', {
            'sede': 'Lottus Principal',
        }, format='json')
        self.assertEqual(r_conv.status_code, 201, r_conv.data)
        venta_id = r_conv.data['venta_id']

        venta = Venta.objects.get(pk=venta_id)
        self.assertEqual(venta.valor_total, Decimal('3600000.00'))

        lineas_venta = list(venta.lineas.order_by('id'))
        self.assertEqual(len(lineas_venta), 2)

        # Línea 1 recibe 10% del total descuento = 100.000. Subtotal neto = 900.000
        lv1 = lineas_venta[0]
        self.assertEqual(lv1.descuento, Decimal('100000.00'))
        self.assertEqual(lv1.subtotal, Decimal('900000.00'))
        self.assertEqual(lv1.costo_estimado, Decimal('400000.00'))

        # Línea 2 recibe 300.000. Subtotal neto = 2.700.000
        lv2 = lineas_venta[1]
        self.assertEqual(lv2.descuento, Decimal('300000.00'))
        self.assertEqual(lv2.subtotal, Decimal('2700000.00'))
        self.assertEqual(lv2.costo_estimado, Decimal('1500000.00'))

        # Garantía contable: suma de subtotales == valor_total de venta exactamente
        self.assertEqual(lv1.subtotal + lv2.subtotal, venta.valor_total)

        # Venta detalle con permisos muestra margen total:
        # Costo total = 400.000 + 1.500.000 = 1.900.000.
        # Margen total = 3.600.000 - 1.900.000 = 1.700.000.
        r_det = self.api(self.admin).get(f'/api/ventas/{venta.id}/')
        self.assertEqual(r_det.status_code, 200)
        self.assertEqual(Decimal(str(r_det.data['margen_total'])), Decimal('1700000.00'))
        self.assertEqual(Decimal(str(r_det.data['lineas'][0]['margen'])), Decimal('500000.00')) # 900.000 - 400.000

        # Sin permisos (vendedor), margen_total y costos ocultos en Venta
        r_det_vend = self.api(self.vendedor).get(f'/api/ventas/{venta.id}/')
        self.assertEqual(r_det_vend.status_code, 200)
        self.assertNotIn('margen_total', r_det_vend.data)
        self.assertNotIn('costo_estimado', r_det_vend.data['lineas'][0])
        self.assertNotIn('margen', r_det_vend.data['lineas'][0])

    def test_crear_venta_directa_valida_tope_descuento_linea(self):
        # Crear venta directa en /api/ventas/crear/ con descuento mayor a 25% debe fallar
        payload_fail = {
            'cliente': {'id': self.cli.id},
            'venta': {
                'id': 9901,
                'id_vendedor': self.vendedor.id,
                'valor_total': '1000000.00',
                'fecha_venta': '2026-10-06',
                'fecha_entrega': '2026-10-20',
                'sede': 'Lottus 1',
            },
            'lineas': [{
                'variante': self.variante_std.id,
                'cantidad': 1,
                'precio_unitario': '1000000.00',
                'descuento': '300000.00',  # 30% > 25% tope
                'notas': 'Descuento no autorizado',
            }]
        }
        r = self.api(self.vendedor).post('/api/ventas/crear/', payload_fail, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('lineas', r.data)

        # Con descuento <= 25% se crea exitosamente y asigna costo estimado
        payload_ok = {
            'cliente': {'id': self.cli.id},
            'venta': {
                'id': 9902,
                'id_vendedor': self.vendedor.id,
                'valor_total': '800000.00',
                'fecha_venta': '2026-10-06',
                'fecha_entrega': '2026-10-20',
                'sede': 'Lottus 1',
            },
            'lineas': [{
                'variante': self.variante_std.id,
                'grupo_tela': self.grupo.id,
                'cantidad': 1,
                'precio_unitario': '1000000.00',
                'descuento': '200000.00',  # 20% <= 25%
                'notas': 'Descuento autorizado',
            }]
        }
        r_ok = self.api(self.vendedor).post('/api/ventas/crear/', payload_ok, format='json')
        self.assertEqual(r_ok.status_code, 201, r_ok.data)
        venta_creada = Venta.objects.get(pk=r_ok.data['venta_id'])
        lv = venta_creada.lineas.first()
        self.assertEqual(lv.descuento, Decimal('200000.00'))
        self.assertEqual(lv.costo_estimado, Decimal('900000.00'))

    def test_simular_multiplicador_endpoint(self):
        # Simular cambio de general de 2.00 a 2.50
        r = self.api(self.admin).post(f'/api/listaprecios/multiplicadores/{self.general.id}/simular/', {
            'nuevo_valor': '2.50',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['multiplicador_id'], self.general.id)
        self.assertEqual(Decimal(str(r.data['valor_actual'])), Decimal('2.00'))
        self.assertEqual(Decimal(str(r.data['valor_nuevo'])), Decimal('2.50'))
        self.assertGreaterEqual(r.data['variantes_afectadas'], 2)
        self.assertTrue(len(r.data['ejemplos']) > 0)

        # Vendedor sin EDITAR_LISTA_PRECIOS debe recibir 403
        r_vend = self.api(self.vendedor).post(f'/api/listaprecios/multiplicadores/{self.general.id}/simular/', {
            'nuevo_valor': '2.50',
        }, format='json')
        self.assertEqual(r_vend.status_code, 403)
