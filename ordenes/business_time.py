"""Tiempo de negocio (P05-05, H31): una sola definición de "hoy", del día local
y del período comercial (del 6 de un mes al 5 del siguiente, ambos incluidos).

Los instantes se guardan en UTC (USE_TZ=True); las fechas de negocio se
calculan siempre en la zona del proyecto (America/Bogota), nunca con
date.today() (zona del servidor) ni con timezone.now().date() (UTC).
"""
from datetime import date, datetime, time, timedelta

from django.utils import timezone

DIA_INICIO_PERIODO = 6


def hoy():
    return timezone.localdate()


def fecha_local(instante):
    return timezone.localtime(instante).date()


def rango_dia_local(dia):
    """[inicio, fin) del día local como instantes conscientes de zona: el inicio
    se incluye y el inicio del día siguiente se excluye (sin doble conteo)."""
    tz = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime.combine(dia, time.min), tz)
    fin = timezone.make_aware(datetime.combine(dia + timedelta(days=1), time.min), tz)
    return inicio, fin


def periodo_de_mes(mes, anio):
    """Período comercial que empieza el día 6 del mes indicado: (inicio, fin) con
    ambas fechas incluidas."""
    inicio = date(anio, mes, DIA_INICIO_PERIODO)
    sig_mes, sig_anio = (1, anio + 1) if mes == 12 else (mes + 1, anio)
    fin = date(sig_anio, sig_mes, DIA_INICIO_PERIODO) - timedelta(days=1)
    return inicio, fin


def periodo_comercial(dia=None):
    """Período comercial que contiene la fecha dada (por defecto, hoy local)."""
    dia = dia or hoy()
    if dia.day >= DIA_INICIO_PERIODO:
        return periodo_de_mes(dia.month, dia.year)
    mes, anio = (12, dia.year - 1) if dia.month == 1 else (dia.month - 1, dia.year)
    return periodo_de_mes(mes, anio)
