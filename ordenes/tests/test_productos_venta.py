from datetime import date
from decimal import Decimal

from listaprecios.models import CargoVariante, CategoriaLista, GrupoTela, LineaProducto, Multiplicador, PrecioVariante, VarianteProducto
from ordenes import nomina
from ordenes.models import DetallePedido, LineaNomina, LineaVenta, OrdenPedido, Venta
from ordenes.tests.utils import LottusTestCase
from suministros.models import Inventario


class ProductosVentaTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', 'administrador')
        self.asesor = self.crear_usuario('asesor')
        self.otro = self.crear_usuario('otro')
        self.permisos('vendedor', ['VER_PROPIAS_VENTAS', 'VER_PRECIOS_VENTA', 'EDITAR_PRODUCTOS_VENTA', 'CREAR_PROPIAS_ORDENES'])
        self.api_admin = self.api(self.admin)
        self.api_asesor = self.api(self.asesor)
        self.prov = self.proveedor()
        self.ref = self.referencia(self.prov)
        cat = CategoriaLista.objects.create(nombre='Sala', slug='sala')
        coleccion = LineaProducto.objects.create(nombre='Sofá', slug='sofa')
        self.variante = VarianteProducto.objects.create(linea=coleccion, categoria=cat, nombre='Tres puestos', costo_base=100, metraje_tela=2)
        self.grupo = GrupoTela.objects.create(nombre='Grupo 1', precio_por_metro=10)
        Multiplicador.objects.filter(es_general=True).update(es_general=False)
        Multiplicador.objects.update_or_create(nombre='General', defaults={'valor': 2, 'es_general': True})
        CargoVariante.objects.create(variante=self.variante, descripcion='Fijo', valor=5)
        self.opcional = CargoVariante.objects.create(variante=self.variante, descripcion='Sin tapa', valor=-10, opcional=True)
        self.v = self.venta(self.asesor, valor='414', fecha=date(2026, 10, 1), abono=200)
        self.url = f'/api/ventas/{self.v.pk}/productos/'

    def fila(self, **extra):
        base = dict(variante=self.variante.pk, grupo_catalogo=self.grupo.pk, referencia=self.ref.pk,
                    cantidad=2, opcionales=[self.opcional.pk], texto_proveedor='Fabricar medidas especiales',
                    texto_cliente='Sofá terminado para tu hogar', tela_modo='incluida', tela_referencia='Lino', tela_color='Arena')
        return {**base, **extra}

    def guardar(self, filas=None, revision=0, confirmar=True, cliente=None, **extra):
        r = (cliente or self.api_asesor).post(self.url, dict(revision=revision, lineas=filas or [self.fila()], confirmar=confirmar, distribuir_total=True, **extra), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def pedir(self, datos, cantidad=2, revision=None):
        return self.api_asesor.post(self.url + 'pedidos/', {'revision': datos['revision'] if revision is None else revision,
            'fecha_esperada': '2026-10-20', 'lineas': [{'linea': datos['lineas'][0]['id'], 'cantidad': cantidad}]}, format='json')

    def test_tela_cargos_negativos_y_total_para_nomina(self):
        d = self.guardar()
        self.assertEqual(Decimal(d['valor_lista']), Decimal(460))  # (100+2*10+5-10)*2 *2 unidades
        l = self.v.lineas.get()
        self.assertEqual((l.precio_lista_unitario, l.costo_estimado, l.subtotal), (Decimal(230), Decimal(115), Decimal(414)))
        self.assertEqual(l.descuento, Decimal(46))
        self.v.refresh_from_db()
        self.assertEqual((self.v.valor_total, self.v.abono), (Decimal(414), Decimal(200)))
        self.assertNotIn('precio_snapshot', d['lineas'][0])
        self.assertNotIn('costo_estimado', d['lineas'][0])
        cierre = nomina.crear_cierre(self.admin, date(2026, 10, 1), date(2026, 10, 5))
        com = LineaNomina.objects.get(asesor_cierre__cierre=cierre, tipo='comision')
        self.assertEqual((com.descuento_pct, com.porcentaje, com.valor, com.pagar, com.origen_precio),
                         (Decimal(10), Decimal('3.60'), Decimal('14.90'), True, 'productos'))
        # Al expandir la venta en Nómina: productos con su precio de lista para validar contra la venta física.
        r = self.api_admin.get(f'/api/nomina/lineas/{com.pk}/venta/')
        self.assertEqual(r.status_code, 200, r.data)
        p = r.data['productos'][0]
        self.assertEqual((p['cantidad'], p['precio_lista_unitario'], p['precio_lista_total'], p['precio_venta'], p['tela']),
                         (2, '230.00', '460.00', '414.00', 'Tela Lino · color Arena'))
        self.assertEqual((r.data['totales']['lista_cuadra'], r.data['totales']['venta_cuadra']), (True, True))
        self.assertEqual(self.api_asesor.get(f'/api/nomina/lineas/{com.pk}/venta/').status_code, 403)

    def test_lista_unificada_asigna_referencia_exacta_y_la_conserva_en_el_pedido(self):
        linea = self.variante.linea
        linea.referencia = self.ref
        linea.save()
        self.vincular_subcategorias_catalogo(linea)
        datos = self.guardar([self.fila(referencia=None)])
        self.assertEqual(self.v.lineas.get().referencia_id, self.ref.pk)
        r = self.pedir(datos)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(DetallePedido.objects.get(linea_venta=self.v.lineas.get()).referencia_id, self.ref.pk)

    def test_lista_unificada_rechaza_otra_referencia_aunque_tenga_el_mismo_nombre(self):
        linea = self.variante.linea
        linea.referencia = self.ref
        linea.save()
        otra = self.referencia(self.proveedor('Fabricante distinto'), self.ref.nombre)
        r = self.api_asesor.post(self.url, dict(revision=0, lineas=[self.fila(referencia=otra.pk)], confirmar=True, distribuir_total=True), format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(self.v.lineas.exists())

    def test_unificar_no_reasigna_ni_bloquea_la_referencia_de_una_venta_historica(self):
        guardado = self.guardar()
        anterior = self.v.lineas.get()
        linea = self.variante.linea
        linea.referencia = self.referencia(self.proveedor('Fabricante del catálogo'), 'Sofá')
        linea.save()
        self.guardar([self.fila(id=anterior.pk)], revision=guardado['revision'])
        anterior.refresh_from_db()
        self.assertEqual(anterior.referencia_id, self.ref.pk)
        self.assertEqual(anterior.precio_lista_unitario, Decimal(230))

    def test_precio_manual_catalogo_y_opcional(self):
        PrecioVariante.objects.create(variante=self.variante, grupo=self.grupo, precio_manual=300)
        self.assertEqual(Decimal(self.guardar()['valor_lista']), Decimal(560))

    def test_congelado_no_cambia_por_editar_textos(self):
        d = self.guardar()
        self.variante.costo_base = 1000
        self.variante.save()
        l = d['lineas'][0]
        l['texto_cliente'] = 'Otro texto de entrega'
        d2 = self.guardar([l], revision=1)
        self.assertEqual(d2['valor_lista'], d['valor_lista'])
        l['recalcular'] = True
        d3 = self.guardar([l], revision=2)
        self.assertEqual(Decimal(d3['valor_lista']), Decimal(4060))

    def test_faltantes_y_grupos_invalidos_no_persisten(self):
        fila = self.fila()
        fila['grupo_catalogo'] = None
        r = self.api_asesor.post(self.url, {'revision': 0, 'lineas': [fila], 'confirmar': True}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.v.lineas.exists())
        # Sin texto para el proveedor hay que marcar "No aplica" (regla 2026-10-07).
        fila = self.fila(texto_proveedor='')
        r = self.api_asesor.post(self.url, {'revision': 0, 'lineas': [fila]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('texto_proveedor', str(r.data))
        self.assertFalse(self.v.lineas.exists())
        d = self.guardar([self.fila(texto_proveedor='', sin_texto_proveedor=True)])
        self.assertTrue(d['lineas'][0]['sin_texto_proveedor'])

    def test_revision_idempotencia_y_alcance_antes_de_cache(self):
        body = {'revision': 0, 'lineas': [self.fila()], 'confirmar': True, 'distribuir_total': True}
        a = self.api_asesor.post(self.url, body, format='json', HTTP_IDEMPOTENCY_KEY='prueba-productos')
        b = self.api_asesor.post(self.url, body, format='json', HTTP_IDEMPOTENCY_KEY='prueba-productos')
        self.assertEqual(a.data, b.data)
        self.assertEqual(self.v.lineas.count(), 1)
        self.assertEqual(self.api_asesor.post(self.url, body, format='json').status_code, 409)
        Venta.objects.filter(pk=self.v.pk).update(vendedor=self.otro)
        self.assertEqual(self.api_asesor.post(self.url, body, format='json', HTTP_IDEMPOTENCY_KEY='prueba-productos').status_code, 404)

    def test_compartida_permiso_y_excepcion_con_motivo(self):
        self.assertEqual(self.api(self.otro).get(self.url).status_code, 404)
        self.v.vendedores_compartidos.add(self.otro)
        self.assertEqual(self.api(self.otro).get(self.url).status_code, 200)
        especial = {'producto_nombre': 'Accesorio fuera del catálogo', 'cantidad': 1, 'precio_lista_override': '500', 'motivo_precio': 'Fabricación especial', 'sin_texto_proveedor': True,
                    'referencia': self.ref.pk, 'texto_cliente': 'Accesorio', 'tela_modo': 'no_aplica'}
        self.assertEqual(self.api_asesor.post(self.url, {'revision': 0, 'lineas': [especial]}, format='json').status_code, 403)
        especial['motivo_precio'] = ''
        self.assertEqual(self.api_admin.post(self.url, {'revision': 0, 'lineas': [especial]}, format='json').status_code, 400)
        especial['motivo_precio'] = 'Autorizado producto único'
        d = self.guardar([especial], cliente=self.api_admin)
        self.assertEqual(Decimal(d['valor_lista']), Decimal(500))
        self.assertIsNone(self.v.lineas.get().costo_estimado)

    def test_recargo_final_y_costo_desconocido(self):
        # El recargo ya dice qué es: no pide un "motivo" aparte (2026-10-08).
        fila = self.fila(adicionales=[{'descripcion': 'Instalación extraordinaria', 'importe_lista': '30'}])
        r = self.api_admin.post(self.url + 'calcular/', {**fila, 'cantidad': 1}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(r.data['precio_lista_unitario']), Decimal(260))
        d = self.guardar([fila], cliente=self.api_admin)
        self.assertEqual(Decimal(d['valor_lista']), Decimal(520))
        self.assertIsNone(self.v.lineas.get().costo_estimado)
        self.assertEqual(self.api_asesor.post(self.url + 'calcular/', {**fila, 'cantidad': 1}, format='json').status_code, 403)

    def test_pedidos_parciales_no_duplicados_y_ruta_clasica(self):
        d = self.guardar()
        r = self.pedir(d, 1)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.pedir(d).status_code, 409)
        d = self.api_asesor.get(self.url).data
        self.assertEqual(d['lineas'][0]['por_pedir'], 1)
        self.assertEqual(self.pedir(d, 2).status_code, 409)
        self.assertEqual(self.pedir(d, 1).status_code, 201)
        self.assertEqual(self.api_admin.post('/api/ordenes-pedido/', {'proveedor': self.prov.pk, 'venta': self.v.pk,
            'fecha_esperada': '2026-10-20', 'detalles': [{'referencia': self.ref.pk, 'linea_venta': self.v.lineas.get().pk, 'cantidad': 1}]}, format='json').status_code, 400)
        self.assertEqual(DetallePedido.objects.count(), 2)
        d = self.api_asesor.get(self.url).data
        fila = d['lineas'][0]; fila['cantidad'] = 1
        self.assertEqual(self.api_asesor.post(self.url, {'revision': d['revision'], 'lineas': [fila]}, format='json').status_code, 400)
        self.assertEqual(self.api_asesor.post(self.url, {'revision': d['revision'], 'lineas': []}, format='json').status_code, 400)

    def test_pedido_reintentado_devuelve_los_mismos_ids(self):
        d = self.guardar()
        body = {'revision': d['revision'], 'fecha_esperada': '2026-10-20', 'lineas': [{'linea': d['lineas'][0]['id'], 'cantidad': 2}]}
        a = self.api_asesor.post(self.url + 'pedidos/', body, format='json', HTTP_IDEMPOTENCY_KEY='pedido')
        b = self.api_asesor.post(self.url + 'pedidos/', body, format='json', HTTP_IDEMPOTENCY_KEY='pedido')
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(a.data, b.data)
        self.assertEqual(OrdenPedido.objects.count(), 1)

    def test_flujo_venta_pedido_recepcion_remision_nomina(self):
        d = self.guardar()
        r = self.pedir(d)
        self.assertEqual(r.status_code, 201, r.data)
        pedido = r.data['ordenes'][0]
        # La remisión trae el tapizado de la venta: material, referencia y color (sin proveedor ni metraje).
        pend = self.api_admin.get('/api/suministros/remisiones/datos-ventas/', {'ids': str(self.v.pk)}).data[0]['pedidos'][0]
        self.assertEqual(pend['tela'], 'Tela Lino · color Arena')
        preparacion = self.api_admin.get(f'/api/productos-venta/pedidos/{pedido}/recepcion/').data
        detalle = preparacion['productos'][0]['detalle_pedido']
        self.assertEqual(preparacion['productos'][0]['cantidad'], 2)
        for i in range(2):
            r = self.api_admin.post('/api/suministros/facturas/', {'id_manual': f'FA-{i}', 'proveedor': self.prov.pk, 'valor': '100',
                'productos': [{'referencia': self.ref.pk, 'costo': '100', 'cantidad': 1, 'detalle_pedido': detalle}]}, format='json')
            self.assertEqual(r.status_code, 201, r.data)
            if i == 0:
                r = self.api_admin.get(f'/api/productos-venta/pedidos/{pedido}/recepcion/')
                self.assertEqual(r.data['productos'][0]['cantidad'], 1)
        self.assertEqual(self.api_admin.get(f'/api/productos-venta/pedidos/{pedido}/recepcion/').data['productos'], [])
        r = self.api_admin.get('/api/suministros/remisiones/datos-ventas/', {'ids': str(self.v.pk)})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data[0]['inventario'][0]['texto_cliente'], 'Sofá terminado para tu hogar')
        self.assertEqual(r.data[0]['inventario'][0]['tela'], 'Tela Lino · color Arena')
        self.assertEqual(DetallePedido.objects.get(pk=detalle).especificaciones, 'Fabricar medidas especiales')
        items = list(Inventario.objects.values_list('pk', flat=True))
        r = self.api_admin.post('/api/suministros/remisiones/', {'ventas': [self.v.pk], 'inventario_items': items,
            'descripciones_inventario': {pk: 'Sofá para cliente' for pk in items},
            'telas_inventario': {pk: 'Tela Lino · color Arena' for pk in items}, 'fecha_entrega': '2026-10-20',
            'nombre_destinatario': 'Cliente ficticio', 'direccion_entrega': 'Calle ficticia'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual({i['tela_remision'] for i in r.data['inventario_items_detalle']}, {'Tela Lino · color Arena'})
        rem = r.data['id']
        r = self.api_admin.patch(f'/api/suministros/remisiones/{rem}/', {'estado': 'finalizada', 'cerrar_ventas': [self.v.pk]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.v.refresh_from_db(); self.assertEqual(self.v.estado, 'entregado')
        cierre = nomina.crear_cierre(self.admin, date(2026, 10, 1), date(2026, 10, 5))
        c = LineaNomina.objects.get(tipo='comision', asesor_cierre__cierre=cierre)
        self.assertEqual(c.precio_lista, Decimal(460))
        nomina.cerrar(cierre.pk, self.admin)
        congelado = c.valor
        d = self.api_admin.get(self.url).data
        fila = d['lineas'][0]; fila.update(precio_lista_override='300', motivo_precio='Corrección posterior')
        self.guardar([fila], revision=d['revision'], cliente=self.api_admin)
        c.refresh_from_db(); self.assertEqual(c.valor, congelado)

    def test_sin_productos_la_comision_queda_pendiente_y_al_guardarlos_se_calcula(self):
        cierre = nomina.crear_cierre(self.admin, date(2026, 10, 1), date(2026, 10, 5))
        c = LineaNomina.objects.get(tipo='comision', asesor_cierre__cierre=cierre)
        self.assertEqual((c.pagar, c.porcentaje, c.valor), (False, None, Decimal(0)))
        r = self.api_admin.patch(f'/api/nomina/lineas/{c.pk}/', {'pagar': True}, format='json')
        self.assertEqual(r.status_code, 400)
        # Guardar los productos basta: el precio es global y el descuento se calcula solo.
        d = self.guardar()
        self.assertEqual(self.pedir(d).status_code, 201)
        nomina.regenerar(cierre.pk, self.admin)
        c = LineaNomina.objects.get(tipo='comision', asesor_cierre__cierre=cierre)
        self.assertTrue(c.pagar)
        self.assertEqual(c.origen_precio, 'productos')
        self.assertEqual(self.api_admin.patch(f'/api/nomina/lineas/{c.pk}/', {'precio_lista': '1000'}, format='json').status_code, 400)

    def test_referencia_de_compra_se_infiere_del_producto(self):
        from ordenes.models import Referencia
        sugerida = Referencia.objects.create(proveedor=self.prov, nombre='Sofá')
        d = self.guardar([self.fila(referencia=None)])
        self.assertEqual(d['lineas'][0]['referencia'], sugerida.pk)
        r = self.api_asesor.get('/api/productos-venta/catalogo/', {'id': self.variante.pk})
        self.assertEqual(r.data['results'][0]['referencias'][0]['id'], sugerida.pk)

    def test_cabecera_no_reemplaza_precio_de_lista_y_cambio_de_total_se_reparte(self):
        self.guardar()
        url = f'/api/ventas/{self.v.pk}/editar/'
        r = self.api_admin.put(url, {'venta': {'valor_lista': '1'}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.v.refresh_from_db()
        self.assertEqual(self.v.valor_lista, Decimal(460))
        r = self.api_admin.put(url, {'venta': {'valor_total': '400'}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.v.refresh_from_db()
        self.assertTrue(self.v.productos_confirmados)
        self.assertEqual(self.v.valor_lista, Decimal(460))
        self.assertEqual(sum(l.subtotal for l in self.v.lineas.all()), Decimal(400))

    def test_stock_asignado_no_genera_compra_y_no_duplica_unidad(self):
        item = Inventario.objects.create(id_referencia='STOCK-001', referencia=self.ref, venta=self.v)
        fila = self.fila(inventario_origen=item.pk); fila['cantidad'] = 1
        d = self.guardar([fila], cliente=self.api_admin)
        self.assertEqual(d['lineas'][0]['por_pedir'], 0)
        self.assertEqual(self.pedir(d, 1).status_code, 409)
        fila2 = dict(fila)
        self.assertEqual(self.api_admin.post(self.url, {'revision': 1, 'lineas': [dict(d['lineas'][0]), fila2]}, format='json').status_code, 400)

    def test_catalogo_completo_paginado_sin_costos(self):
        for n in range(43):
            VarianteProducto.objects.create(linea=self.variante.linea, categoria=self.variante.categoria, nombre=f'Extra{n}', costo_base=88)
        self.vincular_subcategorias_catalogo(self.variante.linea)
        r = self.api_asesor.get('/api/productos-venta/catalogo/', {'page': 2})
        self.assertEqual((r.status_code, r.data['count'], len(r.data['results'])), (200, 44, 4))
        self.assertNotIn('costo_base', str(r.data))
        self.assertEqual(self.api_asesor.get('/api/productos-venta/catalogo/', {'page': 'bad'}).status_code, 400)

    def test_descripcion_cliente_no_cambia_pedido_creado(self):
        d = self.guardar(); self.pedir(d)
        d = self.api_asesor.get(self.url).data
        fila = d['lineas'][0]; fila.update(texto_cliente='Nuevo texto cliente', texto_proveedor='Cambio para un futuro pedido')
        self.guardar([fila], revision=d['revision'])
        self.assertEqual(DetallePedido.objects.get().especificaciones, 'Fabricar medidas especiales')

    def test_historicos_se_vinculan_sin_repetir_compra(self):
        orden = OrdenPedido.objects.create(proveedor=self.prov, usuario=self.admin, venta=self.v, fecha_esperada=date.today())
        detalle = DetallePedido.objects.create(orden=orden, referencia=self.ref, cantidad=2, especificaciones='Texto histórico proveedor')
        d = self.guardar()
        self.assertEqual(self.pedir(d).status_code, 409)
        r = self.api_asesor.post(self.url + 'vincular-pedidos/', {'revision': d['revision'],
            'vinculos': [{'detalle': detalle.pk, 'linea': d['lineas'][0]['id']}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['lineas'][0]['por_pedir'], 0)
        detalle.refresh_from_db()
        self.assertEqual(detalle.especificaciones, 'Texto histórico proveedor')
        self.assertEqual(detalle.linea_venta_id, d['lineas'][0]['id'])
        self.assertEqual(OrdenPedido.objects.count(), 1)

    def test_distribucion_de_centavos_nunca_deja_ultima_linea_negativa(self):
        Venta.objects.filter(pk=self.v.pk).update(valor_total='0.02', saldo='0.02', abono=0)
        filas = [{'producto_nombre': f'Accesorio {i}', 'cantidad': 1, 'precio_lista_override': '1', 'motivo_precio': 'Prueba de centavos', 'sin_texto_proveedor': True, 'referencia': self.ref.pk, 'texto_cliente': 'Accesorio', 'tela_modo': 'no_aplica'} for i in range(6)]
        d = self.guardar(filas, cliente=self.api_admin)
        valores = [Decimal(l['subtotal']) for l in d['lineas']]
        self.assertEqual(sum(valores), Decimal('0.02'))
        self.assertGreaterEqual(min(valores), 0)

    def test_tela_de_cuero_en_productos_de_pedido_de_la_remision(self):
        cuero = GrupoTela.objects.create(nombre='Cuero nacional', tipo='cuero', precio_por_metro=3)
        d = self.guardar([self.fila(tela_material='cuero', tela_referencia='Napoli', tela_color='Café', tela_grupo=cuero.pk)])
        self.assertEqual(self.pedir(d).status_code, 201)
        pend = self.api_admin.get('/api/suministros/remisiones/datos-ventas/', {'ids': str(self.v.pk)}).data[0]['pedidos'][0]
        self.assertEqual(pend['tela'], 'Cuero Napoli · color Café')
        r = self.api_admin.post('/api/suministros/remisiones/', {'ventas': [self.v.pk], 'fecha_entrega': '2026-10-20',
            'direccion_entrega': 'Calle ficticia', 'items_manuales': [{'referencia': 'Sofá', 'cantidad': 2, 'tela': pend['tela'],
            'venta': self.v.pk, 'detalle_pedido': pend['detalle_id']}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['items_manuales'][0]['tela'], 'Cuero Napoli · color Café')
        # Sin tela (no aplica o sin datos) no se sugiere tapizado.
        from ordenes.gestion_venta import texto_tela
        self.assertEqual(texto_tela(LineaVenta(tela_modo='no_aplica', tela_referencia='Lino')), '')
        self.assertEqual(texto_tela(LineaVenta(tela_modo='aparte')), '')
