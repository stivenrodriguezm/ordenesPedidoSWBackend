"""Primitivas de exportación: texto literal, límites y auditoría sin PII."""
import unicodedata

from django.utils.crypto import salted_hmac


def celda_csv(valor):
    """Protege texto; los números/Decimal conservan signo y precisión."""
    if not isinstance(valor, str):
        return valor
    inicio = valor
    while inicio and (inicio[0].isspace() or unicodedata.category(inicio[0]) in ('Cc', 'Cf')):
        inicio = inicio[1:]
    return "'" + valor if inicio.startswith(('=', '+', '-', '@')) else valor


def filtros_sin_datos_personales(filtros):
    # No registrar nombres, documentos ni contactos buscados en la bitácora.
    # HMAC permite contrastar un filtro conocido sin publicar hashes adivinables.
    return {campo: {'aplicado': bool(valor), 'huella': salted_hmac(
        'exportacion.filtro.v1', str(valor), algorithm='sha256').hexdigest()}
        for campo, valor in filtros.items() if valor}


def respuesta_xlsx(request, *, nombre, columnas, filas, accion, filtros, alcance):
    """Archivo acotado por el llamador. Texto literal y números explícitos."""
    from decimal import Decimal
    from io import BytesIO
    from django.http import HttpResponse
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from .models import RegistroAuditoria
    from .servicios import ErrorNegocio

    libro = Workbook()
    hoja = libro.active
    hoja.title = nombre[:31]
    hoja.append(columnas)
    for fila in filas:
        celdas = []
        for valor in fila:
            if isinstance(valor, (Decimal, int)) and not isinstance(valor, bool):
                celda = WriteOnlyCell(hoja, value=valor)
                celda.number_format = '#,##0.00' if isinstance(valor, Decimal) else '0'
            else:
                texto = '' if valor is None else str(valor)
                if ILLEGAL_CHARACTERS_RE.search(texto) or len(texto) > 32767:
                    raise ErrorNegocio('Un campo no se puede representar íntegramente en Excel. Revisa sus caracteres o longitud; no se generó un archivo parcial.', 400)
                celda = WriteOnlyCell(hoja, value=texto)
                celda.data_type = 's'
                celda.number_format = '@'
            celdas.append(celda)
        hoja.append(celdas)
    salida = BytesIO()
    libro.save(salida)
    RegistroAuditoria.objects.create(usuario=request.user, accion=accion,
        objeto_tipo='ReporteOperativo', objeto_id=nombre, detalle={
            'formato': 'xlsx', 'columnas': columnas, 'filas': len(filas),
            'alcance': alcance, 'filtros': filtros_sin_datos_personales(filtros),
        })
    response = HttpResponse(salida.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{nombre}.xlsx"'
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
