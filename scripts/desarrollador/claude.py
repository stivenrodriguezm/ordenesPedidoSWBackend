"""Ciclo de herramientas del Desarrollador con Claude (SDK oficial `anthropic`, 2026-10-29).

Mismas herramientas, reglas y modos que gemini.py (plan / implementar); cambia el transporte:
- Streaming con entrada de herramientas en vivo (eager_input_streaming): el SDK ya no valida esa
  entrada, así que se valida contra el esquema antes de ejecutar y un error vuelve como tool_result.
- La respuesta del modelo se agrega tal cual al historial (incluye los bloques de pensamiento) y el
  historial solo crece: nunca se edita un turno anterior.
- Si la herramienta final llega junto con otras, esas se ejecutan antes de devolver; sus resultados
  (y el de la final) abren el siguiente mensaje para que el historial siga válido.
- fallbacks "default": si un clasificador rechaza la solicitud, la API la reintenta en el modelo
  que Anthropic recomienda para ese caso.
La clave nunca se registra ni se devuelve en errores.
"""
import logging
import time

import anthropic

from .espacio import ErrorEspacio
from .gemini import ESCRITURA, LECTURA, MAX_RESULTADO, PLAN, TERMINAR, Agente, ErrorGemini, error_de_entrada, sistema

log = logging.getLogger('desarrollador')


def _herramienta_claude(decl):
    return {'name': decl['name'], 'description': decl['description'], 'input_schema': decl['parameters'], 'eager_input_streaming': True}


class AgenteClaude(Agente):
    def __init__(self, clave, modelo, espacio, modo, usuario, al_evento=None, tiempo_max=1500, rondas_max=None, esfuerzo='high'):
        if not clave:
            raise ErrorGemini('Falta la clave de Anthropic del Desarrollador.')
        self.cliente = anthropic.Anthropic(api_key=clave, max_retries=4)
        self.modelo_pedido, self.espacio, self.modo, self.esfuerzo = modelo, espacio, modo, esfuerzo
        self.al_evento = al_evento or (lambda texto: None)
        self.limite = time.monotonic() + tiempo_max
        self.rondas_max = rondas_max or (30 if modo == 'plan' else 80)
        self.mensajes, self.pendientes = [], []
        self.tokens = 0
        self.modelo = None
        self.archivos_tocados = set()
        self.decl = {d['name']: d for d in LECTURA + ([PLAN] if modo == 'plan' else ESCRITURA + [TERMINAR])}
        self.herramientas = [_herramienta_claude(d) for d in self.decl.values()]
        self.sistema = sistema(modo, usuario)

    def _llamar(self):
        restante = self.limite - time.monotonic()
        if restante < 5:
            raise ErrorGemini('Se acabó el tiempo de trabajo de la tarea.')
        for intento in range(3):
            try:
                with self.cliente.with_options(timeout=max(30.0, min(900.0, restante))).beta.messages.stream(
                        model=self.modelo_pedido, max_tokens=64000, system=self.sistema, tools=self.herramientas,
                        messages=self.mensajes, output_config={'effort': self.esfuerzo}, cache_control={'type': 'ephemeral'},
                        betas=['server-side-fallback-2026-07-01'], fallbacks='default') as stream:
                    respuesta = stream.get_final_message()
                break
            except ValueError:  # JSON de una herramienta que el SDK no pudo leer: se repite el turno
                if intento == 2:
                    raise ErrorGemini('Claude devolvió varias veces una herramienta ilegible.') from None
            except anthropic.AuthenticationError:
                raise ErrorGemini('Anthropic rechazó la clave del Desarrollador (revisa DESARROLLADOR_ANTHROPIC_API_KEY).') from None
            except anthropic.PermissionDeniedError:
                raise ErrorGemini('La clave de Anthropic no tiene permiso para este modelo.') from None
            except anthropic.RateLimitError:
                raise ErrorGemini('Anthropic sigue limitando las solicitudes (cuota o saldo). Reintenta más tarde.') from None
            except anthropic.APIStatusError as exc:
                raise ErrorGemini(f'Claude rechazó la solicitud (HTTP {exc.status_code}).') from None
            except anthropic.APIConnectionError as exc:
                raise ErrorGemini(f'Sin conexión con Claude ({exc.__class__.__name__}).') from None
        u = respuesta.usage
        self.tokens += sum(int(getattr(u, campo, 0) or 0) for campo in
                           ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
        self.modelo = respuesta.model
        return respuesta

    def _resultado(self, bloque):
        decl = self.decl.get(bloque.name)
        error = f'herramienta desconocida: {bloque.name}' if decl is None else error_de_entrada(decl, bloque.input)
        if error:
            return {'type': 'tool_result', 'tool_use_id': bloque.id, 'is_error': True, 'content': f'Entrada inválida: {error}.'}
        try:
            texto = str(self._herramienta(bloque.name, bloque.input))
            es_error = False
        except ErrorEspacio as exc:
            texto, es_error = f'Error: {exc}', True
        except Exception as exc:  # noqa: BLE001 — se le informa al modelo y sigue
            texto, es_error = f'Error inesperado: {exc.__class__.__name__}', True
        if len(texto) > MAX_RESULTADO:
            texto = texto[:MAX_RESULTADO] + '\n… (resultado recortado)'
        return {'type': 'tool_result', 'tool_use_id': bloque.id, 'content': texto, **({'is_error': True} if es_error else {})}

    def conversar(self, mensaje):
        """Envía un mensaje y ejecuta herramientas hasta que el modelo llame la herramienta final.
        Devuelve (nombre_final, argumentos)."""
        self.mensajes.append({'role': 'user', 'content': [*self.pendientes, {'type': 'text', 'text': mensaje}]})
        self.pendientes = []
        final = 'proponer_plan' if self.modo == 'plan' else 'terminar'
        for _ in range(self.rondas_max):
            respuesta = self._llamar()
            if respuesta.stop_reason == 'refusal':
                motivo = getattr(respuesta.stop_details, 'category', None) if respuesta.stop_details else None
                raise ErrorGemini('Claude no aceptó hacer este pedido' + (f' (categoría: {motivo}).' if motivo else '.'))
            self.mensajes.append({'role': 'assistant', 'content': respuesta.content})
            usos = [b for b in respuesta.content if b.type == 'tool_use']
            if not usos:
                if respuesta.stop_reason == 'pause_turn':
                    continue
                self.mensajes.append({'role': 'user', 'content': f'Continúa usando las herramientas y termina con {final}.'})
                continue
            if respuesta.stop_reason == 'max_tokens':  # entrada cortada: se ve completa pero no lo está
                self.mensajes.append({'role': 'user', 'content': [
                    {'type': 'tool_result', 'tool_use_id': b.id, 'is_error': True,
                     'content': 'La respuesta se cortó antes de terminar esta herramienta. Haz cambios más pequeños (reemplazar_texto por partes).'}
                    for b in usos]})
                continue
            resultados, final_llamada = [], None
            for b in usos:
                log.info('%s → %s %s', self.modelo, b.name, (b.input or {}).get('ruta') or (b.input or {}).get('texto') or '')
                if b.name == final and final_llamada is None:
                    final_llamada = b
                else:
                    resultados.append(self._resultado(b))
            if final_llamada is not None:
                error = error_de_entrada(self.decl[final], final_llamada.input)
                if not error:
                    self.pendientes = [*resultados, {'type': 'tool_result', 'tool_use_id': final_llamada.id, 'content': 'Recibido.'}]
                    return final, final_llamada.input
                resultados.append({'type': 'tool_result', 'tool_use_id': final_llamada.id, 'is_error': True, 'content': f'Entrada inválida: {error}.'})
            self.mensajes.append({'role': 'user', 'content': resultados})
        raise ErrorGemini('El agente no terminó dentro del número de pasos permitido. Divide el pedido en partes más pequeñas.')
