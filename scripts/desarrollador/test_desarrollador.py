"""Pruebas del servicio Desarrollador (sin red ni Gemini real):
    cd ordenesPedidoSWBackend/scripts && python -m unittest desarrollador.test_desarrollador
"""
import copy
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from desarrollador import gemini
from desarrollador.gemini import ErrorGemini
from desarrollador.espacio import Espacio, ErrorEspacio, encadenar_ordenes, riesgo_migraciones
from desarrollador.servicio import Config, Servicio


def git(*args, cwd):
    subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True)


def crear_repos(raiz):
    """Dos repos con un origen bare cada uno, como en el VPS."""
    raiz = Path(raiz)
    for nombre, archivos in (('backend', {'ordenes/models.py': 'class Venta:\n    pass\n', '.env': 'SECRETO=1\n',
                                          'lottusPedidos/settings.py': 'DEBUG = False\n',
                                          'ordenes/migrations/0061_merge_bancos_y_nomina.py':
                                              "dependencies = [\n    ('ordenes', '0057_eliminar_bancos'),\n    ('ordenes', '0085_tareas_desarrollador'),\n]\n"}),
                             ('frontend', {'src/App.jsx': 'export default function App() { return <h1>Hola</h1>; }\n'})):
        origen = raiz / f'{nombre}.git'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(origen)], check=True)
        semilla = raiz / f'semilla-{nombre}'
        semilla.mkdir()
        git('init', '-q', '-b', 'main', cwd=semilla)
        for rel, texto in archivos.items():
            (semilla / rel).parent.mkdir(parents=True, exist_ok=True)
            (semilla / rel).write_text(texto)
        git('add', '-A', cwd=semilla)
        git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'inicio', cwd=semilla)
        git('remote', 'add', 'origin', str(origen), cwd=semilla)
        git('push', '-q', 'origin', 'main', cwd=semilla)
        subprocess.run(['git', 'clone', '-q', str(origen), str(raiz / 'trabajo' / nombre)], check=True)
    return raiz / 'trabajo'


class EspacioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.esp = Espacio(crear_repos(self.tmp.name))
        self.esp.preparar('desarrollador/t1')

    def tearDown(self):
        self.tmp.cleanup()

    def test_rutas_seguras(self):
        self.assertIn('Venta', self.esp.leer('backend/ordenes/models.py'))
        for malo in ('backend/.env', '../x', 'otro/archivo', 'backend/.git/config', '/etc/passwd'):
            with self.assertRaises(ErrorEspacio, msg=malo):
                self.esp.leer(malo)
        self.assertNotIn('.env', self.esp.listar('backend'))
        with self.assertRaises(ErrorEspacio):
            self.esp.escribir('backend/lottusPedidos/settings.py', 'DEBUG = True\n')  # solo lectura
        with self.assertRaises(ErrorEspacio):
            self.esp.reemplazar('backend/ordenes/migrations/0061_merge_bancos_y_nomina.py', '0057', 'x')
        self.assertIn('SECRETO', (Path(self.esp.raiz) / 'backend/.env').read_text())  # ni se lee ni se toca

    def test_reemplazar_exige_un_solo_fragmento_y_buscar(self):
        self.esp.escribir('frontend/src/Nuevo.jsx', 'a\na\n')
        with self.assertRaises(ErrorEspacio):
            self.esp.reemplazar('frontend/src/Nuevo.jsx', 'a', 'b')
        self.esp.reemplazar('frontend/src/App.jsx', 'Hola', 'Hola LOTTUS')
        self.assertIn('frontend/src/App.jsx:1:', self.esp.buscar('Hola LOTTUS'))
        self.assertIn('Hola LOTTUS', self.esp.diff('frontend'))

    def test_encadenar_migracion_nueva_antes_del_merge(self):
        nueva = self.esp.raiz / 'backend/ordenes/migrations/0062_campo_nuevo.py'
        nueva.write_text("dependencies = [('ordenes', '0061_merge_bancos_y_nomina')]\nmigrations.RemoveField(\n")
        encadenar_ordenes(self.esp, ['backend/ordenes/migrations/0062_campo_nuevo.py'])
        renombrada = self.esp.raiz / 'backend/ordenes/migrations/0086_campo_nuevo.py'
        self.assertTrue(renombrada.exists() and not nueva.exists())
        self.assertIn("('ordenes', '0085_tareas_desarrollador')", renombrada.read_text())
        merge = (self.esp.raiz / 'backend/ordenes/migrations/0061_merge_bancos_y_nomina.py').read_text()
        self.assertIn("'0086_campo_nuevo'", merge)
        self.assertIn("'0057_eliminar_bancos'", merge)
        self.assertEqual(riesgo_migraciones(self.esp, ['backend/ordenes/migrations/0086_campo_nuevo.py']), ['0086_campo_nuevo.py: RemoveField'])


def respuesta(*llamadas, tokens=10):
    r = mock.Mock(status_code=200)
    r.json.return_value = {'candidates': [{'content': {'parts': [{'functionCall': {'name': n, 'args': a}} for n, a in llamadas]}}],
                           'usageMetadata': {'totalTokenCount': tokens}}
    return r


class PlataformaFalsa:
    def __init__(self, tarea):
        self.tarea, self.cambios = tarea, []

    def pendientes(self):
        return [self.tarea]

    def actualizar(self, pk, **datos):
        self.cambios.append(datos)
        if 'estado' in datos:
            self.tarea['estado'] = datos['estado']
        return self.tarea

    def latido(self):
        pass


PLAN = {'entendido': 'Cambiar el saludo', 'pasos': ['Editar App.jsx'], 'archivos': ['frontend/src/App.jsx'], 'riesgo': 'bajo',
        'riesgos': ['Ninguno relevante'], 'cambia_base_datos': False, 'cambios_pantalla': 'Dirá Hola LOTTUS'}


class ServicioTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(gemini.time, 'sleep').start()  # sin esperas reales entre llamadas
        self.tmp = tempfile.TemporaryDirectory()
        raiz = crear_repos(self.tmp.name)
        cfg = Config({'DESARROLLADOR_TOKEN': 't', 'DESARROLLADOR_GEMINI_API_KEY': 'clave-falsa', 'DESARROLLADOR_RAIZ': str(raiz),
                      'DESARROLLADOR_MODELOS': 'gemini-prueba', 'DESARROLLADOR_INTERVALO': '0'})
        self.tarea = {'id': 7, 'pedido': 'Que el saludo diga Hola LOTTUS', 'estado': 'planificando', 'ajustes': [], 'plan': {}, 'usuario': 'Stiven'}
        self.plat = PlataformaFalsa(self.tarea)
        self.serv = Servicio(cfg, plataforma=self.plat)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_con_lectura_y_luego_implementa_verifica_y_publica(self):
        with mock.patch.object(gemini.requests, 'post', side_effect=[
                respuesta(('leer_archivo', {'ruta': 'frontend/src/App.jsx'})),
                respuesta(('reemplazar_texto', {'ruta': 'frontend/src/App.jsx', 'buscar': 'x', 'reemplazo': 'y'})),  # al planear no escribe
                respuesta(('proponer_plan', PLAN))]):
            self.serv.una_vuelta()
        self.assertEqual(self.tarea['estado'], 'plan_listo')
        self.assertEqual(self.plat.cambios[-1]['plan']['riesgo'], 'bajo')
        self.assertNotIn('Hola LOTTUS', (self.serv.espacio.raiz / 'frontend/src/App.jsx').read_text())
        # Aprobado: implementa, las verificaciones fallan una vez, corrige y publica en pruebas.
        self.tarea.update(estado='aprobada', plan=PLAN)
        verificaciones = iter([(False, '## lint: FALLÓ\nerror', {}), (True, 'ok', {})])
        with mock.patch.object(gemini.requests, 'post', side_effect=[
                respuesta(('reemplazar_texto', {'ruta': 'frontend/src/App.jsx', 'buscar': 'Hola', 'reemplazo': 'Hola LOTTUS'})),
                respuesta(('terminar', {'resumen': 'Cambié el saludo', 'cambios_pantalla': 'Inicio dice Hola LOTTUS'})),
                respuesta(('terminar', {'resumen': 'Corregí el lint', 'cambios_pantalla': 'Inicio dice Hola LOTTUS'}))]), \
                mock.patch.object(Servicio, 'verificar', side_effect=lambda ev: next(verificaciones)), \
                mock.patch.object(Servicio, 'publicar_pruebas') as publicar:
            self.serv.una_vuelta()
        self.assertEqual(self.tarea['estado'], 'en_pruebas')
        final = self.plat.cambios[-1]
        self.assertEqual(final['resultado']['rama'], 'desarrollador/t7')
        self.assertTrue(final['resultado']['commits']['frontend'])
        self.assertIsNone(final['resultado']['commits']['backend'])
        self.assertIn('Hola LOTTUS', final['diff'])
        publicar.assert_called_once()
        self.assertEqual(publicar.call_args.args[:2], ('main', 'desarrollador/t7'))  # backend sin cambios: main
        rama = subprocess.run(['git', 'ls-remote', '--heads', 'origin', 'desarrollador/t7'], cwd=self.serv.espacio.repo('frontend'),
                              capture_output=True, text=True).stdout
        self.assertIn('desarrollador/t7', rama)

    def test_si_las_verificaciones_siguen_fallando_queda_fallida_sin_publicar(self):
        self.tarea.update(estado='aprobada', plan=PLAN)
        llamadas = [respuesta(('reemplazar_texto', {'ruta': 'frontend/src/App.jsx', 'buscar': 'Hola', 'reemplazo': 'Chao'}))]
        llamadas += [respuesta(('terminar', {'resumen': 'r', 'cambios_pantalla': 'c'})) for _ in range(5)]
        with mock.patch.object(gemini.requests, 'post', side_effect=llamadas), \
                mock.patch.object(Servicio, 'verificar', return_value=(False, '## pruebas: FALLÓ', {})), \
                mock.patch.object(Servicio, 'publicar_pruebas') as publicar:
            self.serv.una_vuelta()
        self.assertEqual(self.tarea['estado'], 'fallida')
        self.assertIn('siguen fallando', self.plat.cambios[-1]['error'])
        publicar.assert_not_called()

    def test_gemini_caido_deja_la_tarea_fallida(self):
        caida = mock.Mock(status_code=503, content=b'')
        with mock.patch.object(gemini.requests, 'post', return_value=caida):
            self.serv.una_vuelta()
        self.assertEqual(self.tarea['estado'], 'fallida')
        self.assertNotIn('clave-falsa', self.plat.cambios[-1]['error'])

    def test_bloqueo_por_rafaga_se_reintenta_y_pro_sin_acceso_se_descarta(self):
        bloqueo = mock.Mock(status_code=404, content=b'')
        agente = gemini.Agente('k', ['pro', 'flash'], self.serv.espacio, 'plan', 'Stiven', intervalo=0)
        llamadas = [bloqueo, bloqueo,  # pro nunca respondió: se descarta
                    bloqueo, respuesta(('proponer_plan', PLAN))]  # flash bloqueado una vez, luego responde
        with mock.patch.object(gemini.requests, 'post', side_effect=llamadas) as post:
            nombre, plan = agente.conversar('pedido')
        self.assertEqual((nombre, agente.modelo), ('proponer_plan', 'flash'))
        self.assertEqual(post.call_args.kwargs['params'], {'key': 'k'})  # la clave va como parámetro


def turno(*usos, stop='tool_use'):
    """Respuesta de Claude: bloque de pensamiento + llamadas a herramientas."""
    contenido = [NS(type='thinking', thinking='', signature='s')]
    contenido += [NS(type='tool_use', id=f'u{i}', name=n, input=a) for i, (n, a) in enumerate(usos)]
    return NS(content=contenido, stop_reason=stop, stop_details=None, model='claude-opus-5-5',
              usage=NS(input_tokens=100, output_tokens=20, cache_creation_input_tokens=0, cache_read_input_tokens=50))


@unittest.skipUnless(importlib.util.find_spec('anthropic'), 'requiere el SDK de Anthropic (venv del servicio)')
class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.esp = Espacio(crear_repos(self.tmp.name))
        self.esp.preparar('desarrollador/t1')
        self.pedidos = []

    def tearDown(self):
        self.tmp.cleanup()

    def agente(self, modo, respuestas, **kw):
        from desarrollador.claude import AgenteClaude
        agente = AgenteClaude('clave-falsa', 'claude-opus-5-5', self.esp, modo, 'Stiven', **kw)
        respuestas = iter(respuestas)

        def stream(**pedido):
            self.pedidos.append(copy.deepcopy(pedido))  # el historial sigue creciendo después
            return mock.MagicMock(__enter__=mock.Mock(return_value=NS(get_final_message=lambda: next(respuestas))))
        agente.cliente = mock.Mock()
        agente.cliente.with_options.return_value.beta.messages.stream.side_effect = stream
        return agente

    def test_plan_lee_y_propone_con_fallback_y_sin_forzar_herramienta(self):
        agente = self.agente('plan', [turno(('leer_archivo', {'ruta': 'frontend/src/App.jsx'})), turno(('proponer_plan', PLAN))])
        nombre, plan = agente.conversar('Que el saludo diga Hola LOTTUS')
        self.assertEqual((nombre, plan['riesgo'], agente.tokens, agente.modelo), ('proponer_plan', 'bajo', 340, 'claude-opus-5-5'))
        pedido = self.pedidos[0]
        self.assertEqual((pedido['fallbacks'], pedido['betas']), ('default', ['server-side-fallback-2026-07-01']))
        self.assertEqual(pedido['output_config'], {'effort': 'high'})
        self.assertNotIn('tool_choice', pedido)
        self.assertTrue(all(h['eager_input_streaming'] for h in pedido['tools']))
        self.assertNotIn('escribir_archivo', [h['name'] for h in pedido['tools']])  # al planear no escribe
        resultado = self.pedidos[1]['messages'][-1]['content'][0]
        self.assertEqual(resultado['tool_use_id'], 'u0')
        self.assertIn('Hola', resultado['content'])
        self.assertEqual(self.pedidos[1]['messages'][1]['content'][0].type, 'thinking')  # la respuesta vuelve tal cual

    def test_entrada_invalida_vuelve_como_error_y_la_final_espera_su_resultado(self):
        agente = self.agente('implementar', [
            turno(('reemplazar_texto', {'ruta': 'frontend/src/App.jsx', 'buscar': 'Hola'})),  # le falta «reemplazo»
            turno(('reemplazar_texto', {'ruta': 'frontend/src/App.jsx', 'buscar': 'Hola', 'reemplazo': 'Hola LOTTUS'}),
                  ('terminar', {'resumen': 'Listo', 'cambios_pantalla': 'Inicio'})),
            turno(('terminar', {'resumen': 'Corregido', 'cambios_pantalla': 'Inicio'}))], esfuerzo='high')
        self.assertEqual(agente.conversar('Implementa')[0], 'terminar')
        error = self.pedidos[1]['messages'][-1]['content'][0]
        self.assertTrue(error['is_error'])
        self.assertIn('reemplazo', error['content'])
        self.assertIn('Hola LOTTUS', self.esp.leer('frontend/src/App.jsx'))  # la edición del mismo turno se aplicó
        agente.conversar('Las verificaciones fallaron: lint')
        abre = self.pedidos[2]['messages'][-1]['content']
        self.assertEqual([b.get('tool_use_id') for b in abre], ['u0', 'u1', None])  # resultados pendientes y luego el texto
        self.assertEqual(abre[-1]['text'], 'Las verificaciones fallaron: lint')

    def test_rechazo_deja_error_claro(self):
        from desarrollador.claude import ErrorGemini
        rechazo = turno(stop='refusal')
        rechazo.stop_details = NS(category='cyber')
        agente = self.agente('plan', [rechazo])
        with self.assertRaisesRegex(ErrorGemini, 'cyber'):
            agente.conversar('pedido')

    def test_con_clave_de_anthropic_el_servicio_usa_claude(self):
        from desarrollador.claude import AgenteClaude
        cfg = Config({'DESARROLLADOR_TOKEN': 't', 'DESARROLLADOR_ANTHROPIC_API_KEY': 'k', 'DESARROLLADOR_RAIZ': str(self.esp.raiz)})
        serv = Servicio(cfg, plataforma=PlataformaFalsa({}), espacio=self.esp)
        plan, impl = serv._agente('plan', {}), serv._agente('implementar', {})
        self.assertIsInstance(plan, AgenteClaude)
        self.assertEqual((plan.esfuerzo, impl.esfuerzo, plan.modelo_pedido), ('medium', 'high', 'claude-opus-5-5'))


def salida_gpt(*llamadas, rid='r1'):
    import json as _json
    r = mock.Mock(status_code=200)
    r.json.return_value = {'id': rid, 'model': 'gpt-5.5', 'usage': {'total_tokens': 30}, 'output': [{'type': 'reasoning'}] + [
        {'type': 'function_call', 'call_id': f'c{i}', 'name': n, 'arguments': a if isinstance(a, str) else _json.dumps(a)}
        for i, (n, a) in enumerate(llamadas)]}
    return r


class GPTTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        mock.patch('desarrollador.gpt.time.sleep').start()
        self.tmp = tempfile.TemporaryDirectory()
        self.esp = Espacio(crear_repos(self.tmp.name))
        self.esp.preparar('desarrollador/t1')

    def tearDown(self):
        self.tmp.cleanup()

    def test_encadena_turnos_valida_entradas_y_deja_pendiente_la_final(self):
        from desarrollador.gpt import AgenteGPT
        agente = AgenteGPT('clave-falsa', 'gpt-5.5', self.esp, 'implementar', 'Stiven', esfuerzo='medium')
        respuestas = [salida_gpt(('reemplazar_texto', '{"ruta": "frontend/src/App.jsx", "buscar"'), rid='r1'),  # JSON cortado
                      salida_gpt(('reemplazar_texto', {'ruta': 'frontend/src/App.jsx', 'buscar': 'Hola', 'reemplazo': 'Hola LOTTUS'}),
                                 ('terminar', {'resumen': 'Listo', 'cambios_pantalla': 'Inicio'}), rid='r2'),
                      salida_gpt(('terminar', {'resumen': 'Corregido', 'cambios_pantalla': 'Inicio'}), rid='r3')]
        with mock.patch('desarrollador.gpt.requests.post', side_effect=respuestas) as post:
            self.assertEqual(agente.conversar('Implementa')[0], 'terminar')
            self.assertIn('Hola LOTTUS', self.esp.leer('frontend/src/App.jsx'))
            agente.conversar('Las verificaciones fallaron: lint')
        cuerpos = [c.kwargs['json'] for c in post.call_args_list]
        self.assertEqual(post.call_args.kwargs['headers'], {'Authorization': 'Bearer clave-falsa'})
        self.assertEqual((cuerpos[0]['tool_choice'], cuerpos[0]['reasoning'], 'previous_response_id' in cuerpos[0]),
                         ('required', {'effort': 'medium'}, False))
        self.assertEqual(cuerpos[1]['previous_response_id'], 'r1')
        self.assertIn('Entrada inválida', cuerpos[1]['input'][0]['output'])
        self.assertEqual([i.get('call_id') for i in cuerpos[2]['input']], ['c0', 'c1', None])  # pendientes y luego el texto
        self.assertEqual((cuerpos[2]['previous_response_id'], agente.tokens, agente.modelo), ('r2', 90, 'gpt-5.5'))

    def test_sin_saldo_falla_de_una_con_mensaje_claro(self):
        from desarrollador.gpt import AgenteGPT
        sin_saldo = mock.Mock(status_code=429, headers={})
        sin_saldo.json.return_value = {'error': {'type': 'insufficient_quota', 'code': 'credit_balance_exhausted', 'message': 'no credits'}}
        agente = AgenteGPT('clave-falsa', 'gpt-5.5', self.esp, 'plan', 'Stiven')
        with mock.patch('desarrollador.gpt.requests.post', return_value=sin_saldo) as post, self.assertRaisesRegex(ErrorGemini, 'saldo'):
            agente.conversar('pedido')
        self.assertEqual(post.call_count, 1)

    def test_con_clave_de_openai_el_servicio_usa_gpt(self):
        from desarrollador.gpt import AgenteGPT
        cfg = Config({'DESARROLLADOR_TOKEN': 't', 'DESARROLLADOR_OPENAI_API_KEY': 'k', 'DESARROLLADOR_RAIZ': str(self.esp.raiz)})
        serv = Servicio(cfg, plataforma=PlataformaFalsa({}), espacio=self.esp)
        plan, impl = serv._agente('plan', {}), serv._agente('implementar', {})
        self.assertIsInstance(plan, AgenteGPT)
        self.assertEqual((plan.esfuerzo, impl.esfuerzo, plan.modelo_pedido), ('low', 'medium', 'gpt-5.5'))

    def test_proveedor_fijo_gana_sobre_las_otras_claves(self):
        cfg = Config({'DESARROLLADOR_TOKEN': 't', 'DESARROLLADOR_OPENAI_API_KEY': 'k', 'DESARROLLADOR_GEMINI_API_KEY': 'g',
                      'DESARROLLADOR_PROVEEDOR': 'Gemini', 'DESARROLLADOR_RAIZ': str(self.esp.raiz)})
        serv = Servicio(cfg, plataforma=PlataformaFalsa({}), espacio=self.esp)
        plan, impl = serv._agente('plan', {}), serv._agente('implementar', {})
        self.assertEqual((type(plan).__name__, plan.intervalo), ('Agente', 0))
        self.assertEqual((plan.modelos[0], impl.modelos[0]), ('gemini-3.8-flash', 'gemini-3.1-pro-preview-customtools'))  # Flash planea, Pro implementa


class AplicarLocalTests(unittest.TestCase):
    """El código local del usuario (con cambios sin commit) recibe el parche verificado y lo devuelve."""
    def setUp(self):
        from desarrollador.aplicar_local import AplicarLocal
        self.tmp = tempfile.TemporaryDirectory()
        raiz = Path(self.tmp.name)
        self.esp = Espacio(crear_repos(raiz))
        self.local = {}
        for n in ('backend', 'frontend'):
            subprocess.run(['git', 'clone', '-q', str(raiz / f'{n}.git'), str(raiz / 'local' / n)], check=True)
            self.local[n] = raiz / 'local' / n
        (self.local['frontend'] / 'src/App.jsx').write_text('export default function App() { return <h1>Hola local</h1>; }\n')
        (self.local['frontend'] / 'src/Nuevo.jsx').write_text('// archivo sin commit\n')
        self.ap = AplicarLocal(self.esp, self.local, raiz / 'aplicados', 'python', raiz / 'respaldos')
        self.eventos = []

    def tearDown(self):
        self.tmp.cleanup()

    def test_parte_del_codigo_local_aplica_y_deshace_sin_tocar_lo_demas(self):
        estado_antes = subprocess.run(['git', 'status', '--porcelain'], cwd=self.local['frontend'], capture_output=True, text=True).stdout
        self.esp.preparar('desarrollador/t5', self.ap.foto())
        self.assertIn('Hola local', self.esp.leer('frontend/src/App.jsx'))  # cambios sin commit incluidos
        self.assertIn('sin commit', self.esp.leer('frontend/src/Nuevo.jsx'))  # y archivos nuevos
        self.assertEqual(subprocess.run(['git', 'status', '--porcelain'], cwd=self.local['frontend'], capture_output=True, text=True).stdout,
                         estado_antes)  # la foto no toca el índice ni los archivos
        self.esp.reemplazar('frontend/src/App.jsx', 'Hola local', 'Hola azul')
        self.esp.commit('frontend', 'cambio', 'desarrollador/t5')
        self.assertIn('Hola azul', self.esp.diff('frontend'))
        info = self.ap.aplicar(5, self.eventos.append)
        self.assertEqual(info, {'repositorios': ['frontend'], 'migraciones_previas': {}, 'respaldo': ''})
        self.assertIn('Hola azul', (self.local['frontend'] / 'src/App.jsx').read_text())
        self.assertTrue((self.local['frontend'] / 'src/Nuevo.jsx').exists())
        self.ap.deshacer(5, info, self.eventos.append)
        self.assertIn('Hola local', (self.local['frontend'] / 'src/App.jsx').read_text())
        self.assertIn('Cambio deshecho en tu plataforma.', self.eventos)

    def test_no_aplica_si_el_codigo_local_cambio_y_no_deshace_si_hay_cambios_encima(self):
        self.esp.preparar('desarrollador/t6', self.ap.foto())
        self.esp.reemplazar('frontend/src/App.jsx', 'Hola local', 'Hola azul')
        self.esp.commit('frontend', 'cambio', 'desarrollador/t6')
        app = self.local['frontend'] / 'src/App.jsx'
        app.write_text('export default function App() { return <h1>Otra cosa</h1>; }\n')  # el usuario editó mientras tanto
        with self.assertRaisesRegex(ErrorEspacio, 'cambió en los mismos archivos'):
            self.ap.aplicar(6, self.eventos.append)
        self.assertIn('Otra cosa', app.read_text())  # nada a medias
        app.write_text('export default function App() { return <h1>Hola local</h1>; }\n')
        info = self.ap.aplicar(6, self.eventos.append)
        app.write_text(app.read_text().replace('Hola azul', 'Hola verde'))  # otra tarea cambió esa línea
        with self.assertRaisesRegex(ErrorEspacio, 'deshaz primero'):
            self.ap.deshacer(6, info, self.eventos.append)
        self.assertIn('Hola verde', app.read_text())

    def test_migraciones_nuevas_vuelven_a_la_anterior_al_deshacer(self):
        self.esp.preparar('desarrollador/t7', self.ap.foto())
        (self.esp.raiz / 'backend/ordenes/migrations/0086_campo_nuevo.py').write_text(  # la genera makemigrations, no el agente
            "dependencies = [('ordenes', '0085_tareas_desarrollador'), ('auth', '0012_x')]\n")
        self.esp.commit('backend', 'migración', 'desarrollador/t7')
        self.assertEqual(self.ap._previas(), {'ordenes': '0085_tareas_desarrollador'})


if __name__ == '__main__':
    unittest.main()
