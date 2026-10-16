"""Exportaciones operativas: filtrar/autorizar/generar/auditar en servidor."""
from decimal import Decimal
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound, PermissionDenied
from .consultas_reportes import (
    FILTROS, consultar_ventas, consultar_recibos_caja,
    consultar_comprobantes_egreso, consultar_inventario,
)
from .exportaciones import respuesta_xlsx
from .permissions import tiene_permiso_codigo, ve_todas_las_ventas
from .serializers import ReciboCajaSerializer
from .servicios import ErrorNegocio

LIMITE_EXPORTACION = 10000
REPORTES = {
    'ventas': ('VER_VENTAS', consultar_ventas, 'Ventas'),
    'recibos': ('VER_RECIBOS', consultar_recibos_caja, 'Recibos_Caja'),
    'egresos': ('VER_COMPROBANTES_EGRESO', consultar_comprobantes_egreso, 'Comprobantes_Egreso'),
    'inventario': ('VER_INVENTARIO', consultar_inventario, 'Inventario_Lottus'),
}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def exportar_reporte(request, reporte):
    if reporte not in REPORTES:
        raise NotFound()
    permiso, consulta, nombre = REPORTES[reporte]
    if not tiene_permiso_codigo(request, permiso):
        raise PermissionDenied('No tienes permiso para consultar este reporte.')
    # Mantener el alcance de exportación que ofrecía la UI: ventas/recibos
    # exclusivos de administrador; egresos tiene permiso propio ya existente.
    if reporte in ('ventas', 'recibos') and request.user.role != 'administrador':
        raise PermissionDenied('Esta exportación requiere el rol administrador.')
    if reporte == 'egresos' and not tiene_permiso_codigo(request, 'EXPORTAR_EGRESOS'):
        raise PermissionDenied('Se requiere EXPORTAR_EGRESOS.')
    objetos = list(consulta(request)[:LIMITE_EXPORTACION + 1])
    if len(objetos) > LIMITE_EXPORTACION:
        raise ErrorNegocio(f'El filtro supera {LIMITE_EXPORTACION} registros. Acótalo; no se generó un archivo incompleto.', 413)
    columnas, filas = construir_filas(reporte, objetos, request)
    filtros = {k: request.query_params[k] for k in FILTROS[reporte] if request.query_params.get(k)}
    return respuesta_xlsx(request, nombre=nombre, columnas=columnas, filas=filas,
        accion=f'{reporte}.exportar', filtros=filtros,
        alcance='global' if reporte in ('inventario', 'egresos') or ve_todas_las_ventas(request) else 'propias_compartidas')


def construir_filas(reporte, objetos, request):
    if reporte == 'ventas':
        columnas = ['O.C.', 'F. Venta', 'F. Entrega', 'Vendedor', 'Sede', 'Feria del Hogar', 'Traslado', 'Cliente', 'Estado']
        precios = tiene_permiso_codigo(request, 'VER_PRECIOS_VENTA')
        if precios:
            columnas += ['Abono', 'Saldo', 'Valor']
        filas = []
        for v in objetos:
            nombres = [v.vendedor.first_name] if v.vendedor else []
            nombres += [u.first_name for u in v.vendedores_compartidos.all() if u.pk != v.vendedor_id]
            fila = [str(v.pk), v.fecha_venta, v.fecha_entrega, ', '.join(nombres), v.sede, 'Sí' if v.es_feria_hogar else 'No', 'Sí' if v.traslado else 'No', v.cliente.nombre, v.estado]
            if precios:
                fila += [v.abono, v.saldo, v.valor_total]
            filas.append(fila)
        return columnas, filas
    if reporte == 'recibos':
        serializer = ReciboCajaSerializer()
        return ['RC', 'Fecha', 'Venta', 'Vendedor', 'Método', 'Valor', 'Nota', 'Estado'], [
            [str(r.pk), r.fecha, str(r.venta_id), serializer.get_vendedor_nombre(r), serializer.get_metodo_pago(r), serializer.get_valor(r), r.nota, serializer.get_estado(r)] for r in objetos]
    if reporte == 'egresos':
        return ['ID', 'Fecha', 'Proveedor', 'Medio de Pago', 'Estado', 'Valor', 'Concepto', 'Descripción'], [
            [str(e.pk), e.fecha, e.proveedor.nombre_empresa if e.proveedor else '', e.medio_pago, e.estado, e.valor, e.concepto, e.descripcion] for e in objetos]
    columnas = ['ID Producto', 'Proveedor', 'Factura', 'Venta', 'Disponibilidad', 'F. Ingreso', 'Producto', 'Categoría', 'Subcategoría', 'Variación', 'Observación']
    costos = tiene_permiso_codigo(request, 'VER_COSTOS_INVENTARIO')
    if costos:
        columnas += ['Costo']
    filas = []
    for i in objetos:
        proveedor = i.referencia.proveedor if i.referencia and i.referencia.proveedor_id else (i.factura.proveedor if i.factura else None)
        fila = [i.pk, proveedor.nombre_empresa if proveedor else '', (i.factura.id_manual if i.factura else '') or i.factura_manual, str(i.venta_id or ''), i.get_disponibilidad_display(), i.fecha_ingreso, i.referencia.nombre if i.referencia else '', i.categoria.nombre if i.categoria else '', i.subcategoria.nombre if i.subcategoria else '', i.variacion, i.observacion]
        if costos:
            fila.append(i.costo_especifico if i.costo_especifico is not None else Decimal('0'))
        filas.append(fila)
    return columnas, filas
