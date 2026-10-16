"""Calendario explícito de la oficina. Las horas siempre se interpretan en Bogotá."""
import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo('America/Bogota')


def siguiente(autom, despues):
    if not autom.activa or autom.archivada:
        return None
    local = despues.astimezone(BOGOTA)
    limite = autom.fecha_fin
    if autom.frecuencia == 'una_vez':
        fecha = autom.fecha_unica
        return fecha if fecha and fecha > despues and (not limite or fecha.astimezone(BOGOTA).date() <= limite) else None
    if autom.frecuencia in ('diaria', 'semanal'):
        for offset in range(8):
            dia = local.date() + timedelta(days=offset)
            if limite and dia > limite:
                return None
            if autom.frecuencia == 'semanal' and dia.weekday() not in autom.dias_semana:
                continue
            fecha = datetime.combine(dia, autom.hora, tzinfo=BOGOTA)
            if fecha > despues:
                return fecha
    if autom.frecuencia == 'mensual':
        for offset in range(2):
            mes_abs = local.year * 12 + local.month - 1 + offset
            ano, mes = mes_abs // 12, mes_abs % 12 + 1
            dia = min(autom.dia_mes, calendar.monthrange(ano, mes)[1])
            fecha = datetime(ano, mes, dia, autom.hora.hour, autom.hora.minute, tzinfo=BOGOTA)
            if limite and fecha.date() > limite:
                return None
            if fecha > despues:
                return fecha
    return None
