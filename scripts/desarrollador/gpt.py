"""Ciclo de herramientas del Desarrollador con GPT (API Responses de OpenAI, 2026-10-29).

Mismas herramientas, reglas y modos que gemini.py (plan / implementar):
- Cada turno manda solo lo nuevo y encadena la conversación con previous_response_id (OpenAI
  guarda el razonamiento entre llamadas a herramientas).
- tool_choice "required": el modelo siempre responde con herramientas, como con Gemini.
- La entrada de cada herramienta se valida contra su esquema antes de ejecutarla; un error vuelve
  al modelo como resultado de la herramienta.
- Si la herramienta final llega junto con otras, esas se ejecutan antes de devolver; sus resultados
  (y el de la final) abren el siguiente mensaje para que la conversación siga válida.
La clave nunca se registra ni se devuelve en errores.
"""
import json
import logging
import time

import requests

from .espacio import ErrorEspacio
from .gemini import ESCRITURA, LECTURA, MAX_RESULTADO, PLAN, TERMINAR, Agente, ErrorGemini, error_de_entrada, sistema

log = logging.getLogger('desarrollador')
URL = 'https://api.openai.com/v1/responses'


class AgenteGPT(Agente):
    def __init__(self, clave, modelo, espacio, modo, usuario, al_evento=None, tiempo_max=1500, rondas_max=None, esfuerzo='medium'):
        if not clave:
            raise ErrorGemini('Falta la clave de OpenAI del Desarrollador.')
        self.clave, self.modelo_pedido, self.espacio, self.modo, self.esfuerzo = clave, modelo, espacio, modo, esfuerzo
        self.al_evento = al_evento or (lambda texto: None)
        self.limite = time.monotonic() + tiempo_max
        self.rondas_max = rondas_max or (30 if modo == 'plan' else 80)
        self.anterior, self.pendientes = None, []
        self.tokens = 0
        self.modelo = None
        self.archivos_tocados = set()
        self.decl = {d['name']: d for d in LECTURA + ([PLAN] if modo == 'plan' else ESCRITURA + [TERMINAR])}
        self.herramientas = [{'type': 'function', 'name': d['name'], 'description': d['description'], 'parameters': d['parameters']}
                             for d in self.decl.values()]
        self.sistema = sistema(modo, usuario)

    def _llamar(self, entrada):
        cuerpo = {'model': self.modelo_pedido, 'instructions': self.sistema, 'input': entrada, 'tools': self.herramientas,
                  'tool_choice': 'required', 'max_output_tokens': 64000}
        if self.esfuerzo:
            cuerpo['reasoning'] = {'effort': self.esfuerzo}
        if self.anterior:
            cuerpo['previous_response_id'] = self.anterior
        espera = 5
        for intento in range(6):
            restante = self.limite - time.monotonic()
            if restante < 5:
                raise ErrorGemini('Se acabó el tiempo de trabajo de la tarea.')
            try:
                r = requests.post(URL, headers={'Authorization': f'Bearer {self.clave}'}, json=cuerpo, timeout=(10, max(30, min(900, restante))))
            except requests.RequestException as exc:  # sin el mensaje: podría incluir datos de la petición
                if intento >= 2:
                    raise ErrorGemini(f'Sin conexión con OpenAI ({exc.__class__.__name__}).') from None
                time.sleep(espera)
                continue
            if r.status_code == 200:
                datos = r.json()
                self.anterior, self.modelo = datos.get('id'), datos.get('model') or self.modelo_pedido
                self.tokens += int((datos.get('usage') or {}).get('total_tokens') or 0)
                return datos
            try:
                error = r.json().get('error') or {}
            except ValueError:
                error = {}
            if r.status_code == 401:
                raise ErrorGemini('OpenAI rechazó la clave del Desarrollador (revisa DESARROLLADOR_OPENAI_API_KEY).')
            if r.status_code == 429 and 'insufficient_quota' in (error.get('type'), error.get('code')):
                raise ErrorGemini('La cuenta de OpenAI no tiene saldo: recárgala en platform.openai.com → Billing y reintenta.')
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(float(r.headers.get('retry-after') or espera))
                espera = min(espera * 2, 60)
                continue
            raise ErrorGemini(f'OpenAI rechazó la solicitud (HTTP {r.status_code}): {str(error.get("message", ""))[:300]}')
        raise ErrorGemini('OpenAI sigue saturado después de varios intentos. Reintenta la tarea más tarde.')

    def _resultado(self, llamada, args):
        decl = self.decl.get(llamada.get('name'))
        error = f'herramienta desconocida: {llamada.get("name")}' if decl is None else error_de_entrada(decl, args)
        if error:
            texto = f'Entrada inválida: {error}.'
        else:
            try:
                texto = str(self._herramienta(llamada['name'], args))
            except ErrorEspacio as exc:
                texto = f'Error: {exc}'
            except Exception as exc:  # noqa: BLE001 — se le informa al modelo y sigue
                texto = f'Error inesperado: {exc.__class__.__name__}'
        if len(texto) > MAX_RESULTADO:
            texto = texto[:MAX_RESULTADO] + '\n… (resultado recortado)'
        return {'type': 'function_call_output', 'call_id': llamada['call_id'], 'output': texto}

    def conversar(self, mensaje):
        """Envía un mensaje y ejecuta herramientas hasta que el modelo llame la herramienta final.
        Devuelve (nombre_final, argumentos)."""
        entrada = [*self.pendientes, {'role': 'user', 'content': mensaje}]
        self.pendientes = []
        final = 'proponer_plan' if self.modo == 'plan' else 'terminar'
        for _ in range(self.rondas_max):
            datos = self._llamar(entrada)
            llamadas = [o for o in datos.get('output') or [] if o.get('type') == 'function_call']
            if not llamadas:
                motivo = (datos.get('incomplete_details') or {}).get('reason')
                entrada = [{'role': 'user', 'content': f'Continúa usando las herramientas y termina con {final}.'
                            + (' (Tu respuesta anterior se cortó: haz pasos más pequeños.)' if motivo else '')}]
                continue
            resultados, final_llamada = [], None
            for ll in llamadas:
                try:
                    args = json.loads(ll.get('arguments') or '{}')
                except ValueError:
                    args = None  # p. ej. cortada por max_output_tokens: la valida error_de_entrada
                log.info('%s → %s %s', self.modelo, ll.get('name'), (args or {}).get('ruta') or (args or {}).get('texto') or '')
                if ll.get('name') == final and final_llamada is None and not error_de_entrada(self.decl[final], args):
                    final_llamada = (ll, args)
                else:
                    resultados.append(self._resultado(ll, args))
            if final_llamada is not None:
                ll, args = final_llamada
                self.pendientes = [*resultados, {'type': 'function_call_output', 'call_id': ll['call_id'], 'output': 'Recibido.'}]
                return final, args
            entrada = resultados
        raise ErrorGemini('El agente no terminó dentro del número de pasos permitido. Divide el pedido en partes más pequeñas.')
