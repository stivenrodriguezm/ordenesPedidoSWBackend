from decimal import Decimal

from ordenes.tests.utils import LottusTestCase
from .models import CategoriaLista, CargoVariante, EspecialCatalogo, GrupoTela, LineaProducto, Multiplicador, PrecioVariante, VarianteProducto
from .services import calcular_precio, costo_lista, opcionales_de_variante


class AgrupacionesYOrdenTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General', valor=2, es_general=True)
        self.admin = self.crear_usuario('admin_agrupaciones', 'administrador')
        self.c = self.api(self.admin)
        self.cat = CategoriaLista.objects.create(nombre='Comedores prueba', slug='comedores-prueba')
        self.linea = LineaProducto.objects.create(nombre='Conjunto prueba', slug='conjunto-prueba')
        self.mesa = VarianteProducto.objects.create(linea=self.linea, categoria=self.cat, nombre='Mesa', costo_base=500000, orden=2)
        self.silla = VarianteProducto.objects.create(linea=self.linea, categoria=self.cat, nombre='Silla', costo_base=100000, metraje_tela=1, decimetraje_cuero=30, orden=4)
        self.juego = VarianteProducto.objects.create(linea=self.linea, categoria=self.cat, nombre='Comedor de 6', costo_base=0, orden=6)
        self.grupo = GrupoTela.objects.create(nombre='Grupo prueba', precio_por_metro=10000)
        self.piezas = [{'variante': self.mesa.pk, 'cantidad': 1}, {'variante': self.silla.pk, 'cantidad': 6}]

    def armar(self, piezas=None):
        return self.c.put(f'/api/listaprecios/variantes/{self.juego.pk}/componentes/', {'componentes': self.piezas if piezas is None else piezas}, format='json')

    def test_costos_y_multiplos_son_exclusivos_del_conjunto_y_no_se_duplican(self):
        CargoVariante.objects.create(variante=self.silla, descripcion='Instalación', valor=2000)
        self.piezas[1].update(costo_unitario='80000', multiplicador='1.5')
        r = self.armar()
        self.assertEqual(r.status_code, 200, r.data)
        juego = VarianteProducto.objects.get(pk=self.juego.pk)
        self.assertEqual(calcular_precio(juego, self.grupo), Decimal('1828000'))
        self.assertEqual(costo_lista(juego, self.grupo), Decimal('1052000'))
        self.silla.refresh_from_db()
        self.assertEqual(self.silla.costo_base, 100000)
        self.assertIsNone(self.silla.multiplicador)
        self.assertEqual(calcular_precio(self.silla, self.grupo), Decimal('224000'))
        # El margen del conjunto solo se aplica a sus cargos propios; su costo base guardado no cuenta.
        juego.costo_base = 10000
        juego.multiplicador = Multiplicador.objects.create(nombre='Propio', valor=3)
        juego.save()
        self.assertEqual(calcular_precio(juego, self.grupo), Decimal('1828000'))
        CargoVariante.objects.create(variante=juego, descripcion='Costo propio', valor=10000)
        self.assertEqual(calcular_precio(juego, self.grupo), Decimal('1858000'))

    def test_costo_cero_es_explicito_y_nulos_vuelven_a_heredar(self):
        self.piezas[1]['costo_unitario'] = '0'
        self.assertEqual(self.armar().status_code, 200)
        self.assertEqual(calcular_precio(VarianteProducto.objects.get(pk=self.juego.pk), self.grupo), Decimal('1120000'))
        self.piezas[1]['costo_unitario'] = None
        self.piezas[1]['multiplicador'] = None
        self.assertEqual(self.armar().status_code, 200)
        self.silla.costo_base = 120000
        self.silla.save()
        self.assertEqual(calcular_precio(VarianteProducto.objects.get(pk=self.juego.pk), self.grupo), Decimal('2560000'))

    def test_costos_propios_conservan_cuero_y_respetan_precio_manual_sin_ajustes(self):
        cuero = GrupoTela.objects.create(nombre='Cuero prueba', tipo='cuero', precio_por_metro=2000)
        PrecioVariante.objects.create(variante=self.silla, grupo=cuero, precio_manual=500000)
        self.armar()
        self.assertEqual(calcular_precio(VarianteProducto.objects.get(pk=self.juego.pk), cuero), Decimal('4000000'))
        self.piezas[1].update(costo_unitario='80000', multiplicador='1.5')
        self.armar()
        self.assertEqual(calcular_precio(VarianteProducto.objects.get(pk=self.juego.pk), cuero), Decimal('2260000'))
        self.assertEqual(PrecioVariante.objects.get(variante=self.silla, grupo=cuero).precio_manual, 500000)

    def test_rechaza_entradas_invalidas_sin_borrar_la_agrupacion_anterior(self):
        self.armar()
        for patch in ({'costo_unitario': '12.50'}, {'costo_unitario': '-1'}, {'costo_unitario': 'NaN'},
                      {'multiplicador': '0'}, {'multiplicador': '1.1234'}, {'cantidad': 1.5}, {'cantidad': True}):
            with self.subTest(patch=patch):
                piezas = [self.piezas[0], {**self.piezas[1], **patch}]
                r = self.armar(piezas)
                self.assertEqual(r.status_code, 400, r.data)
                self.assertEqual(list(self.juego.componentes.values_list('cantidad', flat=True)), [1, 6])
        for payload in ({}, {'componentes': None}, {'componentes': {}}):
            r = self.c.put(f'/api/listaprecios/variantes/{self.juego.pk}/componentes/', payload, format='json')
            self.assertEqual(r.status_code, 400, r.data)
            self.assertEqual(self.juego.componentes.count(), 2)

    def test_simular_no_escribe_y_coincide_con_el_guardado(self):
        self.piezas[1].update(costo_unitario='80000', multiplicador='1.5')
        r = self.c.post(f'/api/listaprecios/variantes/{self.juego.pk}/simular-componentes/', {'componentes': self.piezas}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(self.juego.componentes.exists())
        guardado = self.armar()
        self.assertEqual(r.data['precios_venta'], guardado.data['precios_venta'])

    def test_total_suma_piezas_cantidades_cargos_y_especiales_sin_repetir_margen(self):
        self.juego.costo_base = 10000
        self.juego.save()
        CargoVariante.objects.create(variante=self.juego, descripcion='Costo propio', valor=5000)
        CargoVariante.objects.create(variante=self.silla, descripcion='Instalación', valor=2000)
        CargoVariante.objects.create(variante=self.silla, descripcion='Base metálica', valor=5000)
        self.piezas[1]['adicionales'] = [
            {'tipo': 'especial', 'nombre': 'Acabado especial', 'configuracion': {'costo_base': '10000', 'multiplicador': '1.5'}},
        ]
        r = self.armar()
        self.assertEqual(r.status_code, 200, r.data)
        # Sin el costo base del conjunto (10.000): solo piezas, sus cargos, especiales y cargos propios.
        self.assertEqual(Decimal(r.data['costo_total_producto']), Decimal('1207000'))
        juego = VarianteProducto.objects.get(pk=self.juego.pk)
        self.assertEqual(costo_lista(juego, self.grupo), Decimal('1267000'))
        self.assertEqual(calcular_precio(juego, self.grupo), Decimal('2504000'))
        self.assertEqual(self.silla.cargos.count(), 2)
        self.silla.refresh_from_db()
        self.assertEqual(self.silla.costo_base, 100000)

    def test_especiales_por_pieza_tienen_consumos_independientes_y_margen_propio(self):
        cuero = GrupoTela.objects.create(nombre='Cuero extra', tipo='cuero', precio_por_metro=2000)
        config = {'costo_base': '10000', 'multiplicador': '1.5', 'metraje_tela': '2', 'decimetraje_cuero': '30'}
        self.piezas[1]['adicionales'] = [{'tipo': 'especial', 'nombre': 'Tapizado especial', 'configuracion': config}]
        r = self.armar()
        self.assertEqual(r.status_code, 200, r.data)
        juego = VarianteProducto.objects.get(pk=self.juego.pk)
        self.assertEqual(calcular_precio(juego, self.grupo), Decimal('2590000'))
        self.assertEqual(calcular_precio(juego, cuero), Decimal('3550000'))
        self.assertEqual(costo_lista(juego, cuero), Decimal('1880000'))
        self.assertEqual(Decimal(r.data['costo_total_producto']), Decimal('1160000'))
        config['decimetraje_cuero'] = None
        r = self.armar()
        self.assertEqual([p['grupo'] for p in r.data['precios_venta']], [self.grupo.pk])

    def test_simular_informa_costos_y_no_archiva_especiales_hasta_guardar(self):
        self.vincular_subcategorias_catalogo(self.linea)
        self.piezas[1]['adicionales'] = [{'tipo': 'especial', 'nombre': 'Motor para el conjunto', 'configuracion': {'costo_base': '10000', 'multiplicador': '3'}}]
        antes = EspecialCatalogo.objects.count()
        r = self.c.post(f'/api/listaprecios/variantes/{self.juego.pk}/simular-componentes/', {'componentes': self.piezas}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(EspecialCatalogo.objects.count(), antes)
        self.assertEqual(Decimal(r.data['costo_total_producto']), Decimal('1160000'))
        self.assertEqual(Decimal(r.data['costos_por_grupo'][0]['costo']), Decimal('1220000'))
        self.assertEqual(self.armar().status_code, 200)
        self.assertEqual(EspecialCatalogo.objects.filter(nombre='Motor para el conjunto').count(), 1)
        publico = self.c.get('/api/listaprecios/catalogo/', {'q': self.linea.nombre}).data
        self.assertIn('Motor para el conjunto', next(v for v in publico[0]['variantes'] if v['id'] == self.juego.pk)['componentes'])
        self.assertNotIn('costo_total_producto', publico[0]['variantes'][0])

    def test_adicional_con_tela_habilita_grupos_en_una_pieza_sin_tela(self):
        piezas = [{'variante': self.mesa.pk, 'cantidad': 1, 'adicionales': [{'tipo': 'especial', 'nombre': 'Funda', 'configuracion': {'costo_base': '10000', 'multiplicador': '1.5', 'metraje_tela': '2'}}]}]
        r = self.armar(piezas)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['precios_venta'][0]['grupo'], self.grupo.pk)
        self.assertEqual(Decimal(r.data['precios_venta'][0]['precio']), Decimal('1045000'))
        self.assertEqual(Decimal(r.data['costo_total_producto']), Decimal('510000'))

    def test_omitir_adicionales_conserva_los_guardados_y_lista_vacia_los_quita(self):
        self.piezas[1]['adicionales'] = [{'tipo': 'especial', 'nombre': 'Funda', 'configuracion': {'costo_base': '5000', 'multiplicador': '1.5'}}]
        self.armar()
        del self.piezas[1]['adicionales']
        r = self.armar()
        self.assertEqual(len(r.data['componentes'][1]['adicionales']), 1)
        self.piezas[1]['adicionales'] = []
        r = self.armar()
        self.assertEqual(r.data['componentes'][1]['adicionales'], [])

    def test_adicionales_invalidos_o_descuento_excesivo_no_alteran_la_composicion(self):
        self.armar()
        for extra in (
            {'tipo': 'cargo', 'nombre': '', 'costo': '100'},
            {'tipo': 'cargo', 'nombre': 'Base', 'costo': '100.50'},
            {'tipo': 'cargo', 'nombre': 'Base', 'costo': 'NaN'},
            {'tipo': 'especial', 'nombre': 'Inválido', 'configuracion': {'costo_base': '-1'}},
            {'tipo': 'especial', 'nombre': 'Baja excesiva', 'configuracion': {'costo_base': '9999999', 'sentido': 'baja', 'multiplicador': '2'}},
        ):
            with self.subTest(extra=extra):
                self.piezas[1]['adicionales'] = [extra]
                r = self.armar()
                self.assertEqual(r.status_code, 400, r.data)
                self.assertEqual(self.juego.componentes.get(variante=self.silla).adicionales, [])

    def test_los_cargos_de_la_pieza_son_los_del_producto_y_no_se_crean_por_conjunto(self):
        self.armar()
        self.piezas[1]['adicionales'] = [{'tipo': 'cargo', 'nombre': 'Base', 'costo': '5000'}]
        r = self.armar()
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('producto original', str(r.data))
        # Un cargo agregado a la pieza (desde la agrupación o desde su referencia) es el mismo en ambos.
        r = self.c.post('/api/listaprecios/cargos/', {'variante': self.silla.pk, 'descripcion': 'Instalación', 'valor': '2000'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        juego = VarianteProducto.objects.get(pk=self.juego.pk)
        self.assertEqual(calcular_precio(juego, self.grupo), Decimal('2320000') + 2000 * 2 * 6)

    def test_el_conjunto_ofrece_los_opcionales_de_sus_piezas_por_cantidad(self):
        self.vincular_subcategorias_catalogo(self.linea)
        usb = CargoVariante.objects.create(variante=self.silla, descripcion='USB', valor=3000, opcional=True, preseleccionado=True)
        self.armar()
        juego = VarianteProducto.objects.get(pk=self.juego.pk)
        op = next(o for o in opcionales_de_variante(juego) if o['id'] == usb.pk)
        self.assertEqual((op['descripcion'], op['valor'], op['preseleccionado']), ('USB · Silla ×6', Decimal('36000'), True))
        base = calcular_precio(juego, self.grupo, set())
        self.assertEqual(calcular_precio(juego, self.grupo, {usb.pk}) - base, Decimal('36000'))
        self.assertEqual(costo_lista(juego, self.grupo, [usb.pk]) - costo_lista(juego, self.grupo, []), Decimal('18000'))
        # Habilitado: el precio de lista, el costo total y la venta por grupo ya lo incluyen.
        self.assertEqual(calcular_precio(juego, self.grupo), base + 36000)
        r = self.c.get(f'/api/listaprecios/variantes/{self.juego.pk}/').data
        self.assertEqual(Decimal(r['costo_total_producto']), Decimal('1100000') + 18000)
        self.assertEqual(Decimal(next(p['precio'] for p in r['precios_venta'] if p['grupo'] == self.grupo.pk)), base + 36000)
        r = self.c.get(f'/api/listaprecios/variantes/{self.juego.pk}/precio/', {'grupo': self.grupo.pk, 'opcionales': str(usb.pk)})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(r.data['precio']), base + 36000)
        # Si el vendedor lo quita, el precio baja.
        r = self.c.get(f'/api/listaprecios/variantes/{self.juego.pk}/precio/', {'grupo': self.grupo.pk})
        self.assertEqual(Decimal(r.data['precio']), base)
        # Con precio manual en el conjunto, el opcional de la pieza se suma encima.
        PrecioVariante.objects.create(variante=self.juego, grupo=self.grupo, precio_manual=2000000)
        juego = VarianteProducto.objects.get(pk=self.juego.pk)
        self.assertEqual(calcular_precio(juego, self.grupo, {usb.pk}), Decimal('2036000'))
        self.assertEqual(calcular_precio(juego, self.grupo, set()), Decimal('2000000'))

    def test_opcional_habilitado_de_un_producto_entra_en_su_precio_y_costo_de_lista(self):
        luz = CargoVariante.objects.create(variante=self.silla, descripcion='Luz', valor=10000, opcional=True, preseleccionado=True)
        CargoVariante.objects.create(variante=self.silla, descripcion='Brazos', valor=5000, opcional=True)
        silla = VarianteProducto.objects.get(pk=self.silla.pk)
        # (100.000 + 1 m × 10.000 + 10.000 habilitado) × 2; el deshabilitado no cuenta.
        self.assertEqual(calcular_precio(silla, self.grupo), Decimal('240000'))
        self.assertEqual(costo_lista(silla, self.grupo), Decimal('120000'))
        self.assertEqual(calcular_precio(silla, self.grupo, []), Decimal('220000'))
        self.assertEqual(calcular_precio(silla, self.grupo, {luz.pk}), Decimal('240000'))

    def test_estado_del_cargo_habilitado_deshabilitado_u_obligatorio(self):
        self.vincular_subcategorias_catalogo(self.linea)
        r = self.c.post('/api/listaprecios/cargos/', {'variante': self.silla.pk, 'descripcion': 'USB', 'valor': '3000', 'opcional': True, 'preseleccionado': True}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['preseleccionado'])
        r = self.c.patch(f"/api/listaprecios/cargos/{r.data['id']}/", {'opcional': True, 'preseleccionado': False}, format='json')
        self.assertFalse(r.data['preseleccionado'])
        r = self.c.patch(f"/api/listaprecios/cargos/{r.data['id']}/", {'preseleccionado': True}, format='json')
        self.assertTrue(r.data['preseleccionado'])
        # Obligatorio: deja de ser opcional y nunca queda «seleccionado de entrada».
        r = self.c.patch(f"/api/listaprecios/cargos/{r.data['id']}/", {'opcional': False, 'preseleccionado': True}, format='json')
        self.assertEqual((r.data['opcional'], r.data['preseleccionado']), (False, False))
        publico = self.c.get('/api/listaprecios/catalogo/', {'q': self.linea.nombre}).data
        self.assertEqual(next(v for v in publico[0]['variantes'] if v['id'] == self.silla.pk)['opcionales'], [])

    def test_un_calculo_invalido_no_deja_escrita_una_composicion_parcial(self):
        self.armar()
        CargoVariante.objects.create(variante=self.silla, descripcion='Ajuste de costo', valor=-90000)
        piezas = [self.piezas[0], {**self.piezas[1], 'costo_unitario': '0'}]
        r = self.armar(piezas)
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIsNone(self.juego.componentes.get(variante=self.silla).costo_unitario)

    def test_crea_un_conjunto_completo_atomico_y_al_final_del_orden(self):
        cantidad = self.linea.variantes.count()
        simulado = self.c.post(f'/api/listaprecios/lineas/{self.linea.pk}/simular-agrupacion/', {'componentes': self.piezas}, format='json')
        self.assertEqual(simulado.status_code, 200, simulado.data)
        self.assertEqual(self.linea.variantes.count(), cantidad)
        r = self.c.post(f'/api/listaprecios/lineas/{self.linea.pk}/agrupaciones/', {'nombre': 'Comedor nuevo', 'categoria': self.cat.pk, 'componentes': self.piezas}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['precios_venta'], simulado.data['precios_venta'])
        self.assertEqual(r.data['orden'], 7)
        r = self.c.post(f'/api/listaprecios/lineas/{self.linea.pk}/agrupaciones/', {'nombre': 'Inválido', 'categoria': self.cat.pk, 'componentes': [{'variante': self.mesa.pk, 'cantidad': 0}]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.linea.variantes.count(), cantidad + 1)

    def test_el_orden_se_guarda_completo_y_es_igual_en_el_catalogo(self):
        self.vincular_subcategorias_catalogo(self.linea)
        anteriores = [self.mesa.pk, self.silla.pk, self.juego.pk]
        nuevos = [self.juego.pk, self.mesa.pk, self.silla.pk]
        r = self.c.post(f'/api/listaprecios/lineas/{self.linea.pk}/orden-variantes/', {'variantes': nuevos, 'orden_anterior': anteriores}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        admin = self.c.get(f'/api/listaprecios/lineas/{self.linea.pk}/').data
        self.assertEqual([v['id'] for v in admin['variantes']], nuevos)
        publico = self.c.get('/api/listaprecios/catalogo/', {'q': self.linea.nombre}).data
        self.assertEqual([v['id'] for v in publico[0]['variantes']], nuevos)
        # Una sesión desactualizada no sobrescribe el orden nuevo.
        r = self.c.post(f'/api/listaprecios/lineas/{self.linea.pk}/orden-variantes/', {'variantes': anteriores, 'orden_anterior': anteriores}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(list(self.linea.variantes.values_list('pk', flat=True)), nuevos)

    def test_orden_rechaza_duplicados_omisiones_y_productos_ajenos_sin_cambios(self):
        anteriores = list(self.linea.variantes.values_list('pk', flat=True))
        for ids in ([self.mesa.pk, self.mesa.pk, self.juego.pk], [self.mesa.pk], [999999, self.silla.pk, self.juego.pk]):
            r = self.c.post(f'/api/listaprecios/lineas/{self.linea.pk}/orden-variantes/', {'variantes': ids, 'orden_anterior': anteriores}, format='json')
            self.assertEqual(r.status_code, 409, r.data)
            self.assertEqual(list(self.linea.variantes.values_list('pk', flat=True)), anteriores)

    def test_vendedor_no_puede_reordenar_ni_modificar_agrupaciones(self):
        vendedor = self.crear_usuario('vendedor_agrupaciones')
        c = self.api(vendedor)
        for url, payload in ((f'/api/listaprecios/lineas/{self.linea.pk}/orden-variantes/', {'variantes': [self.mesa.pk], 'orden_anterior': [self.mesa.pk]}),
                             (f'/api/listaprecios/lineas/{self.linea.pk}/agrupaciones/', {'nombre': 'No', 'categoria': self.cat.pk, 'componentes': self.piezas}),
                             (f'/api/listaprecios/variantes/{self.juego.pk}/simular-componentes/', {'componentes': self.piezas})):
            self.assertEqual(c.post(url, payload, format='json').status_code, 403)

    def test_conjunto_sin_tela_con_grupos_que_no_aplican_tiene_precio_unico(self):
        self.armar([{'variante': self.mesa.pk, 'cantidad': 2}])
        PrecioVariante.objects.create(variante=self.juego, grupo=self.grupo)
        juego = VarianteProducto.objects.get(pk=self.juego.pk)
        from .services import precios_por_variante
        self.assertEqual(precios_por_variante(juego), [{'grupo': None, 'grupo_nombre': None, 'precio': Decimal('2000000')}])
