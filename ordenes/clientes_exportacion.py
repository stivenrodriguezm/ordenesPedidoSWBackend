"""Descarga de clientes autorizada y registrada en el servidor."""
from io import BytesIO

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from .clientes_datos import filtrar_clientes
from .exportaciones import filtros_sin_datos_personales
from .models import Cliente, RegistroAuditoria
from .permissions import check_feature_permission, clientes_visibles, ve_todas_las_ventas
from .servicios import ErrorNegocio

LIMITE_EXPORTACION = 10000
COLUMNAS = (
    ('id', 'ID'), ('nombre', 'Nombre / Razón social'), ('cedula', 'Cédula / NIT'), ('correo', 'Correo'),
    ('direccion', 'Dirección'), ('barrio', 'Barrio'), ('ciudad', 'Ciudad'),
    ('telefono1', 'Teléfono 1'), ('telefono2', 'Teléfono 2'), ('tipo_persona', 'Tipo de persona'),
)


@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_CLIENTES'), check_feature_permission('EXPORTAR_CLIENTES')])
def exportar_clientes(request):
    qs, filtros = filtrar_clientes(clientes_visibles(request), request.query_params)
    campos = [c for c, _ in COLUMNAS]
    filas = list(qs.values_list(*campos)[:LIMITE_EXPORTACION + 1])
    if len(filas) > LIMITE_EXPORTACION:
        raise ErrorNegocio(f'La exportación supera {LIMITE_EXPORTACION} clientes. Acota la búsqueda; no se generó un archivo incompleto.', 413)

    # Hasta 10 000 filas: construir en memoria evita temporales con datos personales.
    libro = Workbook()
    hoja = libro.active
    hoja.title = 'Clientes'
    hoja.append([titulo for _, titulo in COLUMNAS])
    for fila in filas:
        celdas = []
        for campo, valor in zip(campos, fila):
            if campo == 'tipo_persona':
                valor = dict(Cliente.TIPO_PERSONA_CHOICES).get(valor, valor)
            texto = '' if valor is None else str(valor)
            if ILLEGAL_CHARACTERS_RE.search(texto):
                raise ErrorNegocio('Hay caracteres de control no admitidos por Excel. Revisa el formato de las fichas antes de exportar.', 400)
            celda = WriteOnlyCell(hoja, value=texto)
            # XLSX tiene tipos explícitos: nunca convertir texto del usuario
            # a fórmula ni perder ceros iniciales o el + de un teléfono.
            celda.data_type = 's'
            celda.number_format = '@'
            celdas.append(celda)
        hoja.append(celdas)
    salida = BytesIO()
    libro.save(salida)
    RegistroAuditoria.objects.create(usuario=request.user, accion='clientes.exportar',
        objeto_tipo='ReporteClientes', objeto_id='directorio', detalle={
            'formato': 'xlsx', 'columnas': campos, 'filas': len(filas),
            'alcance': 'global' if ve_todas_las_ventas(request) else 'propias_compartidas',
            'filtros': filtros_sin_datos_personales(filtros),
        })
    response = HttpResponse(salida.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="Clientes.xlsx"'
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
