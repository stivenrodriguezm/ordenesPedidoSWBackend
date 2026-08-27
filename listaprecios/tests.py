from decimal import Decimal

from django.test import TestCase

from .models import (
    CategoriaLista, GrupoTela, Multiplicador,
    LineaProducto, VarianteProducto, CargoVariante, PrecioVariante,
)
from .services import (
    calcular_precio, precios_por_variante, impacto_categoria, impacto_multiplicador,
    opcionales_de_variante, multiplicador_efectivo, obtener_multiplicador_general,
    establecer_multiplicador_general, asignar_multiplicador_masivo,
)


class CalcularPrecioTests(TestCase):
    def setUp(self):
        # La migración de datos 0006 ya siembra un Multiplicador "General"
        # al aplicar las migraciones (incluida la base de pruebas) — se
        # limpia primero para que cada test parta de un catálogo conocido.
        Multiplicador.objects.all().delete()
        self.general = Multiplicador.objects.create(nombre='General', valor=Decimal('1.76'), es_general=True, orden=0)
        self.categoria = CategoriaLista.objects.create(nombre='Salas', slug='salas')
        # El precio por metro vive en el grupo mismo — es el mismo sin
        # importar la categoría del producto (ver GrupoTela.precio_por_metro).
        self.grupo1 = GrupoTela.objects.create(nombre='Grupo 1', orden=1, precio_por_metro=Decimal('30000'))
        self.grupo2 = GrupoTela.objects.create(nombre='Grupo 2', orden=2, precio_por_metro=Decimal('40000'))
        self.linea = LineaProducto.objects.create(nombre='Detroit', slug='detroit')

    def test_formula_reproduce_ejemplo_excel_salas_detroit(self):
        """Reproduce el ejemplo exacto de §2.2/§5 del plan: Detroit, Sofá
        3p., Grupo 1 → $3.892.064, igual que SALAS!F9 en el Excel real."""
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Sofá 3p. (235cm.)',
            costo_base=Decimal('1676400'), metraje_tela=Decimal('12'),
        )
        CargoVariante.objects.create(variante=variante, descripcion='Transporte', valor=Decimal('95000'))
        CargoVariante.objects.create(variante=variante, descripcion='Instalación', valor=Decimal('80000'))

        precio = calcular_precio(variante, self.grupo1)
        self.assertEqual(precio, Decimal('3892064.00'))

    def test_una_coleccion_puede_combinar_categorias_distintas(self):
        """Caso central del refactor: una misma línea/colección (ej.
        "Altus") puede tener una Poltrona y un Sofá de 3, cada uno con su
        propia categoría — y ambos usan el mismo precio por grupo de tela,
        porque ya no depende de la categoría (corrección explícita del
        usuario, ver GrupoTela.precio_por_metro)."""
        poltronas = CategoriaLista.objects.create(nombre='Poltronas', slug='poltronas')

        sofa = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Sofá de 3',
            costo_base=Decimal('1000000'), metraje_tela=Decimal('10'),
        )
        poltrona = VarianteProducto.objects.create(
            linea=self.linea, categoria=poltronas, nombre='Poltrona',
            costo_base=Decimal('500000'), metraje_tela=Decimal('5'),
        )

        self.assertEqual(self.linea.variantes.count(), 2)
        # Ambas usan el multiplicador general (×1.76) porque ninguna tiene
        # uno propio asignado — la categoría ya no define multiplicador.
        self.assertEqual(
            calcular_precio(sofa, self.grupo1),
            (Decimal('1000000') + Decimal('10') * Decimal('30000')) * Decimal('1.76'),
        )
        self.assertEqual(
            calcular_precio(poltrona, self.grupo1),
            (Decimal('500000') + Decimal('5') * Decimal('30000')) * Decimal('1.76'),
        )

    def test_precio_por_grupo_no_depende_de_la_categoria(self):
        """Regresión directa de la corrección: dos variantes de categorías
        distintas, mismo grupo de tela, deben dar el mismo costo de metraje
        (antes de este cambio, cada categoría podía tener su propio precio
        por metro para el mismo grupo)."""
        comedores = CategoriaLista.objects.create(nombre='Comedores', slug='comedores')
        silla_a = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Silla A',
            costo_base=Decimal('0'), metraje_tela=Decimal('1'),
        )
        silla_b = VarianteProducto.objects.create(
            linea=self.linea, categoria=comedores, nombre='Silla B',
            costo_base=Decimal('0'), metraje_tela=Decimal('1'),
        )
        self.assertEqual(calcular_precio(silla_a, self.grupo1), calcular_precio(silla_b, self.grupo1))

    def test_precio_manual_override_ignora_formula(self):
        """Caso de las ~60 celdas del Excel escritas a mano, sin fórmula."""
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Cojín',
            costo_base=Decimal('999999'), metraje_tela=None,
        )
        PrecioVariante.objects.create(variante=variante, grupo=self.grupo1, precio_manual=Decimal('45000'))
        self.assertEqual(calcular_precio(variante, self.grupo1), Decimal('45000'))

    def test_producto_sin_tela_no_suma_metraje(self):
        """Caso Mesas de Centro / Alcobas 2: sin grupo de tela, precio plano."""
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Mesa de Centro',
            costo_base=Decimal('500000'), metraje_tela=None,
        )
        self.assertEqual(calcular_precio(variante, None), Decimal('500000') * Decimal('1.76'))

    def test_cargo_negativo_resta_del_precio(self):
        """Caso "Sin tapa" = -$80.000 (Mesas de Centro, §2.4)."""
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Araña sin tapa',
            costo_base=Decimal('500000'), metraje_tela=None,
        )
        CargoVariante.objects.create(variante=variante, descripcion='Sin tapa', valor=Decimal('-80000'))
        self.assertEqual(calcular_precio(variante, None), Decimal('420000') * Decimal('1.76'))

    def test_precios_por_variante_genera_una_fila_por_grupo_disponible(self):
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Poltrona',
            costo_base=Decimal('500000'), metraje_tela=Decimal('5'),
        )
        filas = precios_por_variante(variante)
        self.assertEqual(len(filas), 2)
        nombres = {f['grupo_nombre'] for f in filas}
        self.assertEqual(nombres, {'Grupo 1', 'Grupo 2'})

    def test_precios_por_variante_sin_tela_da_una_sola_fila(self):
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Mesa',
            costo_base=Decimal('300000'), metraje_tela=None,
        )
        filas = precios_por_variante(variante)
        self.assertEqual(len(filas), 1)
        self.assertIsNone(filas[0]['grupo'])

    def test_cargo_opcional_no_seleccionado_no_se_suma(self):
        """Caso "transporte" del usuario: un cargo opcional NO se suma al
        precio de lista por defecto — solo cuando el vendedor lo activa."""
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Sofá Moon',
            costo_base=Decimal('1000000'), metraje_tela=Decimal('10'),
        )
        transporte = CargoVariante.objects.create(
            variante=variante, descripcion='Transporte', valor=Decimal('110000'), opcional=True,
        )
        precio_base = calcular_precio(variante, self.grupo1)
        self.assertEqual(precio_base, (Decimal('1000000') + Decimal('10') * Decimal('30000')) * Decimal('1.76'))

        precio_con_transporte = calcular_precio(variante, self.grupo1, opcionales_ids={transporte.id})
        self.assertEqual(
            precio_con_transporte,
            (Decimal('1000000') + Decimal('10') * Decimal('30000') + Decimal('110000')) * Decimal('1.76'),
        )

    def test_opcionales_de_variante_excluye_cargos_fijos(self):
        """Los cargos fijos (costo interno) nunca deben aparecer en la lista
        de opcionales expuesta al vendedor."""
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Comedor',
            costo_base=Decimal('500000'), metraje_tela=None,
        )
        CargoVariante.objects.create(variante=variante, descripcion='Mano de obra interna', valor=Decimal('30000'))
        toma = CargoVariante.objects.create(
            variante=variante, descripcion='Tomacorriente USB', valor=Decimal('50000'), opcional=True,
        )
        opcionales = opcionales_de_variante(variante)
        self.assertEqual(len(opcionales), 1)
        self.assertEqual(opcionales[0]['id'], toma.id)

    def test_cargo_opcional_se_suma_encima_de_precio_manual(self):
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Cojín',
            costo_base=Decimal('999999'), metraje_tela=None,
        )
        PrecioVariante.objects.create(variante=variante, grupo=self.grupo1, precio_manual=Decimal('45000'))
        extra = CargoVariante.objects.create(
            variante=variante, descripcion='Bordado', valor=Decimal('10000'), opcional=True,
        )
        self.assertEqual(
            calcular_precio(variante, self.grupo1, opcionales_ids={extra.id}),
            Decimal('45000') + Decimal('10000') * Decimal('1.76'),
        )

    def test_impacto_categoria_cuenta_variantes_activas(self):
        VarianteProducto.objects.create(linea=self.linea, categoria=self.categoria, nombre='Sofá 2p.', costo_base=Decimal('1'))
        VarianteProducto.objects.create(linea=self.linea, categoria=self.categoria, nombre='Sofá 3p.', costo_base=Decimal('1'))
        otra_linea = LineaProducto.objects.create(nombre='Inactiva', slug='inactiva', activo=False)
        VarianteProducto.objects.create(linea=otra_linea, categoria=self.categoria, nombre='X', costo_base=Decimal('1'))

        resultado = impacto_categoria(self.categoria)
        self.assertEqual(resultado['lineas_afectadas'], 1)
        self.assertEqual(resultado['variantes_afectadas'], 2)

    # ---- Catálogo de multiplicadores (nombre libre, independiente de la categoría) ----

    def test_multiplicador_por_defecto_usa_el_general(self):
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Sofá 3p.',
            costo_base=Decimal('1000000'), metraje_tela=None,
        )
        self.assertIsNone(variante.multiplicador_id)
        self.assertEqual(multiplicador_efectivo(variante), Decimal('1.76'))
        self.assertEqual(calcular_precio(variante, None), Decimal('1000000') * Decimal('1.76'))

    def test_variante_con_multiplicador_propio_nombrado_libremente(self):
        """El admin crea el multiplicador con el nombre que quiera (ej.
        "Mayorista") y lo asigna a variantes puntuales — independiente de
        la categoría y de cualquier otra variante."""
        mayorista = Multiplicador.objects.create(nombre='Mayorista', valor=Decimal('1.3'), orden=1)
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Edición especial',
            costo_base=Decimal('500000'), metraje_tela=None, multiplicador=mayorista,
        )
        self.assertEqual(multiplicador_efectivo(variante), Decimal('1.3'))
        self.assertEqual(calcular_precio(variante, None), Decimal('500000') * Decimal('1.3'))

    def test_multiplicador_con_valor_uno_equivale_a_sin_margen(self):
        """"Sin multiplicador" ya no es un caso especial del código — es
        simplemente un Multiplicador más, que el admin puede crear con
        valor=1 y el nombre que quiera (ej. "Costo")."""
        costo = Multiplicador.objects.create(nombre='Costo', valor=Decimal('1'), orden=1)
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Repuesto',
            costo_base=Decimal('200000'), metraje_tela=None, multiplicador=costo,
        )
        self.assertEqual(calcular_precio(variante, None), Decimal('200000'))

    def test_multiplicador_propio_afecta_tambien_metraje_y_cargos(self):
        doble = Multiplicador.objects.create(nombre='Doble margen', valor=Decimal('2'), orden=1)
        variante = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='Sofá especial',
            costo_base=Decimal('1000000'), metraje_tela=Decimal('10'), multiplicador=doble,
        )
        CargoVariante.objects.create(variante=variante, descripcion='Cargo fijo', valor=Decimal('50000'))
        self.assertEqual(
            calcular_precio(variante, self.grupo1),
            (Decimal('1000000') + Decimal('10') * Decimal('30000') + Decimal('50000')) * Decimal('2'),
        )

    def test_establecer_multiplicador_general_desmarca_al_anterior(self):
        nuevo = Multiplicador.objects.create(nombre='Promoción', valor=Decimal('1.5'), orden=1)
        establecer_multiplicador_general(nuevo)

        self.general.refresh_from_db()
        nuevo.refresh_from_db()
        self.assertFalse(self.general.es_general)
        self.assertTrue(nuevo.es_general)
        self.assertEqual(obtener_multiplicador_general(), Decimal('1.5'))

    def test_impacto_multiplicador_general_incluye_variantes_sin_asignar(self):
        propio = Multiplicador.objects.create(nombre='Propio', valor=Decimal('2'), orden=1)
        VarianteProducto.objects.create(linea=self.linea, categoria=self.categoria, nombre='Usa general 1', costo_base=Decimal('1'))
        VarianteProducto.objects.create(linea=self.linea, categoria=self.categoria, nombre='Usa general 2', costo_base=Decimal('1'))
        VarianteProducto.objects.create(linea=self.linea, categoria=self.categoria, nombre='Con propio', costo_base=Decimal('1'), multiplicador=propio)

        self.assertEqual(impacto_multiplicador(self.general)['variantes_afectadas'], 2)
        self.assertEqual(impacto_multiplicador(propio)['variantes_afectadas'], 1)

    def test_asignar_multiplicador_masivo_por_categoria(self):
        promo = Multiplicador.objects.create(nombre='Promoción', valor=Decimal('1.5'), orden=1)
        v1 = VarianteProducto.objects.create(linea=self.linea, categoria=self.categoria, nombre='A', costo_base=Decimal('1'))
        v2 = VarianteProducto.objects.create(linea=self.linea, categoria=self.categoria, nombre='B', costo_base=Decimal('1'))
        otra_categoria = CategoriaLista.objects.create(nombre='Comedores', slug='comedores')
        v3 = VarianteProducto.objects.create(linea=self.linea, categoria=otra_categoria, nombre='C', costo_base=Decimal('1'))

        actualizadas = asignar_multiplicador_masivo(multiplicador_id=promo.id, categoria_id=self.categoria.id)

        self.assertEqual(actualizadas, 2)
        v1.refresh_from_db(); v2.refresh_from_db(); v3.refresh_from_db()
        self.assertEqual(v1.multiplicador_id, promo.id)
        self.assertEqual(v2.multiplicador_id, promo.id)
        self.assertIsNone(v3.multiplicador_id)

    def test_asignar_multiplicador_masivo_a_none_vuelve_al_general(self):
        promo = Multiplicador.objects.create(nombre='Promoción', valor=Decimal('1.5'), orden=1)
        v1 = VarianteProducto.objects.create(
            linea=self.linea, categoria=self.categoria, nombre='A', costo_base=Decimal('1'), multiplicador=promo,
        )
        asignar_multiplicador_masivo(multiplicador_id=None, variante_ids=[v1.id])
        v1.refresh_from_db()
        self.assertIsNone(v1.multiplicador_id)

    def test_asignar_multiplicador_masivo_exige_al_menos_un_filtro(self):
        with self.assertRaises(ValueError):
            asignar_multiplicador_masivo(multiplicador_id=None)
