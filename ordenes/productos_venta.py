"""Productos de la venta, precio de lista congelado y compras por cantidades pendientes.

Reglas del usuario (2026-10-07):
- El precio se pacta GLOBAL (el valor de la venta); no hay precio unitario ni
  descuento por producto. El descuento de la venta se calcula después con la suma
  de los precios de lista de los productos (Venta.valor_lista → Nómina).
- La fecha de entrega es de la venta, no de cada producto. Sin "especificaciones":
  solo texto para el proveedor (o "No aplica") y texto para el cliente/remisión.
- La referencia de compra se infiere del producto del catálogo; se puede cambiar.
- (2026-10-08) Cada producto dice si lleva tela: no lleva, la incluye el proveedor del
  mueble o se compra aparte (con su proveedor de tela); en los dos últimos casos, en qué
  tela se vendió, con los mismos datos que un pedido de /telas: material (tela en metros
  o cuero en decímetros), referencia, color, proveedor y cantidad. La tela comprada
  aparte se pide desde la venta (un pedido por proveedor de tela + dirección); el pedido
  queda ligado al producto (`DetallePedidoTela.linea_venta`).
  La gestión de la venta se finaliza en `gestion_venta`.
- (2026-10-08) Además de productos, la venta lleva servicios y ajustes (`LineaVenta.tipo`):
  transporte, artículos adicionales sin referencia (jarrones…) y ajustes de negociación que
  suman o restan. Su valor entra completo al precio de lista; no se piden ni llevan tela.
- Al guardar, cada producto debe estar completo (referencia de compra, tela, texto para el
  proveedor); el cálculo de precio en vivo (`precio_producto`) no exige esos datos.
- (2026-10-15) El texto para el cliente y la remisión es opcional: sin él, la remisión usa
  el nombre del producto. La tela lleva su grupo (tela o cuero, une con la lista de precios
  aunque el producto no sea de catálogo) y el costo del proveedor por metro o decímetro.
  Conjuntos (comedor = mesa + sillas; cama = base + cabecero): piezas que se ven juntas en
  la venta y se piden y facturan por separado; un juego de la lista de precios se agrega
  como conjunto. `pendientes_factura` sugiere el costo de cada producto pedido: precio de
  lista ÷ multiplicador (sin la tela que se compra aparte), para revisar en la factura.
"""
import re
import unicodedata
import hashlib
import json
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from listaprecios import cache_catalogo, decorativos as deco, transportes
from listaprecios.models import CargoVariante, ComponenteJuego, GrupoTela, VarianteProducto
from listaprecios.decorativos import calcular_incluidos, da_decorativos, es_decorativo
from listaprecios.transportes import calcular_compartidos
from listaprecios.services import (PREFETCH_JUEGOS, calcular_precio, componentes_de, costo_lista, metraje_total,
                                   multiplicador_efectivo, obtener_multiplicador_general, resumen_componentes, usa_tela, grupo_aplicable,
                                   ids_opcionales, opcionales_piezas, precio_pieza, costos_propios, nombre_costos_propios,
                                   valor_cargo, vista_en_conjunto)
from . import gestion_venta
from .models import DetallePedido, DetallePedidoTela, DireccionEntrega, LineaVenta, OrdenPedido, PedidoTela, ProveedorTela, Referencia, Venta
from .permissions import tiene_permiso_codigo, ventas_visibles
from .servicios import ErrorNegocio, auditar, idempotente

CENT = Decimal('0.01')


def dinero(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def exigir(request, *permisos):
    if not any(tiene_permiso_codigo(request, p) for p in permisos):
        raise PermissionDenied('No tienes permiso para esta acción.')


def visible(request, pk):
    exigir(request, 'VER_VENTAS')
    return get_object_or_404(ventas_visibles(request), pk=pk)


def bloquear(pk, revision):
    venta = Venta.objects.select_for_update().get(pk=pk)
    if venta.estado == Venta.ESTADO_ANULADA:
        raise ErrorNegocio('La venta está anulada.', 409)
    if venta.revision_productos != revision:
        raise ErrorNegocio('Los productos cambiaron. Recarga antes de continuar.', 409)
    return venta


class AdicionalEntrada(serializers.Serializer):
    descripcion = serializers.CharField(max_length=255)
    importe_lista = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)


class LineaEntrada(serializers.Serializer):
    id = serializers.IntegerField(required=False, min_value=1)
    tipo = serializers.ChoiceField(choices=[c for c, _ in LineaVenta.TIPO_CHOICES], default=LineaVenta.TIPO_PRODUCTO)
    variante = serializers.PrimaryKeyRelatedField(queryset=VarianteProducto.objects.all(), allow_null=True, default=None)
    # Conjunto de la lista de precios dividido en piezas (2026-10-24): cada pieza es una línea
    # con su proveedor (`pieza`); los costos propios del conjunto, una línea de servicio (`juego`).
    juego = serializers.PrimaryKeyRelatedField(queryset=VarianteProducto.objects.all(), allow_null=True, default=None)
    pieza = serializers.PrimaryKeyRelatedField(queryset=ComponenteJuego.objects.select_related('variante'), allow_null=True, default=None)
    grupo_catalogo = serializers.PrimaryKeyRelatedField(queryset=GrupoTela.objects.all(), allow_null=True, default=None)
    referencia = serializers.PrimaryKeyRelatedField(queryset=Referencia.objects.select_related('proveedor'), allow_null=True, default=None)
    producto_nombre = serializers.CharField(max_length=255, allow_blank=True, default='')
    cantidad = serializers.IntegerField(min_value=1, max_value=10000)
    precio_unitario = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    descuento = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, default=0)
    opcionales = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=100, default=list)
    adicionales = AdicionalEntrada(many=True, default=list)
    # Los ajustes de negociación pueden restar: el signo se valida por tipo de línea.
    precio_lista_override = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True, default=None)
    motivo_precio = serializers.CharField(max_length=1000, allow_blank=True, default='')
    texto_proveedor = serializers.CharField(max_length=10000, allow_blank=True, default='')
    texto_cliente = serializers.CharField(max_length=10000, allow_blank=True, default='')
    sin_texto_proveedor = serializers.BooleanField(default=False)
    especificaciones = serializers.CharField(max_length=10000, allow_blank=True, default='')
    fecha_compromiso = serializers.DateField(allow_null=True, default=None)
    inventario_origen = serializers.CharField(max_length=50, allow_blank=True, allow_null=True, default=None)
    tela_modo = serializers.ChoiceField(choices=[c for c, _ in LineaVenta.TELA_MODO_CHOICES], allow_blank=True, default='')
    tela_material = serializers.ChoiceField(choices=['', 'tela', 'cuero'], allow_blank=True, default='')
    tela_referencia = serializers.CharField(max_length=255, allow_blank=True, default='')
    tela_color = serializers.CharField(max_length=255, allow_blank=True, default='')
    tela_proveedor = serializers.PrimaryKeyRelatedField(queryset=ProveedorTela.objects.all(), allow_null=True, default=None)
    tela_cantidad = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=CENT, allow_null=True, default=None)
    tela_grupo = serializers.PrimaryKeyRelatedField(queryset=GrupoTela.objects.all(), allow_null=True, default=None)
    tela_costo = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, allow_null=True, default=None)
    conjunto = serializers.RegexField(r'^[A-Za-z0-9-]{0,36}$', allow_blank=True, default='')
    conjunto_nombre = serializers.CharField(max_length=150, allow_blank=True, default='')
    conjunto_cantidad = serializers.IntegerField(min_value=1, max_value=1000, default=1)
    recalcular = serializers.BooleanField(default=False)


class DesgloseEntrada(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0)
    lineas = LineaEntrada(many=True, allow_empty=True)
    confirmar = serializers.BooleanField(default=False)
    distribuir_total = serializers.BooleanField(default=False)

    def validate_lineas(self, lineas):
        if len(lineas) > 300:
            raise ValidationError('Máximo 300 líneas por venta; usa cantidades para productos idénticos.')
        unidades = [d['inventario_origen'] for d in lineas if d.get('inventario_origen')]
        if len(unidades) != len(set(unidades)):
            raise ValidationError('Una unidad de stock está repetida.')
        ids = [d['id'] for d in lineas if d.get('id')]
        if len(ids) != len(set(ids)):
            raise ValidationError('Una línea está repetida.')
        return lineas


def _norm(texto):
    texto = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().lower()
    texto = re.sub(r'\(.*?\)|[^a-z0-9 ]', ' ', texto)
    return ' '.join(texto.split())


def referencias_sugeridas(variante):
    """Referencias de proveedor cuyo nombre coincide con el producto del catálogo,
    la más pedida primero (casi siempre la referencia es la del producto)."""
    if variante.linea.referencia_id:
        return [variante.linea.referencia]
    from django.db.models import Count
    nombre = _norm(variante.linea.nombre)
    if not nombre:
        return []
    candidatas = [nombre, nombre.split(' ')[0]]
    qs = Referencia.objects.select_related('proveedor').annotate(usos=Count('detallepedido'))
    for clave in candidatas:
        refs = [r for r in qs if _norm(r.nombre) == clave]
        if refs:
            return sorted(refs, key=lambda r: (-r.usos, r.pk))
    return []


def huella_config(d):
    config = {k: d[k] for k in ('opcionales', 'adicionales', 'precio_lista_override', 'motivo_precio')}
    config.update(variante=d['variante'].pk if d['variante'] else None,
                  grupo=d['grupo_catalogo'].pk if d['grupo_catalogo'] else None)
    if d.get('pieza'):
        config.update(juego=d['juego'].pk, pieza=d['pieza'].pk)
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()


def publicado_en_lista(v):
    from listaprecios.disposicion import retirada
    return (v.publicado and v.costo_confirmado if v.linea.referencia_id else v.linea.activo) and not retirada(v)


def preparar_adicional(d, anterior):
    """Servicio o ajuste de la venta: descripción y valor; no se pide ni lleva tela.
    Con `juego`, son los costos propios de un conjunto de la lista (su Transporte…): el
    valor sale de la lista de precios y va dentro del conjunto."""
    tipo, descripcion, valor = d['tipo'], d['producto_nombre'].strip(), d['precio_lista_override']
    juego, por_conjunto = d.get('juego'), None
    if juego is not None:
        if d.get('pieza') or tipo not in (LineaVenta.TIPO_TRANSPORTE, LineaVenta.TIPO_AJUSTE):
            raise ValidationError('Los costos de un conjunto van como transporte o ajuste.')
        veces = d['conjunto_cantidad'] if d['conjunto'] else 1
        grupo = d['grupo_catalogo'].pk if d['grupo_catalogo'] else None
        previo = anterior.precio_snapshot if anterior else {}
        # Ventas históricas: lo guardado se conserva aunque cambie la lista (multiplicador,
        # cargos…); solo se recalcula al pedirlo («Actualizar precio») o si cambia el conjunto.
        if (anterior and anterior.tipo == tipo and previo.get('juego') == juego.pk
                and previo.get('grupo', grupo) == grupo and not d['recalcular']):
            por_conjunto = Decimal(previo['por_conjunto']) if previo.get('por_conjunto') else \
                anterior.precio_lista_unitario / (anterior.conjunto_cantidad or 1)
        else:
            if not publicado_en_lista(juego):
                raise ValidationError('El conjunto está inactivo en la lista de precios.')
            por_conjunto = costos_propios(juego, d['grupo_catalogo'])
        valor = por_conjunto * veces
        descripcion = descripcion or nombre_costos_propios(juego)[0]
        if not valor:
            raise ValidationError('Este conjunto no tiene costos propios en la lista de precios.')
    faltan = {}
    if not descripcion:
        faltan['producto_nombre'] = 'Escribe qué es.'
    if juego is None and (valor is None or valor == 0 or (tipo != LineaVenta.TIPO_AJUSTE and valor < 0)):
        faltan['precio_lista_override'] = 'Indica el valor (un ajuste puede restar).' if tipo == LineaVenta.TIPO_AJUSTE else 'Indica el valor.'
    if faltan:
        raise ValidationError(faltan)
    if abs(valor) > Decimal('9999999999.99'):
        raise ValidationError({'precio_lista_override': 'El valor supera el límite permitido.'})
    if anterior and (anterior.detalles.exists() or anterior.inventario_origen_id or tela_pedida(anterior)):
        raise ValidationError('Este producto ya tiene pedidos; no se puede convertir en servicio o ajuste.')
    cantidad = d['cantidad'] if tipo == LineaVenta.TIPO_ARTICULO else 1
    valor = dinero(valor)
    return {'tipo': tipo, 'producto_nombre': descripcion[:255], 'variante': None, 'variante_nombre': '', 'categoria_nombre': '',
            'referencia': None, 'grupo_catalogo': None, 'grupo_tela': '', 'cantidad': cantidad, 'opcionales': [], 'adicionales': [],
            'precio_lista_unitario': valor, 'precio_unitario': valor, 'descuento': Decimal(0), 'subtotal': dinero(valor * cantidad),
            'costo_estimado': None, 'motivo_precio': '',
            'precio_snapshot': {'tipo': tipo, 'override': str(valor),
                                **({'juego': juego.pk, 'grupo': grupo, 'por_conjunto': str(por_conjunto)} if juego else {})},
            'texto_cliente': d['texto_cliente'].strip() or (descripcion if tipo == LineaVenta.TIPO_ARTICULO else ''),
            'texto_proveedor': '', 'sin_texto_proveedor': True, 'especificaciones': '', 'fecha_compromiso': None,
            'inventario_origen_id': None, 'tela_modo': LineaVenta.TELA_NO_APLICA, 'tela_material': '', 'tela_referencia': '',
            'tela_color': '', 'tela_proveedor': None, 'tela_cantidad': None, 'tela_grupo': None, 'tela_costo': None,
            'conjunto': d['conjunto'] if juego else '', 'conjunto_nombre': d['conjunto_nombre'].strip()[:150] if juego and d['conjunto'] else '',
            'conjunto_cantidad': d['conjunto_cantidad'] if juego and d['conjunto'] else 1}


def preparar_linea(request, venta, d, anterior=None, completo=True):
    """`completo=False` solo para el cálculo de precio en vivo: no exige los datos que
    el asesor aún está llenando (textos, referencia, tela)."""
    if d['tipo'] != LineaVenta.TIPO_PRODUCTO:
        return preparar_adicional(d, anterior)
    if anterior and anterior.tipo != LineaVenta.TIPO_PRODUCTO:
        raise ValidationError('Un servicio o ajuste no se convierte en producto: quítalo y agrega el producto.')
    v, grupo = d['variante'], d['grupo_catalogo']
    juego_lista, pieza = d.get('juego'), d.get('pieza')
    if (juego_lista or pieza) and not (juego_lista and pieza and pieza.juego_id == juego_lista.pk and v and pieza.variante_id == v.pk):
        raise ValidationError('La pieza no corresponde a ese conjunto de la lista de precios.')
    if pieza:
        v = vista_en_conjunto(v)  # sin los cargos que no se muestran en la agrupación
    huella = huella_config(d)
    conservar = anterior and anterior.precio_snapshot.get('config') == huella and not d['recalcular']
    if conservar:
        lista, costo, snapshot = anterior.precio_lista_unitario, anterior.costo_estimado, anterior.precio_snapshot
    else:
        manual = d['precio_lista_override']
        if manual is not None or d['adicionales'] or not v:
            exigir(request, 'AJUSTAR_PRECIO_LISTA_VENTA')
            # Un recargo ya dice qué es (su descripción); el motivo solo se exige
            # para un precio especial que reemplaza al del catálogo.
            if manual is not None and not d['motivo_precio'].strip():
                raise ValidationError({'motivo_precio': 'Explica por qué este producto lleva precio especial.'})
        if v:
            # Una pieza se vende con el conjunto: lo que debe estar publicado es el conjunto.
            if not publicado_en_lista(juego_lista or v):
                raise ValidationError('El producto está inactivo en el catálogo.')
            juego = resumen_componentes(v)
            lleva_tela = usa_tela(v)
            if lleva_tela and not grupo:
                raise ValidationError('Selecciona el grupo de tela/cuero de este producto.')
            if not lleva_tela and grupo:
                raise ValidationError('Este producto no utiliza grupo de tela.')
            grupos = set() if juego else set(v.precios.values_list('grupo_id', flat=True))
            if grupos and (grupo.pk if grupo else None) not in grupos:
                raise ValidationError('Ese grupo no está habilitado para la variante.')
            if grupo and not grupo_aplicable(v, grupo):
                raise ValidationError('Este material no tiene consumo o precio manual configurado para el producto.')
            permitidos = ids_opcionales(v)  # un conjunto incluye los opcionales de sus piezas
            if len(d['opcionales']) != len(set(d['opcionales'])) or not set(d['opcionales']) <= permitidos:
                raise ValidationError('Hay opcionales repetidos o de otro producto.')
            if pieza:
                calculado = precio_pieza(pieza, grupo, d['opcionales'])
                costo = costo_lista(v, grupo, d['opcionales'], costo_base_override=pieza.costo_unitario)
            else:
                calculado = calcular_precio(v, grupo, d['opcionales'])
                costo = costo_lista(v, grupo, d['opcionales'])
            mult = pieza.multiplicador if pieza and pieza.multiplicador is not None else multiplicador_efectivo(v)
            snapshot = {'base': str(0 if juego else v.costo_base), 'metraje': str(metraje_total(v, grupo.tipo if grupo else 'tela') or 0),
                        'costo_tela': str(grupo.precio_por_metro if grupo else 0),
                        'multiplicador': str(mult),
                        # Transporte y «cojines incluidos» como se venden hoy: la venta los conserva.
                        'transporte_unidad': str(transportes.valor_venta(v, d['opcionales'], mult)),
                        'cupo_transporte': transportes.cupo(v), 'da_decorativos': da_decorativos(v, d['opcionales']),
                        **({'tope_decorativo': str(deco.tope_por_unidad(v, grupo, deco.grupos_incluidos()))} if es_decorativo(v) else {}),
                        **({'juego': juego_lista.pk, 'pieza': pieza.pk} if pieza else {}),
                        'cargos': [{'id': c.pk, 'descripcion': c.descripcion,
                                    ('diferencia_precio' if c.tipo == 'diferencia_precio' else 'costo'): str(c.valor if c.tipo == 'diferencia_precio' else valor_cargo(
                                        c, 0 if juego else pieza.costo_unitario if pieza and pieza.costo_unitario is not None else v.costo_base, grupo)),
                                    **({'configuracion': {**c.especial.configuracion, **c.configuracion_especial}} if c.tipo == 'especial_producto' else {})}
                                   for c in v.cargos.all() if not c.opcional or c.pk in d['opcionales']]
                                  + [{'id': c.pk, 'descripcion': c.descripcion, 'pieza': comp.variante.nombre_catalogo, 'cantidad': comp.cantidad}
                                     for comp, c in opcionales_piezas(v) if c.pk in d['opcionales']],
                        'calculado': str(calculado), **({'juego': juego} if juego else {})}
        else:
            if not d['producto_nombre'] or manual is None:
                raise ValidationError('Un producto especial necesita nombre y precio de lista autorizado.')
            if grupo or d['opcionales']:
                raise ValidationError('El producto especial no tiene opciones de catálogo.')
            calculado, costo, snapshot = manual, None, {}
        lista = dinero(manual if manual is not None else calculado + sum((a['importe_lista'] for a in d['adicionales']), Decimal(0)))
        if d['adicionales']:
            # Un recargo de venta no informa su costo: nunca inventar el margen.
            costo = None
        if lista <= 0 or lista > Decimal('9999999999.99'):
            raise ValidationError('El precio de lista debe ser positivo y estar dentro del límite permitido.')
        snapshot.update(config=huella, override=str(manual) if manual is not None else None,
                        fecha=timezone.now().isoformat(), usuario=request.user.pk)
    if v and d['referencia'] is None:
        sugeridas = referencias_sugeridas(v)
        if sugeridas:
            d['referencia'] = sugeridas[0]
    if (v and v.linea.referencia_id and d['referencia'] and d['referencia'].pk != v.linea.referencia_id
            and not (conservar and anterior.referencia_id == d['referencia'].pk)):
        raise ValidationError({'referencia': 'La referencia de compra debe ser la del producto seleccionado en la lista de precios.'})
    if completo:
        faltan = {}
        if not d['referencia'] and not d['inventario_origen']:
            faltan['referencia'] = 'Elige la referencia de compra (proveedor) de este producto.'
        if not d['texto_proveedor'].strip() and not d['sin_texto_proveedor'] and not d['inventario_origen']:
            faltan['texto_proveedor'] = 'Escribe el texto para el proveedor o marca "No aplica".'
        # El texto para el cliente y la remisión es opcional (sin él, va el nombre del producto).
        if d['conjunto'] and not d['conjunto_nombre'].strip():
            faltan['conjunto_nombre'] = 'Ponle nombre al conjunto (p. ej. «Comedor 6 puestos»).'
        if faltan:
            raise ValidationError(faltan)
    precio = d.get('precio_unitario', anterior.precio_unitario if anterior else lista)
    subtotal = dinero(precio * d['cantidad'] - d['descuento'])
    if subtotal < 0 or subtotal > Decimal('9999999999.99'):
        raise ValidationError('El descuento supera el importe o el subtotal excede el límite.')
    campos = {k: d[k] for k in ('variante', 'referencia', 'grupo_catalogo', 'cantidad', 'descuento',
                               'motivo_precio', 'texto_cliente', 'texto_proveedor', 'sin_texto_proveedor',
                               'especificaciones', 'fecha_compromiso')}
    campos.update(preparar_tela(d, v, anterior, completo), tipo=LineaVenta.TIPO_PRODUCTO,
                  conjunto=d['conjunto'], conjunto_nombre=d['conjunto_nombre'].strip()[:150] if d['conjunto'] else '',
                  conjunto_cantidad=d['conjunto_cantidad'] if d['conjunto'] else 1)
    from listaprecios.referencias import categoria_variante, nombre_linea
    categoria = categoria_variante(v) if v else None
    campos.update(producto_nombre=nombre_linea(v.linea) if v else d['producto_nombre'], variante_nombre=v.nombre_catalogo if v else '',
                  categoria_nombre=categoria.nombre if categoria else '', grupo_tela=grupo.nombre if grupo else '',
                  opcionales=d['opcionales'], adicionales=[{'descripcion': a['descripcion'], 'importe_lista': str(a['importe_lista'])} for a in d['adicionales']],
                  precio_lista_unitario=lista, precio_unitario=precio, subtotal=subtotal,
                  costo_estimado=costo, precio_snapshot=snapshot, inventario_origen_id=d['inventario_origen'] or None)
    if anterior and (anterior.detalles.exists() or anterior.inventario_origen_id):
        for campo in ('variante', 'referencia', 'grupo_catalogo'):
            if getattr(anterior, f'{campo}_id') != (d[campo].pk if d[campo] else None):
                raise ValidationError('Este producto ya tiene operaciones. Conserva su identidad y agrega otra línea para un producto diferente.')
        if anterior.inventario_origen_id != campos['inventario_origen_id']:
            raise ValidationError('Una unidad vinculada se cambia desde Inventario antes de corregir el desglose.')
        comprometida = anterior.detalles.exclude(orden__estado='anulado').aggregate(n=Sum('cantidad'))['n'] or 0
        if d['cantidad'] < comprometida:
            raise ValidationError(f'Ya se pidieron {comprometida} unidades; no puedes reducir la cantidad por debajo de ese valor.')
    if campos['inventario_origen_id']:
        from suministros.models import Inventario
        exigir(request, 'VER_INVENTARIO')
        item = get_object_or_404(Inventario.objects.select_for_update(), pk=campos['inventario_origen_id'])
        if d['cantidad'] != 1 or item.venta_id != venta.pk or item.detalle_pedido_id:
            raise ValidationError('Elige una unidad de stock ya asignada a esta venta, sin pedido asociado y con cantidad 1.')
        if item.referencia_id != (d['referencia'].pk if d['referencia'] else None):
            raise ValidationError('La referencia debe coincidir con la unidad de inventario.')
        if LineaVenta.objects.filter(inventario_origen=item).exclude(pk=anterior.pk if anterior else None).exists():
            raise ValidationError('Esta unidad ya está vinculada a otra línea.')
    return campos


def como_se_vendio(preparadas):
    """Por línea, el transporte y los «cojines incluidos» que guardó al venderse, para que un
    cambio posterior de la lista (multiplicador, cargos) no altere la venta. Las líneas guardadas
    antes de 2026-10-24 no los tienen: se deducen de sus cargos y multiplicador guardados."""
    ids = {x['id'] for _, c in preparadas for x in (c['precio_snapshot'] or {}).get('cargos', []) if x.get('id')}
    tipos = {pk: (tipo, cupo) for pk, tipo, cupo in CargoVariante.objects.filter(pk__in=ids).values_list('pk', 'tipo', 'unidades_por_transporte')}
    incluidos = None
    resultado = []
    for _, c in preparadas:
        s = c['precio_snapshot'] or {}
        valores = {}
        if 'transporte_unidad' in s:
            valores = {'valor_transporte': s['transporte_unidad'], 'cupo': s.get('cupo_transporte'), 'da_decorativos': bool(s.get('da_decorativos'))}
            if s.get('tope_decorativo') is not None:
                valores['tope'] = s['tope_decorativo']
        elif s.get('multiplicador') and isinstance(s.get('cargos'), list) and c['variante']:
            cargos = [(x, tipos[x['id']]) for x in s['cargos'] if x.get('id') in tipos]
            transporte = next(((x, t) for x, t in cargos if t[0] == CargoVariante.TIPO_TRANSPORTE and 'costo' in x), None)
            valores = {'valor_transporte': Decimal(transporte[0]['costo']) * Decimal(s['multiplicador']) if transporte else 0,
                       'da_decorativos': any(t[0] == CargoVariante.TIPO_DECORATIVOS for _, t in cargos)}
            if transporte:
                valores['cupo'] = transporte[1][1]
            if es_decorativo(c['variante']):
                incluidos = deco.grupos_incluidos() if incluidos is None else incluidos
                valores['tope'] = min(c['precio_lista_unitario'], deco.tope_por_unidad(c['variante'], c['grupo_catalogo'], incluidos))
        resultado.append(valores)
    return resultado


def aplicar_decorativos(preparadas):
    """«Cojines incluidos»: cada producto con «Decorativos x2» cubre 2 decorativos por unidad
    (listaprecios/decorativos.py). Anota en cada decorativo lo cubierto y devuelve el total."""
    vendidos = como_se_vendio(preparadas)
    items = [{'clave': i, 'variante': c['variante'], 'grupo': c['grupo_catalogo'], 'cantidad': c['cantidad'], 'opcionales': c['opcionales'],
              **{k: x for k, x in vendidos[i].items() if k in ('da_decorativos', 'tope')}}
             for i, (_, c) in enumerate(preparadas) if c['tipo'] == LineaVenta.TIPO_PRODUCTO and c['variante']]
    incluidos = calcular_incluidos(items)
    total = Decimal(0)
    for i, (_, c) in enumerate(preparadas):
        snapshot = dict(c['precio_snapshot'] or {})
        snapshot.pop('decorativos', None)
        if i in incluidos:
            valor = min(incluidos[i]['valor'], dinero(c['precio_lista_unitario'] * c['cantidad']))
            snapshot['decorativos'] = {'unidades': incluidos[i]['unidades'], 'valor': str(valor)}
            total += valor
        c['precio_snapshot'] = snapshot
    return total


def aplicar_transportes(preparadas):
    """Transporte por envío (listaprecios/transportes.py): las piezas de un conjunto cobran uno
    solo y cada transporte lleva su cupo de unidades. Anota lo descontado en cada línea."""
    vendidos = como_se_vendio(preparadas)
    items = [{'clave': i, 'variante': c['variante'], 'cantidad': c['cantidad'], 'opcionales': c['opcionales'],
              'conjunto': c.get('conjunto') or '', 'conjunto_cantidad': c.get('conjunto_cantidad') or 1,
              **{k: x for k, x in vendidos[i].items() if k in ('valor_transporte', 'cupo')}}
             for i, (_, c) in enumerate(preparadas) if c['tipo'] == LineaVenta.TIPO_PRODUCTO and c['variante']
             and not (c['precio_snapshot'] or {}).get('pieza')]  # su transporte va en los costos del conjunto
    compartidos = calcular_compartidos(items)
    total = Decimal(0)
    for i, (_, c) in enumerate(preparadas):
        snapshot = dict(c['precio_snapshot'] or {})
        snapshot.pop('transporte', None)
        if i in compartidos:
            disponible = dinero(c['precio_lista_unitario'] * c['cantidad']) - incluido_de(c)
            valor = min(dinero(compartidos[i]['valor']), max(disponible, Decimal(0)))
            snapshot['transporte'] = {'transportes': compartidos[i]['transportes'], 'valor': str(valor)}
            total += valor
        c['precio_snapshot'] = snapshot
    return total


def productos_sin_cambios(actuales, ids, preparadas):
    """True si la venta conserva exactamente sus productos guardados: ninguno nuevo, quitado,
    con otra cantidad o configuración, ni con precio actualizado."""
    if any(l.tipo == LineaVenta.TIPO_PRODUCTO and l.pk not in ids for l in actuales.values()):
        return False
    productos = [(l, c) for l, c in preparadas if c['tipo'] == LineaVenta.TIPO_PRODUCTO]
    return bool(productos) and all(
        l is not None and c['precio_snapshot'] is l.precio_snapshot and c['cantidad'] == l.cantidad
        and (c['conjunto'] or '') == (l.conjunto or '') and c['conjunto_cantidad'] == l.conjunto_cantidad
        for l, c in productos)


def incluido_de(campos):
    return Decimal((campos['precio_snapshot'] or {}).get('decorativos', {}).get('valor') or 0)


def descontado_de(campos):
    """Lo que no se cobra de la línea: decorativos incluidos y transporte compartido."""
    return incluido_de(campos) + Decimal((campos['precio_snapshot'] or {}).get('transporte', {}).get('valor') or 0)


def repartir(valor_total, items):
    """El precio se pacta global: reparte el valor de la venta entre los productos en
    proporción a su precio de lista (solo para márgenes por producto; nadie lo digita).
    Los servicios y ajustes valen exactamente lo que dicen; los productos se reparten
    el resto. `items` = [(precio_lista_unitario, cantidad[, tipo])]; un dict por línea."""
    items = [(lista or Decimal(0), cant, (resto or [LineaVenta.TIPO_PRODUCTO])[0]) for lista, cant, *resto in items]
    fijos = sum((lista * cant for lista, cant, tipo in items if tipo != LineaVenta.TIPO_PRODUCTO), Decimal(0))
    productos = [(lista, cant) for lista, cant, tipo in items if tipo == LineaVenta.TIPO_PRODUCTO]
    restante = valor_total - fijos
    if productos and restante < 0:
        raise ValidationError('El valor de la venta es menor que la suma de servicios y ajustes. Revisa los valores.')
    total_lista = sum((lista * cant for lista, cant in productos), Decimal(0))
    repartos, acumulado, peso = [], Decimal(0), Decimal(0)
    for idx, (lista, cant) in enumerate(productos):
        if not total_lista:
            repartos.append({})
            continue
        peso += lista * cant
        objetivo = restante if idx == len(productos) - 1 else dinero(restante * peso / total_lista)
        neto, acumulado = objetivo - acumulado, objetivo
        # Redondear hacia arriba evita descuentos negativos por centavos.
        precio = max(lista, (neto / cant).quantize(CENT, rounding=ROUND_CEILING))
        repartos.append({'precio_unitario': precio, 'descuento': precio * cant - neto, 'subtotal': neto})
    repartos = iter(repartos)
    return [next(repartos) if tipo == LineaVenta.TIPO_PRODUCTO
            else {'precio_unitario': lista, 'descuento': Decimal(0), 'subtotal': dinero(lista * cant)} for lista, cant, tipo in items]


CAMPOS_TELA = ('tela_modo', 'tela_material', 'tela_referencia', 'tela_color', 'tela_proveedor', 'tela_cantidad')


def preparar_tela(d, v, anterior, completo=True):
    modo = d['tela_modo'] or (LineaVenta.TELA_NO_APLICA if v and not usa_tela(v) else '')
    referencia, color = d['tela_referencia'].strip(), d['tela_color'].strip()
    material, proveedor, cantidad = d['tela_material'], d['tela_proveedor'], d['tela_cantidad']
    # El grupo de la tela: el elegido o, en un producto de catálogo con tela, el de su precio.
    grupo, costo = d['tela_grupo'], d['tela_costo']
    if modo == LineaVenta.TELA_NO_APLICA:
        material, referencia, color, proveedor, cantidad = '', '', '', None, None
        grupo = costo = None
    elif modo:
        # Sin indicarlo, el material sale del grupo (grupo de cuero → cuero, en decímetros).
        precio = d['grupo_catalogo']
        if not material:
            material = (grupo or precio).tipo if (grupo or precio) else 'tela'
        if not grupo and precio and precio.tipo == material:
            grupo = precio
        if grupo and grupo.tipo != material:
            raise ValidationError({'tela_grupo': f'«{grupo.nombre}» es un grupo de {grupo.get_tipo_display().lower()}; elige un grupo de {material}.'})
        if modo == LineaVenta.TELA_INCLUIDA:
            costo = None  # la pone el proveedor del mueble: va dentro de su precio, sin costo aparte
        elif costo is None and grupo and grupo.precio_por_metro:
            costo = grupo.precio_por_metro  # costo de la lista de precios; se puede corregir
        if modo == LineaVenta.TELA_INCLUIDA:
            proveedor = cantidad = None
        elif cantidad is None and v and metraje_total(v, material):
            cantidad = dinero(metraje_total(v, material) * d['cantidad'])
    else:
        proveedor = cantidad = grupo = costo = None
    pedida = bool(anterior and tela_pedida(anterior))
    if completo:
        faltan = {}
        if not modo:
            faltan['tela_modo'] = 'Indica si el producto lleva tela.'
        elif modo != LineaVenta.TELA_NO_APLICA:
            nombre = 'del cuero' if material == 'cuero' else 'de la tela'
            if not referencia:
                faltan['tela_referencia'] = f'Escribe la referencia {nombre}.'
            if not color:
                faltan['tela_color'] = f'Escribe el color {nombre}.'
            if modo == LineaVenta.TELA_APARTE and not proveedor:
                faltan['tela_proveedor'] = f'Elige el proveedor {nombre}.'
            if modo == LineaVenta.TELA_APARTE and not cantidad:
                faltan['tela_cantidad'] = f'Indica la cantidad {nombre}.'
            if not grupo and not pedida:
                faltan['tela_grupo'] = f'Elige el grupo {nombre}.'
            if modo == LineaVenta.TELA_APARTE and costo is None and not pedida:
                unidad = 'decímetro' if material == 'cuero' else 'metro'
                faltan['tela_costo'] = f'Indica el costo del proveedor por {unidad}.'
        if faltan:
            raise ValidationError(faltan)
    tela = dict(zip(CAMPOS_TELA, (modo, material, referencia, color, proveedor, cantidad)))
    if pedida:
        antes = tuple(getattr(anterior, c + '_id' if c == 'tela_proveedor' else c) for c in CAMPOS_TELA)
        ahora = tuple(x.pk if c == 'tela_proveedor' and x else x for c, x in tela.items())
        if antes != ahora:
            raise ValidationError({'tela_referencia': 'La tela de este producto ya se pidió. Para cambiarla, elimina primero ese pedido en Telas.'})
    # El grupo y el costo no cambian el pedido de tela: se pueden completar después.
    tela.update(tela_grupo=grupo, tela_costo=dinero(costo) if costo is not None else None)
    return tela


def auditoria_lineas(lineas):
    campos = ('tela_modo', 'tela_material', 'tela_referencia', 'tela_color', 'tela_proveedor_id', 'tela_cantidad', 'tela_grupo_id',
              'tela_costo', 'conjunto', 'conjunto_nombre', 'conjunto_cantidad', 'id', 'variante_id', 'referencia_id', 'grupo_catalogo_id', 'cantidad', 'producto_nombre',
              'precio_lista_unitario', 'precio_unitario', 'descuento', 'subtotal', 'precio_snapshot',
              'adicionales', 'opcionales', 'motivo_precio', 'texto_cliente', 'texto_proveedor',
              'sin_texto_proveedor', 'especificaciones', 'inventario_origen_id', 'fecha_compromiso')
    return [{k: getattr(l, k) for k in campos} for l in lineas]


def representar(request, venta):
    from .serializers import LineaVentaSerializer
    lineas = list(venta.lineas.select_related('referencia__proveedor', 'variante', 'grupo_catalogo', 'tela_proveedor', 'tela_grupo').prefetch_related(
        Prefetch('detalles', queryset=DetallePedido.objects.exclude(orden__estado='anulado').prefetch_related('unidades_recibidas')),
        Prefetch('detalles_tela', queryset=DetallePedidoTela.objects.select_related('pedido'))).all())
    direcciones = {x.nombre.strip().lower(): x for x in DireccionEntrega.objects.all()}
    data = LineaVentaSerializer(lineas, many=True, context={'ver_margenes': tiene_permiso_codigo(request, 'VER_MARGENES')}).data
    for l, d in zip(lineas, data):
        detalles = list(l.detalles.all())
        d['pedidas'] = sum(x.cantidad for x in detalles)
        d['por_pedir'] = max(l.cantidad - d['pedidas'] - (1 if l.inventario_origen_id else 0), 0) if l.tipo == LineaVenta.TIPO_PRODUCTO else 0
        d['proveedor_nombre'] = l.referencia.proveedor.nombre_empresa if l.referencia_id else ''
        d['proveedor'] = l.referencia.proveedor_id if l.referencia_id else None
        d['referencia_nombre'] = l.referencia.nombre if l.referencia_id else ''
        d['precio_lista_override'] = l.precio_snapshot.get('override')
        d['juego'] = l.precio_snapshot.get('juego')
        d['pieza'] = l.precio_snapshot.get('pieza')
        d['opcionales'] = [o['id'] if isinstance(o, dict) else o for o in l.opcionales if not isinstance(o, dict) or 'id' in o]
        d['pedidos'] = [{'id': x.orden_id, 'detalle': x.pk, 'cantidad': x.cantidad,
                         'recibidas': sum(1 for u in x.unidades_recibidas.all() if u.disponibilidad != 'devuelto_proveedor')} for x in detalles]
        d['tela_modo'] = gestion_venta.tela_modo(l)
        d['lleva_tela_catalogo'] = bool(l.variante_id and usa_tela(l.variante))
        d['tela_proveedor_nombre'] = l.tela_proveedor.nombre_empresa if l.tela_proveedor_id else ''
        d['tela_unidad'] = 'dm' if l.tela_material == 'cuero' else 'm'
        d['grupo_es_cuero'] = bool(l.grupo_catalogo_id and l.grupo_catalogo.tipo == 'cuero')
        d['tela_grupo_nombre'] = l.tela_grupo.nombre if l.tela_grupo_id else ''
        # «Cojines incluidos»: el producto da 2 decorativos por unidad; un decorativo cubierto lo indica.
        d['da_decorativos'] = bool(l.variante_id and da_decorativos(l.variante, d['opcionales']))
        d['decorativos_incluidos'] = l.precio_snapshot.get('decorativos')
        d['transporte_compartido'] = l.precio_snapshot.get('transporte')
        d['tela_pedidos'] = [{'id': t.pedido_id, 'estado': t.pedido.estado, 'cantidad': str(t.cantidad), 'tela': t.tela}
                             for t in l.detalles_tela.all() if t.pedido.estado != PedidoTela.ANULADO]
        orden = next((x.orden_id for x in detalles), None)
        d['tela_orden'] = orden
        sugerida = direcciones.get(l.referencia.proveedor.nombre_empresa.strip().lower()) if l.referencia_id else None
        d['tela_direccion_sugerida'] = f'{sugerida.nombre} - {sugerida.detalles}' if sugerida else ''
    return {'gestion': gestion_venta.resumen(venta, data),
            'fecha_entrega': str(venta.fecha_entrega) if venta.fecha_entrega else None, 'es_feria_hogar': venta.es_feria_hogar,
            'vendedor_nombre': venta.vendedor.first_name or venta.vendedor.username,'venta': venta.pk, 'revision': venta.revision_productos, 'confirmados': venta.productos_confirmados,
            'pedidos_sin_vincular': [{'detalle': d.pk, 'pedido': d.orden_id, 'referencia': d.referencia_id,
                                     'referencia_nombre': d.referencia.nombre if d.referencia else '',
                                     'cantidad': d.cantidad, 'texto': d.especificaciones}
                                    for d in DetallePedido.objects.filter(orden__venta=venta, linea_venta__isnull=True, ignorar_vinculo=False)
                                    .exclude(orden__estado='anulado').select_related('referencia')],
            'valor_total': str(venta.valor_total), 'valor_lista': str(venta.valor_lista) if venta.valor_lista is not None else None, 'lineas': data}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def productos(request, venta_id):
    venta = visible(request, venta_id)
    exigir(request, 'VER_PRECIOS_VENTA')
    if request.method == 'GET':
        return Response(representar(request, venta))
    exigir(request, 'EDITAR_PRODUCTOS_VENTA', 'EDITAR_VENTA')
    return guardar(request, venta_id)


@idempotente('venta.productos')
@transaction.atomic
def guardar(request, venta_id):
    entrada = DesgloseEntrada(data=request.data)
    entrada.is_valid(raise_exception=True)
    datos = entrada.validated_data
    venta = bloquear(venta_id, datos['revision'])
    actuales = {l.pk: l for l in venta.lineas.select_for_update().all()}
    antes = auditoria_lineas(actuales.values())
    preparadas = []
    for i, d in enumerate(datos['lineas']):
        if d.get('id') and d['id'] not in actuales:
            raise ValidationError({'lineas': {i: 'La línea no pertenece a esta venta.'}})
        try:
            preparadas.append((actuales.get(d.get('id')), preparar_linea(request, venta, d, actuales.get(d.get('id')))))
        except ValidationError as exc:
            raise ValidationError({'lineas': {i: exc.detail}})
    ids = {d.get('id') for d in datos['lineas']}
    for l in actuales.values():
        if l.pk not in ids:
            if l.detalles.exists() or l.inventario_origen_id:
                raise ValidationError('No se elimina una línea con pedidos o inventario vinculado.')
            l.delete()
    if productos_sin_cambios(actuales, ids, preparadas):
        # Solo cambiaron textos, tela u otros datos: los descuentos quedan como se vendieron,
        # aunque la lista de precios haya cambiado desde entonces.
        incluido = sum((descontado_de(c) for _, c in preparadas if c['tipo'] == LineaVenta.TIPO_PRODUCTO), Decimal(0))
    else:
        incluido = aplicar_decorativos(preparadas)
        incluido += aplicar_transportes(preparadas)
    total_lista = sum((c['precio_lista_unitario'] * c['cantidad'] for _, c in preparadas), Decimal(0)) - incluido
    if preparadas and total_lista <= 0:
        raise ValidationError('El precio de lista total debe ser positivo: revisa los ajustes que restan.')
    if total_lista > Decimal('9999999999.99'):
        raise ValidationError('El total de lista supera el límite permitido.')
    # El valor de la venta se reparte sobre lo que se cobra: un decorativo incluido pesa menos (o nada).
    efectivos = [((c['precio_lista_unitario'] * c['cantidad'] - descontado_de(c)) / c['cantidad']).quantize(CENT) for _, c in preparadas]
    for (_, c), reparto in zip(preparadas, repartir(venta.valor_total, [(e, c['cantidad'], c['tipo']) for e, (_, c) in zip(efectivos, preparadas)])):
        c.update(reparto)
    for l, campos in preparadas:
        if l:
            for k, v in campos.items():
                setattr(l, k, v)
            l.save()
        else:
            LineaVenta.objects.create(venta=venta, **campos)
    venta.revision_productos += 1
    venta.productos_confirmados = bool(preparadas)
    venta.valor_lista = total_lista if preparadas else None
    venta.save(update_fields=['revision_productos', 'productos_confirmados', 'valor_lista'])
    auditar(request.user, 'venta.productos', venta, {'revision': venta.revision_productos, 'confirmados': venta.productos_confirmados,
                                                  'total_lista': str(total_lista), 'antes': antes, 'despues': auditoria_lineas(venta.lineas.all())})
    return Response(gestion_venta.reabrir_si_falta(request, venta, representar(request, venta)))


class PedidoLineaEntrada(serializers.Serializer):
    linea = serializers.IntegerField(min_value=1)
    cantidad = serializers.IntegerField(min_value=1, max_value=10000)
    texto_proveedor = serializers.CharField(max_length=10000, allow_blank=True, required=False)


ESTADOS_TELA_OP = ['Sin tela', 'Por pedir', 'Pedida']


class OrdenEntrada(serializers.Serializer):
    """Datos propios de cada orden (una por proveedor), como en Crear pedido."""
    proveedor = serializers.IntegerField(min_value=1)
    fecha_esperada = serializers.DateField(required=False)
    observacion = serializers.CharField(max_length=10000, allow_blank=True, default='')
    tela = serializers.ChoiceField(choices=ESTADOS_TELA_OP, required=False)


class PedidosEntrada(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0)
    fecha_esperada = serializers.DateField()
    lineas = PedidoLineaEntrada(many=True, allow_empty=False)
    ordenes = OrdenEntrada(many=True, default=list)


def estado_tela_de(lineas):
    """Estado de tela de una orden según sus productos (mismos valores que /ordenes)."""
    aparte = [l for l in lineas if gestion_venta.tela_modo(l) == LineaVenta.TELA_APARTE]
    if not aparte:
        return 'Sin tela'
    return 'Pedida' if all(tela_pedida(l) for l in aparte) else 'Por pedir'


def tela_pedida(linea):
    """La tela del producto ya está pedida (un pedido de tela anulado no cuenta)."""
    return linea.detalles_tela.exclude(pedido__estado=PedidoTela.ANULADO).exists()


def liberar_tela_anulada(pedido):
    """Al anular un pedido de tela, la tela de sus productos vuelve a quedar por pedir: la orden
    que había pasado a «Pedida» vuelve a «Por pedir» y la venta cambia de revisión."""
    lineas_ids = list(pedido.detalles.filter(linea_venta__isnull=False).values_list('linea_venta_id', flat=True))
    ordenes = OrdenPedido.objects.filter(Q(pk=pedido.orden_asociada_id) | Q(detalles__linea_venta_id__in=lineas_ids)).distinct()
    for orden in ordenes.filter(tela='Pedida'):
        lineas = list(LineaVenta.objects.filter(detalles__orden=orden).distinct())
        sigue = (estado_tela_de(lineas) == 'Pedida' if lineas
                 else orden.pedidos_telas.exclude(pk=pedido.pk).exclude(estado=PedidoTela.ANULADO).exists())
        if not sigue:
            orden.tela = 'Por pedir'
            orden.save(update_fields=['tela'])
    ventas = set(LineaVenta.objects.filter(pk__in=lineas_ids).values_list('venta_id', flat=True))
    if pedido.venta_id:
        ventas.add(pedido.venta_id)
    Venta.objects.filter(pk__in=ventas).update(revision_productos=F('revision_productos') + 1)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pedidos(request, venta_id):
    visible(request, venta_id)
    exigir(request, 'CREAR_ORDEN', 'CREAR_PROPIAS_ORDENES', 'CREAR_ORDENES_OTROS')
    if not any(tiene_permiso_codigo(request, p) for p in ('CREAR_ORDEN', 'CREAR_ORDENES_OTROS')):
        venta = visible(request, venta_id)
        if request.user.pk != venta.vendedor_id and not venta.vendedores_compartidos.filter(pk=request.user.pk).exists():
            raise PermissionDenied('Solo puedes crear pedidos para tus ventas.')
    return generar_pedidos(request, venta_id)


@idempotente('venta.productos.pedidos')
@transaction.atomic
def generar_pedidos(request, venta_id):
    s = PedidosEntrada(data=request.data)
    s.is_valid(raise_exception=True)
    datos = s.validated_data
    venta = bloquear(venta_id, datos['revision'])
    if not venta.productos_confirmados:
        raise ErrorNegocio('Guarda los productos de la venta antes de generar pedidos.', 409)
    if venta.ordenes_pedido.exclude(estado='anulado').filter(detalles__linea_venta__isnull=True, detalles__isnull=False, detalles__ignorar_vinculo=False).exists():
        raise ErrorNegocio('Vincula primero los pedidos anteriores a sus productos para evitar pedirlos de nuevo.', 409)
    grupos, vistos = defaultdict(list), set()
    for d in datos['lineas']:
        l = get_object_or_404(venta.lineas.select_for_update().select_related('referencia'), pk=d['linea'])
        if l.pk in vistos:
            raise ValidationError('Hay una línea repetida.')
        vistos.add(l.pk)
        if l.tipo != LineaVenta.TIPO_PRODUCTO:
            raise ValidationError(f'{l.producto_nombre} es un servicio o ajuste: no se pide al proveedor.')
        if not l.referencia_id:
            raise ValidationError(f'Asigna la referencia del proveedor a {l.producto_nombre}.')
        pedidas = l.detalles.exclude(orden__estado='anulado').aggregate(n=Sum('cantidad'))['n'] or 0
        if l.inventario_origen_id or d['cantidad'] > l.cantidad - pedidas:
            raise ErrorNegocio(f'La línea {l.pk} ya está cubierta o supera la cantidad pendiente.', 409)
        grupos[l.referencia.proveedor_id].append((l, d))
    por_proveedor = {o['proveedor']: o for o in datos['ordenes']}
    resultado, detalle = [], []
    for proveedor, lineas in grupos.items():
        extra = por_proveedor.get(proveedor, {})
        orden = OrdenPedido.objects.create(proveedor_id=proveedor, usuario=request.user, venta=venta,
                                          fecha_esperada=extra.get('fecha_esperada') or datos['fecha_esperada'],
                                          observacion=extra.get('observacion', '').strip() or None,
                                          tela=extra.get('tela') or estado_tela_de([l for l, _ in lineas]),
                                          es_feria_hogar=venta.es_feria_hogar)
        for l, d in lineas:
            texto = d.get('texto_proveedor', l.texto_proveedor) or ('-' if l.sin_texto_proveedor else l.especificaciones or l.producto_nombre)
            DetallePedido.objects.create(orden=orden, referencia=l.referencia, linea_venta=l, cantidad=d['cantidad'], especificaciones=texto,
                                         subcategoria=l.variante.subcategoria if l.variante_id else None)
        resultado.append(orden.pk)
        detalle.append({'id': orden.pk, 'proveedor': proveedor, 'tela': orden.tela, 'fecha_esperada': str(orden.fecha_esperada)})
        auditar(request.user, 'venta.pedido_generado', orden, {'venta': venta.pk, 'lineas': [l.pk for l, _ in lineas]})
    venta.revision_productos += 1
    venta.save(update_fields=['revision_productos'])
    return Response({'ordenes': resultado, 'detalle': detalle, 'revision': venta.revision_productos}, status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def catalogo_productos(request):
    exigir(request, 'VER_VENTAS')
    exigir(request, 'VER_PRECIOS_VENTA')
    if request.query_params.get('solo_grupos'):
        # Grupos de tela y cuero con su costo por metro/decímetro (sección Tela del producto).
        return Response({'grupos': grupos_tela()})
    qs = VarianteProducto.objects.select_related('linea__referencia__proveedor', 'categoria', 'categoria_referencia', 'subcategoria__categoria').prefetch_related('cargos__especial', 'precios', *PREFETCH_JUEGOS)
    q = request.query_params.get('q', '').strip()[:150]
    pag = serializers.IntegerField(min_value=1).run_validation(request.query_params.get('page', 1))
    if not request.query_params.get('id'):
        # Búsqueda del vendedor (2026-10-24): la misma respuesta para todos, guardada en la caché
        # del catálogo, que se descarta en cuanto cambia la lista de precios, una referencia,
        # un proveedor o una categoría. Sin caché eran ~40 consultas a la base remota (3-4 s).
        clave = hashlib.sha1(' '.join(q.lower().split()).encode()).hexdigest()
        return Response(cache_catalogo.obtener(f'pv-busqueda:{clave}:{pag}', lambda: buscar_catalogo(request, qs, q, pag)))
    return Response(buscar_catalogo(request, qs, q, pag))


def grupos_tela():
    return list(GrupoTela.objects.order_by('orden').values('id', 'nombre', 'tipo', 'precio_por_metro'))


def buscar_catalogo(request, qs, q, pag):
    from listaprecios.disposicion import excluir_retiradas
    from listaprecios.referencias import productos_actuales, ordenar_productos_actuales, categoria_variante, nombre_linea
    qs = excluir_retiradas(qs)
    grupos = grupos_tela()
    general = obtener_multiplicador_general()  # una vez, no una consulta por producto y pieza
    if request.query_params.get('id'):
        # Lectura puntual para editar documentos anteriores: nunca se ofrece en búsquedas nuevas.
        qs = qs.filter(pk=serializers.IntegerField(min_value=1).run_validation(request.query_params['id']))
        actuales = set(productos_actuales(qs).values_list('pk', flat=True))
    else:
        qs = productos_actuales(qs)
        actuales = None
    qs = ordenar_productos_actuales(qs)
    if q:
        qs = qs.filter(Q(subcategoria__nombre__icontains=q) | Q(subcategoria__categoria__nombre__icontains=q) | Q(linea__referencia__nombre__icontains=q) | Q(linea__referencia__proveedor__nombre_empresa__icontains=q))
    resultados = []
    for v in qs[(pag - 1) * 40:pag * 40]:
        juego = resumen_componentes(v)  # «1 Mesa de 6 + 6 Silla de comedor»
        metraje = metraje_total(v)
        # Un conjunto siempre se agrega por piezas: cada una con su precio dentro del conjunto, su
        # referencia y su pedido al proveedor; sus costos propios (Transporte…) van en otra línea.
        piezas = [{'pieza': c.pk, 'variante': c.variante_id, 'nombre': c.variante.nombre_catalogo, 'cantidad': c.cantidad,
                   'subcategoria': c.variante.subcategoria_id, 'referencia': c.variante.linea.referencia_id,
                   'referencia_nombre': nombre_linea(c.variante.linea),
                   'tela': usa_tela(c.variante), 'grupos': [g['id'] for g in grupos if grupo_aplicable(c.variante, GrupoTela(**g))] if usa_tela(c.variante) else [],
                   'proveedor_nombre': c.variante.linea.referencia.proveedor.nombre_empresa if c.variante.linea.referencia_id else ''}
                  for c in componentes_de(v)] if juego else []
        costos = costos_propios(v, multiplicador_general=general) if piezas else Decimal(0)
        nombre_costos, solo_transporte = nombre_costos_propios(v) if piezas else ('', True)
        categoria = categoria_variante(v)
        actual = actuales is None or v.pk in actuales
        estado = 'historico' if not actual else 'borrador' if not v.publicado else 'sin_costo' if not v.costo_confirmado else 'publicado'
        referencia = v.linea.referencia
        referencias_piezas = [c.variante.linea.referencia for c in componentes_de(v)] if juego else [referencia]
        proveedores = {r.proveedor_id: r.proveedor.nombre_empresa for r in referencias_piezas if r}
        proveedor_nombre = ' · '.join(proveedores.values())
        resultados.append({'id': v.pk, 'nombre': f'{nombre_linea(v.linea)} · {v.nombre_catalogo}', 'categoria': categoria.nombre if categoria else '',
                           'subcategoria': v.subcategoria_id, 'subcategoria_nombre': v.nombre_catalogo,
                           'referencia': v.linea.referencia_id, 'referencia_nombre': nombre_linea(v.linea),
                           'proveedor': next(iter(proveedores)) if len(proveedores) == 1 else None,
                           'proveedor_nombre': proveedor_nombre,
                           'catalogo_actual': actual, 'seleccionable': estado == 'publicado', 'estado_precio': estado,
                           'activo': v.publicado, 'tela': usa_tela(v),
                           'metraje': str(metraje) if metraje else None, 'decimetraje_cuero': str(metraje_total(v, 'cuero') or '') or None, 'juego': juego, 'piezas': piezas,
                           'costos_conjunto': str(dinero(costos)) if costos else None, 'costos_conjunto_nombre': nombre_costos,
                           'costos_conjunto_tipo': LineaVenta.TIPO_TRANSPORTE if solo_transporte and costos > 0 else LineaVenta.TIPO_AJUSTE,
                           'decorativos_incluidos': 2 if da_decorativos(v, []) else 0, 'es_decorativo': es_decorativo(v),
                           'grupos': [g['id'] for g in grupos if grupo_aplicable(v, GrupoTela(**g))] if usa_tela(v) else [],
                           'opcionales': [{'id': c.pk, 'descripcion': c.descripcion, 'especial': c.especial_id is not None, 'preseleccionado': c.preseleccionado,
                                           'decorativos': c.tipo == 'decorativos'}
                                          for c in v.cargos.all() if c.opcional]
                                         + [{'id': c.pk, 'descripcion': f'{c.descripcion} · {comp.variante.nombre_catalogo}', 'especial': c.especial_id is not None,
                                             'preseleccionado': c.preseleccionado} for comp, c in opcionales_piezas(v)],
                           'referencias': [{'id': r.pk, 'nombre': f'{r.nombre} · {v.nombre_catalogo} · {proveedor_nombre}' if actual else f'{r.nombre} · {r.proveedor.nombre_empresa}'}
                                           for r in referencias_sugeridas(v)][:5] if request.query_params.get('id') else []})
    return {'results': resultados, 'count': qs.count(), 'page': pag, 'grupos': grupos}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def referencias_productos(request):
    exigir(request, 'VER_VENTAS')
    q = request.query_params.get('q', '').strip()[:150]
    qs = Referencia.objects.select_related('proveedor').filter(Q(nombre__icontains=q) | Q(proveedor__nombre_empresa__icontains=q)).order_by('id')
    pag = serializers.IntegerField(min_value=1).run_validation(request.query_params.get('page', 1))
    return Response({'results': [{'id': r.pk, 'nombre': f'{r.nombre} · {r.proveedor.nombre_empresa}'} for r in qs[(pag - 1)*40:pag*40]], 'count': qs.count()})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def precio_producto(request, venta_id):
    venta = visible(request, venta_id)
    exigir(request, 'VER_PRECIOS_VENTA')
    exigir(request, 'EDITAR_PRODUCTOS_VENTA', 'EDITAR_VENTA')
    s = LineaEntrada(data=request.data)
    s.is_valid(raise_exception=True)
    anterior = get_object_or_404(venta.lineas, pk=s.validated_data['id']) if s.validated_data.get('id') else None
    c = preparar_linea(request, venta, s.validated_data, anterior, completo=False)
    publico = {k: str(c[k]) for k in ('precio_lista_unitario', 'precio_unitario', 'descuento', 'subtotal')}
    if anterior is not None and not s.validated_data['recalcular'] and s.validated_data['variante']:
        # La línea guardada conserva su precio; si la lista cambió, se informa el actual
        # para ofrecer «Actualizar precio» (nunca se aplica solo).
        try:
            vigente = preparar_linea(request, venta, {**s.validated_data, 'recalcular': True}, anterior, completo=False)
        except (ValidationError, PermissionDenied):
            pass  # ya no está en la lista o no se puede recalcular: se queda como se vendió
        else:
            if vigente['precio_lista_unitario'] != c['precio_lista_unitario']:
                publico['precio_lista_vigente'] = str(vigente['precio_lista_unitario'])
    if tiene_permiso_codigo(request, 'VER_MARGENES'):
        publico['costo_estimado'] = str(c['costo_estimado']) if c['costo_estimado'] is not None else None
    return Response(publico)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def preparar_recepcion(request, pedido_id):
    from .permissions import ordenes_visibles
    exigir(request, 'CREAR_FACTURA')
    orden = get_object_or_404(ordenes_visibles(request, OrdenPedido.objects.select_related('proveedor')), pk=pedido_id)
    if orden.estado == 'anulado':
        raise ErrorNegocio('El pedido está anulado.', 409)
    filas = _filas_pendientes(OrdenPedido.objects.filter(pk=orden.pk))
    return Response({'pedido': orden.pk, 'proveedor': orden.proveedor_id, 'proveedor_nombre': orden.proveedor.nombre_empresa, 'productos': filas})


class VinculoEntrada(serializers.Serializer):
    detalle = serializers.IntegerField(min_value=1)
    # Sin línea: "no es de un producto de esta venta" (deja de ofrecerse y de bloquear).
    linea = serializers.IntegerField(min_value=1, allow_null=True, default=None)


class VinculosEntrada(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0)
    vinculos = VinculoEntrada(many=True, allow_empty=False)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def vincular_pedidos(request, venta_id):
    visible(request, venta_id)
    exigir(request, 'EDITAR_PRODUCTOS_VENTA', 'EDITAR_VENTA')
    return guardar_vinculos(request, venta_id)


@idempotente('venta.productos.vincular')
@transaction.atomic
def guardar_vinculos(request, venta_id):
    s = VinculosEntrada(data=request.data)
    s.is_valid(raise_exception=True)
    venta = bloquear(venta_id, s.validated_data['revision'])
    for d in s.validated_data['vinculos']:
        detalle = get_object_or_404(DetallePedido.objects.select_for_update(), pk=d['detalle'], orden__venta=venta)
        if detalle.linea_venta_id or detalle.orden.estado == 'anulado':
            raise ErrorNegocio('El pedido ya está vinculado o está anulado.', 409)
        if d['linea'] is None:
            detalle.ignorar_vinculo = True
            detalle.save(update_fields=['ignorar_vinculo'])
            auditar(request.user, 'venta.pedido_no_vinculado', detalle, {'venta': venta.pk})
            continue
        linea = get_object_or_404(venta.lineas.select_for_update(), pk=d['linea'])
        # La referencia puede diferir (p. ej. un sobre pedido aparte para una mesa): el
        # vínculo solo dice que esa unidad del producto ya se pidió.
        if linea.inventario_origen_id or linea.tipo != LineaVenta.TIPO_PRODUCTO:
            raise ValidationError('Ese producto sale de bodega o es un servicio: no se le vinculan pedidos.')
        pedidas = sum(linea.detalles.exclude(orden__estado='anulado').values_list('cantidad', flat=True))
        if detalle.cantidad + pedidas > linea.cantidad:
            raise ValidationError('El pedido histórico supera la cantidad de productos de esta línea.')
        detalle.linea_venta = linea
        detalle.save(update_fields=['linea_venta'])
        auditar(request.user, 'venta.pedido_vinculado', detalle, {'venta': venta.pk, 'linea': linea.pk})
    venta.revision_productos += 1
    venta.save(update_fields=['revision_productos'])
    return Response(representar(request, venta))


# --- Facturas: productos pedidos a un proveedor con su costo sugerido (2026-10-15) ---------

def costo_sugerido(linea):
    """Costo por unidad que debería facturar el proveedor del mueble, según la lista de
    precios: el precio de lista (con recargos o precio especial) ÷ su multiplicador. Si la
    tela se compra aparte, se descuenta la tela que el catálogo incluía en el precio. Es una
    sugerencia: en la factura se revisa contra lo que cobra el proveedor."""
    if not linea or linea.tipo != LineaVenta.TIPO_PRODUCTO or not linea.precio_lista_unitario:
        return None
    try:
        mult = Decimal(str(linea.precio_snapshot.get('multiplicador') or 0)) or (
            multiplicador_efectivo(linea.variante) if linea.variante_id else obtener_multiplicador_general())
    except Exception:
        mult = None
    if not mult or mult <= 0:
        return None
    costo = linea.precio_lista_unitario / mult
    tela = Decimal(0)
    if gestion_venta.tela_modo(linea) == LineaVenta.TELA_APARTE:
        try:
            tela = Decimal(str(linea.precio_snapshot.get('metraje') or 0)) * Decimal(str(linea.precio_snapshot.get('costo_tela') or 0))
        except Exception:
            tela = Decimal(0)
    valor = (costo - tela).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return {'valor': str(max(valor, Decimal(0))), 'lista': str(linea.precio_lista_unitario), 'multiplicador': str(mult.normalize()),
            'tela_descontada': str(tela.quantize(Decimal('1'))) if tela else None}


def fila_factura(det, orden, recibidas, sugerencias=None):
    """Una línea de pedido pendiente de recibir, lista para la factura."""
    l = det.linea_venta if det.linea_venta_id else None
    nombre = (det.referencia.nombre.strip().lower() if det.referencia else '')
    categoria, subcategoria = (sugerencias or {}).get(nombre, (None, None))
    telas = []
    if l and gestion_venta.tela_modo(l) in (LineaVenta.TELA_INCLUIDA, LineaVenta.TELA_APARTE) and (l.tela_referencia or l.tela_color):
        por_unidad = (l.tela_cantidad / l.cantidad).quantize(CENT) if l.tela_cantidad and l.cantidad else None
        telas.append({'tipo': l.tela_material or 'tela', 'referencia': l.tela_referencia, 'color': l.tela_color,
                      'cantidad': str(por_unidad) if por_unidad else '', 'costo_unidad': str(l.tela_costo) if l.tela_costo is not None else '',
                      'grupo': l.tela_grupo.nombre if l.tela_grupo_id else ''})
    return {'detalle_pedido': det.pk, 'pedido': orden.pk, 'venta': orden.venta_id, 'referencia': det.referencia_id,
            'referencia_nombre': det.referencia.nombre if det.referencia else '',
            'cantidad': max(det.cantidad - recibidas, 0), 'recibidas': recibidas, 'pedidas': det.cantidad,
            'descripcion': det.especificaciones or '',
            'producto': (f'{l.producto_nombre} · {l.variante_nombre}' if l.variante_nombre else l.producto_nombre) if l else '',
            'detalle': l.variante_nombre if l else '', 'conjunto': l.conjunto_nombre if l else '',
            'categoria': categoria, 'subcategoria': subcategoria,
            'costo_sugerido': costo_sugerido(l), 'telas': telas, 'fecha_pedido': str(orden.fecha_creacion)}


def _filas_pendientes(ordenes):
    from suministros.views import sugerencias_por_referencia
    ordenes = list(ordenes.prefetch_related(
        Prefetch('detalles', queryset=DetallePedido.objects.select_related('referencia', 'linea_venta__variante__multiplicador', 'linea_venta__tela_grupo')
                 .prefetch_related('unidades_recibidas', 'linea_venta__detalles_tela'))))
    sugerencias = sugerencias_por_referencia({d.referencia.nombre for o in ordenes for d in o.detalles.all() if d.referencia})
    filas = []
    for orden in ordenes:
        for d in orden.detalles.all():
            recibidas = sum(1 for u in d.unidades_recibidas.all() if u.disponibilidad != 'devuelto_proveedor')
            if d.cantidad - recibidas > 0:
                filas.append(fila_factura(d, orden, recibidas, sugerencias))
    return filas


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pendientes_factura(request, proveedor_id):
    """Lo pedido a este proveedor que aún no llega: para agregarlo rápido a su factura."""
    from .permissions import ordenes_visibles
    exigir(request, 'CREAR_FACTURA')
    qs = ordenes_visibles(request, OrdenPedido.objects.filter(proveedor_id=proveedor_id).exclude(estado__in=['anulado', 'recibido'])).order_by('-id')[:200]
    return Response({'productos': _filas_pendientes(OrdenPedido.objects.filter(pk__in=[o.pk for o in qs]).order_by('-id'))})
