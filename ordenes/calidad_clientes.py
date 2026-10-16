"""Calidad de maestros: sugerencias explicables, nunca identidad inferida.

Los valores originales solo se guardan en CorreccionCliente, con el mismo
control de acceso que la ficha. La bitácora general no copia datos personales.
"""
import hashlib
import json
import re
import unicodedata
from collections import defaultdict

from django.core import signing
from django.db import transaction
from django.shortcuts import get_object_or_404

from .models import Cliente, CorreccionCliente
from .permissions import clientes_visibles, ventas_visibles
from .serializers import ClienteSerializer
from .servicios import ErrorNegocio, auditar

CAMPOS = ('nombre', 'cedula', 'correo', 'telefono1', 'telefono2', 'direccion', 'barrio', 'ciudad')
EDITABLES = ('nombre', 'correo', 'telefono1', 'telefono2', 'direccion', 'barrio', 'ciudad')
LIMITE_CLIENTES = 5000
LIMITE_GRUPO = 50
SALT = 'calidad-cliente-v1'


def datos_cliente(cliente):
    return {'id': cliente.pk, **{campo: getattr(cliente, campo) for campo in CAMPOS}}


def huella(cliente):
    return hashlib.sha256(json.dumps(datos_cliente(cliente), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def espacios(texto):
    return ' '.join((texto or '').split())


def telefono(texto):
    limpio = espacios(texto)
    # No adivinar país, extensión ni dígitos faltantes. Texto con extensión o
    # símbolos desconocidos solo recibe limpieza de espacios.
    if re.fullmatch(r'\+?[0-9() .-]+', limpio):
        digitos = re.sub(r'[^0-9]', '', limpio)
        if 7 <= len(digitos) <= 15:
            return ('+' if limpio.startswith('+') else '') + digitos
    return limpio


def clave_texto(texto):
    return ''.join(c for c in unicodedata.normalize('NFKD', espacios(texto).casefold()) if not unicodedata.combining(c))


def clave_documento(texto):
    # Solo para sugerir coincidencias; jamás cambia cédula/NIT ni quita ceros.
    return re.sub(r'[ .-]', '', espacios(texto)).casefold()


def clave_contacto(texto):
    normal = telefono(texto)
    digitos = normal.lstrip('+')
    if digitos.isdigit() and len(digitos) >= 7 and len(set(digitos)) > 2:
        return normal
    return ''


def propuestas(cliente):
    cambios = {}
    for campo in EDITABLES:
        original = getattr(cliente, campo)
        if not original:
            continue
        nuevo = telefono(original) if campo.startswith('telefono') else espacios(original)
        # No modificar contenido de correo (incluido el case del local-part).
        if campo == 'correo':
            nuevo = original.strip()
        if nuevo != original:
            entrada = ClienteSerializer(cliente, data={campo: nuevo}, partial=True)
            if entrada.is_valid():
                cambios[campo] = {'antes': original, 'despues': nuevo}
    return cambios


def vista_cliente(cliente):
    return {
        'cliente': datos_cliente(cliente), 'cambios': propuestas(cliente),
        'version': signing.dumps({'cliente': cliente.pk, 'huella': huella(cliente)}, salt=SALT),
    }


def buscar_candidatos(request, buscar=''):
    # La búsqueda elige qué clientes mostrar, pero las coincidencias se buscan
    # en TODO el ámbito visible, no solo entre los resultados de esa búsqueda.
    qs = clientes_visibles(request)
    clientes = list(qs[:LIMITE_CLIENTES + 1])
    if len(clientes) > LIMITE_CLIENTES:
        raise ErrorNegocio('La revisión supera 5000 clientes. Se necesita una revisión por lotes antes de continuar; no se entrega un resultado incompleto.', 413)
    seleccionados = {c.pk for c in clientes if not buscar or clave_texto(buscar) in clave_texto(
        ' '.join(str(v or '') for v in datos_cliente(c).values())
    )}
    grupos = defaultdict(dict)
    for c in clientes:
        nombre = clave_texto(c.nombre)
        documento = clave_documento(c.cedula)
        correo = (c.correo or '').strip().casefold()
        if len(documento) >= 5 and len(set(documento)) > 1:
            grupos[('documento', documento)][c.pk] = c
        if len(nombre) >= 5:
            for contacto in {clave_contacto(c.telefono1), clave_contacto(c.telefono2)} - {''}:
                grupos[('nombre_telefono', nombre, contacto)][c.pk] = c
            if '@' in correo and not any(ch.isspace() for ch in correo):
                grupos[('nombre_correo', nombre, correo)][c.pk] = c
    razones = {
        'documento': 'Documento coincidente al comparar espacios, puntos y guiones; conserva letras y ceros iniciales.',
        'nombre_telefono': 'Nombre y teléfono coincidentes al comparar espacios, mayúsculas, tildes y separadores del teléfono.',
        'nombre_correo': 'Nombre y correo coincidentes al comparar espacios y mayúsculas; se ignoran tildes solo en el nombre.',
    }
    # Un mismo conjunto puede coincidir por dos criterios: se muestra una vez.
    conjuntos = {}
    for clave, miembros in grupos.items():
        ids = tuple(sorted(miembros))
        if len(ids) < 2 or not seleccionados.intersection(ids):
            continue
        if len(ids) > LIMITE_GRUPO:
            raise ErrorNegocio('Hay una coincidencia demasiado amplia para revisar de forma segura. Revisa los identificadores genéricos antes de continuar.', 413)
        grupo = conjuntos.setdefault(ids, {'id': '-'.join(map(str, ids)), 'razones': [],
            'clientes': [datos_cliente(miembros[i]) for i in ids]})
        razon = razones[clave[0]]
        if razon not in grupo['razones']:
            grupo['razones'].append(razon)
    return list(conjuntos.values()), len(clientes)


@transaction.atomic
def corregir(request, cliente_id, version, campos):
    # Bloqueo simple, sin joins: compatible con MySQL. El alcance se revalida
    # antes de obtener el cliente y nunca se confía en los IDs del navegador.
    get_object_or_404(clientes_visibles(request), pk=cliente_id)
    cliente = Cliente.objects.select_for_update().get(pk=cliente_id)
    try:
        previa = signing.loads(version, salt=SALT, max_age=1800)
    except signing.BadSignature:
        raise ErrorNegocio('La vista previa expiró o no es válida. Vuelve a consultar el cliente.', 409)
    if previa.get('cliente') != cliente.pk or previa.get('huella') != huella(cliente):
        raise ErrorNegocio('El cliente cambió después de la vista previa. Revísalo antes de guardar.', 409)
    cambios = propuestas(cliente)
    if not campos or len(campos) != len(set(campos)) or any(c not in cambios for c in campos):
        raise ErrorNegocio('Selecciona únicamente correcciones ofrecidas en la vista previa.', campo='campos')
    elegidos = {c: cambios[c] for c in campos}
    serializer = ClienteSerializer(cliente, data={c: v['despues'] for c, v in elegidos.items()}, partial=True)
    serializer.is_valid(raise_exception=True)
    for campo, valor in serializer.validated_data.items():
        setattr(cliente, campo, valor)
    cliente.save(update_fields=list(serializer.validated_data))
    revision = CorreccionCliente.objects.create(cliente=cliente, usuario=request.user, cambios=elegidos)
    auditar(request.user, 'cliente.normalizar', cliente, {'revision': revision.pk, 'campos': sorted(campos)})
    return {'revision': revision.pk, **vista_cliente(cliente)}


def comparar(request, origen, destino):
    """Vista previa de identidad y documentos. No fusiona ni cambia FKs."""
    if origen == destino:
        raise ErrorNegocio('Selecciona dos clientes distintos.')
    a = get_object_or_404(clientes_visibles(request), pk=origen)
    b = get_object_or_404(clientes_visibles(request), pk=destino)
    ventas = ventas_visibles(request)
    conflictos = [campo for campo in CAMPOS if getattr(a, campo) and getattr(b, campo)
                  and getattr(a, campo) != getattr(b, campo)]
    return {
        'origen': datos_cliente(a), 'destino': datos_cliente(b), 'conflictos': conflictos,
        'ventas_visibles': {'origen': ventas.filter(cliente=a).count(), 'destino': ventas.filter(cliente=b).count()},
        'puede_fusionar': False,
        'advertencia': 'Una coincidencia no demuestra que sea la misma persona. La fusión no está habilitada: primero hay que resolver identidades y preservar los datos históricos de los documentos.',
    }
