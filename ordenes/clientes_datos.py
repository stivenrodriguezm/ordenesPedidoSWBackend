"""Filtros compartidos por directorio y exportación de clientes."""
from django.db.models import Q
from rest_framework import serializers
from .models import Cliente


class FiltrosClientes(serializers.Serializer):
    tipo_persona = serializers.ChoiceField(choices=Cliente.TIPO_PERSONA_CHOICES, required=False, allow_blank=True)
    query = serializers.CharField(max_length=255, required=False, allow_blank=True)
    search = serializers.CharField(max_length=255, required=False, allow_blank=True)
    cedula = serializers.CharField(max_length=20, required=False, allow_blank=True)


def filtrar_clientes(qs, parametros):
    entrada = FiltrosClientes(data=parametros)
    entrada.is_valid(raise_exception=True)
    filtros = entrada.validated_data
    for campo in ('query', 'search'):
        valor = filtros.get(campo)
        if valor:
            consulta = Q(nombre__icontains=valor) | Q(cedula__icontains=valor)
            # No convertir búsquedas de centenares de dígitos a un BIGINT SQL.
            if valor.isascii() and valor.isdigit() and len(valor) <= 19 and int(valor) <= 9223372036854775807:
                consulta |= Q(id=int(valor))
            qs = qs.filter(consulta)
    if filtros.get('cedula'):
        qs = qs.filter(cedula=filtros['cedula'])
    if filtros.get('tipo_persona'):
        qs = qs.filter(tipo_persona=filtros['tipo_persona'])
    return qs.order_by('-id'), filtros
