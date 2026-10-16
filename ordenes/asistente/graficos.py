"""Gráficos construidos exclusivamente con resultados de consultas de este turno."""
import math

DECLARACION = {
    'name': 'graficar_consulta',
    'description': 'Muestra un gráfico real en el chat a partir de consulta_datos, ventas_por_asesor o tendencia_ventas. No inventes valores: selecciona consulta_id devuelto, tipo y métrica. Máximo 3 gráficos por respuesta.',
    'parameters': {'type': 'object', 'properties': {
        'consulta_id': {'type': 'string'},
        'tipo': {'type': 'string', 'enum': ['barras', 'lineas', 'dona']},
        'metrica': {'type': 'string', 'description': 'Clave numérica del resultado (p. ej. valor_vendido, total_atribuido o valor).'},
    }, 'required': ['consulta_id', 'tipo', 'metrica']},
}


def construir(args, resultados):
    fuente = resultados.get(args.get('consulta_id'))
    if not fuente or fuente.get('error'):
        raise ValueError('Primero consulta datos en este turno y usa su consulta_id.')
    filas = fuente.get('filas')
    etiqueta = 'etiqueta'
    columnas = fuente.get('columnas', {})
    if filas is None and 'asesores' in fuente:
        filas, etiqueta = fuente['asesores'], 'asesor'
        columnas = {'total_atribuido': 'COP', 'ventas_equivalentes': 'unidades', 'saldo_por_cobrar_atribuido': 'COP', 'cumplimiento_meta_pct': '%'}
    if filas is None and 'periodos' in fuente:
        filas, etiqueta = fuente['periodos'], 'periodo'
        columnas = {'valor': 'COP', 'abonado': 'COP', 'ventas': 'unidades', 'ticket_promedio': 'COP'}
    tipo, metrica = args.get('tipo'), args.get('metrica')
    if tipo not in ('barras', 'lineas', 'dona') or metrica not in columnas or columnas[metrica] not in ('COP', '%', 'unidades'):
        raise ValueError('Elige un tipo y una métrica numérica presentes en la consulta.')
    if not filas:
        raise ValueError('La consulta no tiene datos para graficar.')
    if len(filas) > 50:
        raise ValueError('Consulta hasta 50 grupos antes de graficar.')
    valores = [f.get(metrica) for f in filas]
    if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)) for v in valores):
        raise ValueError('Valores no válidos para el gráfico.')
    if all(v is None for v in valores):
        raise ValueError('La métrica no tiene valores registrados.')
    if tipo == 'dona' and (columnas[metrica] == '%' or fuente.get('truncado') or len(filas) > 10 or any(v is None or v < 0 for v in valores) or not sum(valores)):
        raise ValueError('La dona requiere hasta 10 grupos completos, valores no negativos y total positivo; usa barras.')
    periodo = fuente.get('filtros') or fuente.get('periodo') or {}
    nota = fuente.get('nota') or fuente.get('regla') or ''
    if fuente.get('truncado'):
        nota += f" Se muestran {len(filas)} de {fuente['grupos_totales']} grupos; no es el total."
    if fuente.get('periodo_actual_incompleto_hasta'):
        nota += ' Último período incompleto hasta ' + fuente['periodo_actual_incompleto_hasta'] + '.'
    return {'consulta_id': args['consulta_id'], 'tipo': tipo, 'titulo': metrica.replace('_', ' ').capitalize(),
            'metrica': metrica, 'unidad': columnas[metrica], 'etiquetas': [str(f[etiqueta])[:160] for f in filas],
            'valores': valores, 'fuente': fuente.get('dominio', 'ventas'), 'filtros': periodo,
            'consultado_en': fuente.get('consultado_en'), 'nota': nota.strip()}
