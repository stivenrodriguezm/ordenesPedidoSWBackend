"""Agente de la oficina cuando no encuentra la impresora (2026-10-30): antes el documento se
quedaba en la cola de CUPS y la web cargando sin decir nada."""
import importlib.util
import subprocess
import time
from pathlib import Path
from unittest import TestCase, mock

RUTA = Path(__file__).resolve().parent.parent / 'scripts' / 'impresion' / 'agente.py'
_spec = importlib.util.spec_from_file_location('agente_impresion', RUTA)
agente = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agente)

SERVIDOR = {'nombre': 'prueba', 'api': 'https://x/api', 'token': 't'}
URI = 'dispositivo para COLA: dnssd://RICOH%20SP%203710SF%20(50f7b8)._ipps._tcp.local./?uuid=abc\n'


def respuesta(stdout='', codigo=0):
    return subprocess.CompletedProcess([], codigo, stdout=stdout, stderr='')


class BuscarImpresoraTests(TestCase):
    def test_dnssd_usa_ippfind_con_el_nombre_del_servicio(self):
        for codigo, esperado in ((0, True), (1, False)):
            with mock.patch.object(agente.subprocess, 'run', side_effect=[respuesta(URI), respuesta(codigo=codigo)]) as run:
                self.assertIs(agente.impresora_encontrada('COLA'), esperado)
            self.assertEqual(run.call_args_list[1].args[0], ['ippfind', 'RICOH SP 3710SF (50f7b8)._ipps._tcp.local.', '-T', '3'])

    def test_direccion_fija_prueba_la_conexion(self):
        with mock.patch.object(agente.subprocess, 'run', return_value=respuesta('device for COLA: socket://10.0.0.9:9100\n')), \
                mock.patch.object(agente.socket, 'create_connection', side_effect=OSError) as con:
            self.assertIs(agente.impresora_encontrada('COLA'), False)
        con.assert_called_once_with(('10.0.0.9', 9100), timeout=3)

    def test_si_no_se_puede_saber_no_afirma_nada(self):
        with mock.patch.object(agente.subprocess, 'run', return_value=respuesta('device for COLA: usb://Ricoh/SP\n')):
            self.assertIsNone(agente.impresora_encontrada('COLA'))
        with mock.patch.object(agente.subprocess, 'run', side_effect=OSError):
            self.assertIsNone(agente.impresora_encontrada('COLA'))


class TrabajoAtascadoTests(TestCase):
    def setUp(self):
        with mock.patch.object(agente, 'cargar_config', return_value={'cola': 'COLA', 'servidores': [SERVIDOR]}):
            self.a = agente.Agente()
        for nombre in ('pedir', 'cancelar_en_cups', 'pendientes_cups', 'impresora_encontrada'):
            p = mock.patch.object(agente, nombre)
            setattr(self, nombre, p.start())
            self.addCleanup(p.stop)
        self.pendientes_cups.return_value = {'COLA-1'}

    def en_cola(self, hace):
        self.a.en_vuelo['COLA-1'] = (SERVIDOR, 7, time.time() - hace)

    def test_sin_impresora_avisa_una_vez_y_sigue_esperando(self):
        self.a.impresora_ok = False
        self.en_cola(10)
        self.a.revisar_en_vuelo()
        self.a.revisar_en_vuelo()
        self.pedir.assert_called_once_with(SERVIDOR, '/impresion/agente/trabajos/7/', {'estado': 'enviado', 'detalle': agente.NO_ENCONTRADA})
        self.cancelar_en_cups.assert_not_called()

    def test_sin_impresora_cancela_y_reporta_error_para_que_la_web_no_quede_cargando(self):
        self.a.impresora_ok = False
        self.impresora_encontrada.return_value = False
        self.en_cola(agente.CANCELAR_SEG + 1)
        self.a.revisar_en_vuelo()
        self.cancelar_en_cups.assert_called_once_with('COLA-1')
        datos = self.pedir.call_args.args[2]
        self.assertEqual(datos['estado'], 'error')
        self.assertIn('No se imprimió', datos['detalle'])
        self.assertLessEqual(len(datos['detalle']), 255)
        self.assertNotIn('COLA-1', self.a.en_vuelo)

    def test_no_cancela_si_al_volver_a_buscar_la_impresora_aparecio(self):
        self.a.impresora_ok = False
        self.impresora_encontrada.return_value = True
        self.en_cola(agente.CANCELAR_SEG + 1)
        self.a.revisar_en_vuelo()
        self.cancelar_en_cups.assert_not_called()
        self.assertIn('COLA-1', self.a.en_vuelo)

    def test_con_impresora_no_cancela_aunque_tarde(self):
        self.a.impresora_ok = True
        self.en_cola(agente.CANCELAR_SEG + 1)
        self.a.revisar_en_vuelo()
        self.cancelar_en_cups.assert_not_called()
        self.pedir.assert_not_called()

    def test_si_salio_de_la_cola_queda_impreso(self):
        self.a.impresora_ok = True
        self.pendientes_cups.return_value = set()
        self.en_cola(5)
        self.a.revisar_en_vuelo()
        self.pedir.assert_called_once_with(SERVIDOR, '/impresion/agente/trabajos/7/', {'estado': 'impreso'})


class CertificadosTests(TestCase):
    """(2026-11-19) En la oficina el agente no veía el certificado raíz del servidor."""

    def tearDown(self):
        agente.contexto_tls.cache_clear()

    def test_suma_los_certificados_que_van_con_el_agente(self):
        import certifi
        agente.contexto_tls.cache_clear()
        with mock.patch.object(agente, 'CERTIFICADOS', Path('/no/existe.pem')):
            solo_sistema = agente.contexto_tls().cert_store_stats()['x509_ca']
        agente.contexto_tls.cache_clear()
        with mock.patch.object(agente, 'CERTIFICADOS', Path(certifi.where())):
            self.assertGreater(agente.contexto_tls().cert_store_stats()['x509_ca'], solo_sistema)

    def test_las_consultas_usan_ese_contexto(self):
        with mock.patch.object(agente.urllib.request, 'urlopen', side_effect=OSError('sin red')) as abrir:
            with self.assertRaises(OSError):
                agente.pedir(SERVIDOR, '/impresion/agente/siguiente/')
        self.assertIs(abrir.call_args.kwargs['context'], agente.contexto_tls())


class WindowsTests(TestCase):
    """Se prueba la lógica con PowerShell y SumatraPDF simulados; lo real se comprueba con --probar."""

    def test_imprime_con_sumatra_en_carta_y_sigue_el_trabajo_nuevo(self):
        with mock.patch.object(agente, '_powershell', side_effect=[(0, '4'), (0, '4\n9')]), \
                mock.patch.object(agente.subprocess, 'run', return_value=respuesta()) as run:
            self.assertEqual(agente.imprimir_windows(Path('C:/t/d.pdf'), 'RICOH SP', 1, 'CE-1'), '9')
        orden = run.call_args.args[0]
        self.assertEqual(orden[1:6], ['-print-to', 'RICOH SP', '-silent', '-print-settings', '1x,noscale,paper=letter,simplex'])

    def test_doble_cara_con_cada_copia_en_su_propio_trabajo(self):
        # Con 3 páginas y 2 copias en un solo trabajo, la 2.ª copia empezaría al respaldo de la 1.ª.
        with mock.patch.object(agente, '_powershell', side_effect=[(0, '4'), (0, '4\n10\n11')]), \
                mock.patch.object(agente.subprocess, 'run', return_value=respuesta()) as run:
            self.assertEqual(agente.imprimir_windows(Path('C:/t/d.pdf'), 'RICOH SP', 2, 'Remisión', doble_cara=True), '11')
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0][5], '1x,noscale,paper=letter,duplexlong')

    def test_en_mac_carta_doble_cara_y_copias_intercaladas(self):
        with mock.patch.object(agente.subprocess, 'run', return_value=respuesta('request id is COLA-12 (1 file(s))')) as run:
            self.assertEqual(agente.imprimir(Path('/t/d.pdf'), 'COLA', 2, 'Remisión', doble_cara=True), 'COLA-12')
        orden = run.call_args.args[0]
        for opcion in ('media=Letter', 'sides=two-sided-long-edge', 'collate=true'):
            self.assertIn(opcion, orden)
        self.assertEqual(orden[orden.index('-n') + 1], '2')

    def test_si_sumatra_falla_se_reporta(self):
        with mock.patch.object(agente, '_powershell', return_value=(0, '')), \
                mock.patch.object(agente.subprocess, 'run', return_value=respuesta(codigo=1)):
            with self.assertRaises(RuntimeError):
                agente.imprimir_windows(Path('C:/t/d.pdf'), 'RICOH', 1, 'CE-1')

    def test_si_ya_salio_de_la_cola_no_hay_trabajo_que_seguir(self):
        with mock.patch.object(agente, '_powershell', return_value=(0, '')), \
                mock.patch.object(agente.subprocess, 'run', return_value=respuesta()):
            self.assertIsNone(agente.imprimir_windows(Path('C:/t/d.pdf'), 'RICOH', 1, 'CE-1'))

    def test_el_nombre_de_la_impresora_no_rompe_el_comando(self):
        with mock.patch.object(agente, '_powershell', return_value=(0, '')) as ps:
            agente.pendientes_windows("RICOH d'oficina")
        self.assertIn("'RICOH d''oficina'", ps.call_args.args[0])

    def encontrada(self, estado, conecta=True):
        efecto = None if conecta else OSError
        with mock.patch.object(agente, '_powershell', return_value=(0, estado)), \
                mock.patch.object(agente.socket, 'create_connection', side_effect=efecto):
            return agente.impresora_encontrada_windows('RICOH')

    def test_busca_la_impresora(self):
        self.assertIs(self.encontrada('{"estado":"Normal","host":"192.168.1.20","puerto":"9100"}'), True)
        self.assertIs(self.encontrada('{"estado":"Normal","host":"192.168.1.20","puerto":"9100"}', conecta=False), False)
        self.assertIs(self.encontrada('{"estado":"Offline","host":"","puerto":""}'), False)
        self.assertIsNone(self.encontrada('{"estado":"Normal","host":"","puerto":""}'))  # USB o WSD
        with mock.patch.object(agente, '_powershell', return_value=(1, '')):
            self.assertIs(agente.impresora_encontrada_windows('NO INSTALADA'), False)

    def test_en_pausa(self):
        with mock.patch.object(agente, '_powershell', return_value=(0, '{"estado":"Paused","host":"","puerto":""}')):
            self.assertTrue(agente.cola_detenida_windows('RICOH'))
