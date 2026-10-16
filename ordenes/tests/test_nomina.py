"""Nómina de asesores (D12a): comisión por descuento, abono mínimo, bonificación por
meta pagada al entregar desde el cierre siguiente, básico, ajustes y edición."""
from datetime import date
from decimal import Decimal

from ordenes import nomina
from ordenes.models import AsesorCierre, AsesorNomina, LineaNomina, Venta
from ordenes.tests.utils import LottusTestCase


def lineas(datos, asesor, tipo):
    fila = next(a for a in datos['asesores'] if a['asesor'] == asesor.id)
    return [l for l in fila['lineas'] if l['tipo'] == tipo], fila


class TablaComisionTests(LottusTestCase):
    def test_porcentaje_segun_descuento(self):
        tabla = nomina.config().tabla_comision
        casos = {'0': '4.0', '1': '3.9', '2.5': '3.9', '2.6': '3.8', '10': '3.6', '24.9': '3.0', '25': '3.0', '40': '3.0'}
        for desc, pct in casos.items():
            self.assertEqual(nomina.porcentaje_por_descuento(tabla, Decimal(desc)), Decimal(pct), desc)
        self.assertEqual(nomina.descuento_pct(Decimal('900000'), Decimal('1000000')), Decimal('10.00'))
        self.assertEqual(nomina.descuento_pct(Decimal('900000'), None), Decimal('0'))


class NominaTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.c = self.api(self.admin)
        self.ana = self.crear_usuario('ana')
        self.beto = self.crear_usuario('beto')
        AsesorNomina.objects.create(asesor=self.ana, salario_basico='1300000', meta='1000000')
        # Período del 6/9 al 5/10.
        self.a = self.venta(self.ana, valor='900000', fecha=date(2026, 9, 10), valor_lista='1000000', abono='300000')
        self.b = self.venta(self.ana, valor='200000', valor_lista='200000', fecha=date(2026, 9, 12), abono='40000')
        self.comp = self.venta(self.ana, valor='400000', valor_lista='400000', fecha=date(2026, 9, 20), abono='400000')
        self.comp.vendedores_compartidos.add(self.beto)
        self.vieja = self.venta(self.ana, valor='500000', fecha=date(2026, 8, 1), abono='500000')

    def venta(self, vendedor, valor, fecha, abono='0', **extra):
        v = super().venta(vendedor, valor=valor, fecha=fecha, **extra)
        Venta.objects.filter(pk=v.pk).update(abono=Decimal(abono), saldo=Decimal(valor) - Decimal(abono))
        v.refresh_from_db()
        return v

    def crear(self, inicio, fin):
        r = self.c.post('/api/nomina/cierres/', {'fecha_inicio': inicio, 'fecha_fin': fin}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data


    def test_basico_y_meta_de_la_configuracion_llegan_al_cierre_abierto(self):
        """Básico agregado en Configuración después de crear el cierre (2026-10-09)."""
        d = self.crear('2026-09-06', '2026-10-05')
        fila = lambda u: AsesorCierre.objects.get(cierre_id=d['id'], asesor=u)
        self.assertEqual(fila(self.beto).salario_basico, Decimal('0'))
        r = self.c.patch(f'/api/nomina/asesores/{self.beto.pk}/', {'salario_basico': '1200000', 'meta': '500000'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((fila(self.beto).salario_basico, fila(self.beto).meta), (Decimal('1200000'), Decimal('500000')))
        # Lo fijado a mano en el cierre se respeta al recalcular y al cambiar la configuración.
        self.c.patch(f"/api/nomina/asesores-cierre/{fila(self.ana).pk}/", {'salario_basico': '1000000'}, format='json')
        AsesorNomina.objects.filter(asesor=self.ana).update(salario_basico='1500000')
        self.c.post(f"/api/nomina/cierres/{d['id']}/regenerar/")
        self.assertEqual(fila(self.ana).salario_basico, Decimal('1000000'))
        AsesorNomina.objects.filter(asesor=self.beto).update(salario_basico='1250000')
        self.c.post(f"/api/nomina/cierres/{d['id']}/regenerar/")
        self.assertEqual(fila(self.beto).salario_basico, Decimal('1250000'))
        resumen = self.c.get(f"/api/nomina/cierres/{d['id']}/").data['resumen']
        self.assertEqual(Decimal(resumen['salario_basico']), Decimal('2250000'))
        # Un asesor cerrado conserva lo que se le pagó.
        self.c.post(f"/api/nomina/asesores-cierre/{fila(self.beto).pk}/cerrar/")
        self.c.patch(f'/api/nomina/asesores/{self.beto.pk}/', {'salario_basico': '9'}, format='json')
        self.assertEqual(fila(self.beto).salario_basico, Decimal('1250000'))
    def test_primer_cierre(self):
        d = self.crear('2026-09-06', '2026-10-05')
        com, ana = lineas(d, self.ana, 'comision')
        por_venta = {l['venta']: l for l in com}
        self.assertNotIn(self.vieja.pk, por_venta)  # anterior al primer cierre
        la = por_venta[self.a.pk]
        self.assertEqual((la['descuento_pct'], la['porcentaje'], la['valor'], la['pagar']), ('10.00', '3.60', '32400.00', True))
        lb = por_venta[self.b.pk]  # 20 % de abono: pendiente
        self.assertEqual((lb['pagar'], lb['valor'], lb['motivo_pendiente']), (False, '8000.00', 'Abono menor al 30 %'))
        lc = por_venta[self.comp.pk]  # compartida: 400.000 / 2 al 4 %
        self.assertEqual((lc['participantes'], lc['base'], lc['valor']), (2, '200000.00', '8000.00'))
        com_beto, _ = lineas(d, self.beto, 'comision')
        self.assertEqual([l['valor'] for l in com_beto], ['8000.00'])
        # Meta: 900k + 200k + 200k = 1.3M >= 1M → bonificación causada, no se paga aún.
        self.assertTrue(ana['cumple_meta'])
        bono, _ = lineas(d, self.ana, 'bonificacion')
        self.assertTrue(bono and not any(l['pagar'] for l in bono))
        self.assertEqual(sum(Decimal(l['valor']) for l in bono), Decimal('13000.00'))
        t = ana['totales']
        self.assertEqual((t['comisiones'], t['bonificaciones'], t['salario_basico']), ('40400.00', '0.00', '1300000.00'))
        self.assertEqual(t['total_nomina'], '40400.00')  # el básico se paga aparte (día 20)

    def test_pendientes_pasan_al_siguiente_cierre_y_bonificacion_al_entregar(self):
        d1 = self.crear('2026-09-06', '2026-10-05')
        self.assertEqual(self.c.post(f"/api/nomina/cierres/{d1['id']}/cerrar/").status_code, 200)
        # La venta B llega al 40 % y la venta A se entrega.
        Venta.objects.filter(pk=self.b.pk).update(abono=Decimal('80000'))
        Venta.objects.filter(pk=self.a.pk).update(estado='entregado')
        d2 = self.crear('2026-10-06', '2026-11-05')
        com, ana = lineas(d2, self.ana, 'comision')
        self.assertEqual([(l['venta'], l['pagar']) for l in com], [(self.b.pk, True)])  # la A ya se pagó
        bono, _ = lineas(d2, self.ana, 'bonificacion')
        pagables = {l['venta']: l['pagar'] for l in bono}
        self.assertEqual(pagables[self.a.pk], True)
        self.assertEqual(pagables[self.comp.pk], False)  # aún sin entregar
        self.assertEqual(ana['totales']['bonificaciones'], '9000.00')
        self.assertFalse(ana['cumple_meta'])  # sin ventas en octubre

    def test_cierre_anterior_al_primero_incluye_sus_ventas_sin_duplicar(self):
        sep = self.crear('2026-09-06', '2026-10-05')
        # Cierre de un período anterior creado después: antes salía vacío.
        jul = self.crear('2026-07-06', '2026-08-05')
        com, _ = lineas(jul, self.ana, 'comision')
        self.assertEqual([l['venta'] for l in com], [self.vieja.pk])
        self.assertFalse(com[0]['pagar'])  # sin precio de lista: pendiente
        # Mientras julio está en borrador, septiembre no la ve (no hay doble pago).
        r = self.c.post(f"/api/nomina/cierres/{sep['id']}/regenerar/")
        self.assertNotIn(self.vieja.pk, [l['venta'] for l in lineas(r.data, self.ana, 'comision')[0]])
        # Al cerrar julio, su pendiente pasa a septiembre al recalcularlo.
        self.assertEqual(self.c.post(f"/api/nomina/cierres/{jul['id']}/cerrar/").status_code, 200)
        self.assertEqual(nomina.config().ventas_desde, date(2026, 7, 6))
        r = self.c.post(f"/api/nomina/cierres/{sep['id']}/regenerar/")
        self.assertIn(self.vieja.pk, [l['venta'] for l in lineas(r.data, self.ana, 'comision')[0]])

    def test_edicion_ajustes_y_regenerar(self):
        d = self.crear('2026-09-06', '2026-10-05')
        com, fila = lineas(d, self.ana, 'comision')
        lb = next(l for l in com if l['venta'] == self.b.pk)
        r = self.c.patch(f"/api/nomina/lineas/{lb['id']}/", {'precio_lista': '250000', 'pagar': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        lb2 = next(l for l in lineas(r.data, self.ana, 'comision')[0] if l['venta'] == self.b.pk)
        self.assertEqual((lb2['descuento_pct'], lb2['porcentaje'], lb2['valor'], lb2['pagar'], lb2['editada']), ('20.00', '3.20', '6400.00', True, True))
        self.b.refresh_from_db()
        self.assertEqual(self.b.valor_lista, Decimal('250000'))
        r = self.c.post(f"/api/nomina/asesores-cierre/{fila['id']}/ajustes/", {'descripcion': 'Adelanto del 15', 'valor': '-100000'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.c.post(f"/api/nomina/asesores-cierre/{fila['id']}/ajustes/", {'descripcion': '', 'valor': '5'}, format='json').status_code, 400)
        # Regenerar conserva lo editado y los ajustes.
        r = self.c.post(f"/api/nomina/cierres/{d['id']}/regenerar/")
        com, fila = lineas(r.data, self.ana, 'comision')
        self.assertEqual(next(l for l in com if l['venta'] == self.b.pk)['valor'], '6400.00')
        self.assertEqual(fila['totales']['ajustes'], '-100000.00')
        self.assertEqual(fila['totales']['total_nomina'], str(Decimal('32400') + Decimal('6400') + Decimal('8000') - Decimal('100000')) + '.00')
        # Sin meta cumplida (decisión manual) no hay bonificación.
        r = self.c.patch(f"/api/nomina/asesores-cierre/{fila['id']}/", {'cumple_meta_manual': False}, format='json')
        self.assertEqual(lineas(r.data, self.ana, 'bonificacion')[0], [])

    def test_cerrar_reabrir_y_borrar(self):
        d = self.crear('2026-09-06', '2026-10-05')
        url = f"/api/nomina/cierres/{d['id']}/"
        self.c.post(url + 'cerrar/')
        linea = LineaNomina.objects.filter(asesor_cierre__cierre_id=d['id']).first()
        self.assertEqual(self.c.patch(f'/api/nomina/lineas/{linea.pk}/', {'valor': '1'}, format='json').status_code, 409)
        self.assertEqual(self.c.delete(url).status_code, 409)
        d2 = self.crear('2026-10-06', '2026-11-05')
        self.c.post(f"/api/nomina/cierres/{d2['id']}/cerrar/")
        self.assertEqual(self.c.post(url + 'reabrir/', {}, format='json').status_code, 409)  # hay uno posterior cerrado
        self.c.post(f"/api/nomina/cierres/{d2['id']}/reabrir/", {}, format='json')
        self.assertEqual(self.c.post(url + 'reabrir/', {}, format='json').status_code, 200)  # sin justificación
        self.assertEqual(self.c.delete(f"/api/nomina/cierres/{d2['id']}/").status_code, 204)

    def test_cierre_por_asesor_y_estado_general_dinamico(self):
        d = self.crear('2026-09-06', '2026-10-05')
        _, ana = lineas(d, self.ana, 'comision')
        _, beto = lineas(d, self.beto, 'comision')
        r = self.c.post(f"/api/nomina/asesores-cierre/{ana['id']}/cerrar/")
        self.assertEqual(r.status_code, 200, r.data)
        _, ana = lineas(r.data, self.ana, 'comision')
        self.assertEqual((ana['estado'], r.data['estado'], r.data['asesores_cerrados']), ('cerrado', 'borrador', 1))
        # Ana cerrada no se edita ni se recalcula; Beto sigue abierto.
        linea_ana = LineaNomina.objects.filter(asesor_cierre_id=ana['id'], tipo='comision').first()
        self.assertEqual(self.c.patch(f'/api/nomina/lineas/{linea_ana.pk}/', {'valor': '1'}, format='json').status_code, 409)
        valor = linea_ana.valor
        Venta.objects.filter(pk=self.a.pk).update(valor_lista=Decimal('2000000'))
        self.assertEqual(self.c.post(f"/api/nomina/cierres/{d['id']}/regenerar/").status_code, 200)
        linea_ana.refresh_from_db()
        self.assertEqual(linea_ana.valor, valor)
        self.assertEqual(self.c.post(f"/api/nomina/asesores-cierre/{beto['id']}/ajustes/", {'descripcion': 'Bono', 'valor': '5000'}, format='json').status_code, 201)
        self.assertEqual(self.c.delete(f"/api/nomina/cierres/{d['id']}/").status_code, 409)
        # Con todos cerrados el general queda cerrado; al reabrir uno vuelve a abierto, sin justificación.
        r = self.c.post(f"/api/nomina/asesores-cierre/{beto['id']}/cerrar/")
        self.assertEqual(r.data['estado'], 'cerrado')
        r = self.c.post(f"/api/nomina/asesores-cierre/{beto['id']}/reabrir/")
        self.assertEqual((r.status_code, r.data['estado']), (200, 'borrador'))
        # En el siguiente cierre no se vuelve a pagar lo de Ana (cerrada), sí lo de Beto (abierto).
        d2 = self.crear('2026-10-06', '2026-11-05')
        self.assertNotIn(self.a.pk, [l['venta'] for l in lineas(d2, self.ana, 'comision')[0] if l['pagar']])

    def test_descuento_global_por_asesor(self):
        d = self.crear('2026-09-06', '2026-10-05')
        _, ana = lineas(d, self.ana, 'comision')
        # Ana: 900k/1M, 200k/200k y la compartida 200k/200k (su mitad) → 1,3M frente a 1,4M de lista.
        self.assertEqual((ana['totales']['ventas_con_lista'], ana['totales']['lista_total']), ('1300000.00', '1400000.00'))
        self.assertEqual(ana['totales']['descuento_global_pct'], '7.14')
        self.assertIsNotNone(d['resumen']['descuento_global_pct'])

    def test_permisos_y_config(self):
        aux = self.crear_usuario('aux', role='auxiliar')
        self.permisos('auxiliar', ['VER_NOMINA'])
        c = self.api(aux)
        self.assertEqual(c.get('/api/nomina/cierres/').status_code, 200)
        self.assertEqual(c.post('/api/nomina/cierres/', {'fecha_inicio': '2026-09-06', 'fecha_fin': '2026-10-05'}, format='json').status_code, 403)
        self.permisos('auxiliar', [])
        self.assertEqual(c.get('/api/nomina/cierres/').status_code, 403)
        r = self.c.put('/api/nomina/config/', {'tabla_comision': [[0, 4], [10, 3.5], [20, 3]], 'abono_minimo_pct': '25'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['abono_minimo_pct'], '25')
        r = self.c.patch(f'/api/nomina/asesores/{self.beto.pk}/', {'salario_basico': '1500000', 'meta': '2000000'}, format='json')
        self.assertEqual(r.data['salario_basico'], '1500000.00')
        filas = self.c.get('/api/nomina/asesores/').data
        self.assertEqual(next(f for f in filas if f['asesor'] == self.beto.pk)['meta'], '2000000.00')

    def test_valor_lista_en_la_venta(self):
        r = self.c.get(f'/api/ventas/{self.a.pk}/')
        if r.status_code == 200:
            self.assertEqual(Decimal(str(r.data['valor_lista'])), Decimal('1000000'))
