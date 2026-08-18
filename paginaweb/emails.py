"""
Correos transaccionales del sistema de PQRS de "Contacto":
- Confirmación al cliente cuando envía un PQRS.
- Notificación interna al equipo LOTTUS.
- Aviso al cliente cuando un admin responde desde Gestión Web.

Sin credenciales SMTP configuradas (ver settings.EMAIL_BACKEND), los correos
se imprimen en el log del servidor en vez de enviarse de verdad — así el
flujo completo se puede probar en local sin depender de un proveedor real.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape, strip_tags

logger = logging.getLogger(__name__)

_GOLD = "#c9a227"
_INK = "#0a0a0a"


def _shell(preheader, title, body_html):
    return f"""\
<div style="background:#f4f4f2;padding:32px 16px;font-family:Georgia,'Times New Roman',serif;color:{_INK}">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 12px 30px -12px rgba(0,0,0,0.18)">
    <div style="background:{_INK};padding:26px 32px">
      <span style="font-family:Arial,Helvetica,sans-serif;font-weight:700;letter-spacing:0.12em;color:#ffffff;font-size:1.05rem">LOTTUS</span>
      <div style="height:2px;width:36px;background:{_GOLD};margin-top:8px"></div>
    </div>
    <div style="padding:32px">
      <h1 style="font-size:1.25rem;margin:0 0 18px;font-weight:600">{escape(title)}</h1>
      {body_html}
    </div>
    <div style="padding:18px 32px;background:#faf9f7;color:#6b6b6b;font-family:Arial,Helvetica,sans-serif;font-size:0.75rem">
      LOTTUS · Bogotá D.C. · {escape(preheader)}
    </div>
  </div>
</div>
"""


def _send(subject, to_email, html_body, reply_to=None):
    if not to_email:
        return False
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=strip_tags(html_body),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
            reply_to=[reply_to] if reply_to else None,
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("Error enviando correo PQRS a %s", to_email)
        return False


def send_confirmation_email(ticket):
    """Correo de confirmación al cliente justo al crear el ticket."""
    body = f"""
      <p>Hola {escape(ticket.nombre)},</p>
      <p>Recibimos tu <strong>{escape(ticket.get_tipo_display())}</strong> y ya está registrada en nuestro sistema.
      Nuestro equipo la revisará y te responderemos a este mismo correo en un plazo máximo de
      <strong>2 días hábiles</strong>.</p>
      <table style="width:100%;border-collapse:collapse;margin:20px 0;font-family:Arial,Helvetica,sans-serif;font-size:0.85rem">
        <tr><td style="padding:6px 0;color:#6b6b6b;width:120px">Radicado</td><td style="padding:6px 0;font-weight:700">{escape(ticket.radicado)}</td></tr>
        <tr><td style="padding:6px 0;color:#6b6b6b">Tipo</td><td style="padding:6px 0">{escape(ticket.get_tipo_display())}</td></tr>
        {f'<tr><td style="padding:6px 0;color:#6b6b6b">Asunto</td><td style="padding:6px 0">{escape(ticket.asunto)}</td></tr>' if ticket.asunto else ''}
      </table>
      <div style="background:#faf9f7;border-left:3px solid {_GOLD};padding:14px 18px;margin:0 0 20px;white-space:pre-wrap;font-family:Arial,Helvetica,sans-serif;font-size:0.88rem;color:#333">{escape(ticket.mensaje)}</div>
      <p style="font-family:Arial,Helvetica,sans-serif;font-size:0.85rem;color:#6b6b6b">Guarda tu número de radicado para futuras consultas sobre este caso.</p>
    """
    html = _shell(f"Radicado {ticket.radicado}", "Hemos recibido tu solicitud", body)
    return _send(
        subject=f"[LOTTUS] Confirmación de tu {ticket.get_tipo_display().lower()} · {ticket.radicado}",
        to_email=ticket.email,
        html_body=html,
        reply_to=settings.PQRS_NOTIFY_EMAIL,
    )


def send_internal_notification(ticket):
    """Aviso al equipo LOTTUS para que entren a Gestión Web a atenderlo."""
    body = f"""
      <p>Se registró un nuevo <strong>{escape(ticket.get_tipo_display())}</strong> desde el formulario de contacto de la web.</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;font-family:Arial,Helvetica,sans-serif;font-size:0.85rem">
        <tr><td style="padding:6px 0;color:#6b6b6b;width:120px">Radicado</td><td style="padding:6px 0;font-weight:700">{escape(ticket.radicado)}</td></tr>
        <tr><td style="padding:6px 0;color:#6b6b6b">Nombre</td><td style="padding:6px 0">{escape(ticket.nombre)}</td></tr>
        <tr><td style="padding:6px 0;color:#6b6b6b">Correo</td><td style="padding:6px 0">{escape(ticket.email)}</td></tr>
        {f'<tr><td style="padding:6px 0;color:#6b6b6b">Teléfono</td><td style="padding:6px 0">{escape(ticket.telefono)}</td></tr>' if ticket.telefono else ''}
        {f'<tr><td style="padding:6px 0;color:#6b6b6b">Asunto</td><td style="padding:6px 0">{escape(ticket.asunto)}</td></tr>' if ticket.asunto else ''}
      </table>
      <div style="background:#faf9f7;border-left:3px solid {_GOLD};padding:14px 18px;margin:0 0 20px;white-space:pre-wrap;font-family:Arial,Helvetica,sans-serif;font-size:0.88rem;color:#333">{escape(ticket.mensaje)}</div>
      <p style="font-family:Arial,Helvetica,sans-serif;font-size:0.85rem;color:#6b6b6b">Ingresa a Gestión Web → PQRS en la plataforma para responder.</p>
    """
    html = _shell(f"Radicado {ticket.radicado}", "Nuevo PQRS recibido", body)
    return _send(
        subject=f"Nuevo PQRS · {ticket.radicado} · {ticket.nombre}",
        to_email=settings.PQRS_NOTIFY_EMAIL,
        html_body=html,
        reply_to=ticket.email,
    )


def send_response_email(ticket, mensaje):
    """Correo al cliente cuando un admin responde su PQRS desde Gestión Web."""
    body = f"""
      <p>Hola {escape(ticket.nombre)},</p>
      <p>Tenemos una respuesta para tu {escape(ticket.get_tipo_display().lower())} con radicado <strong>{escape(ticket.radicado)}</strong>:</p>
      <div style="background:#faf9f7;border-left:3px solid {_GOLD};padding:14px 18px;margin:0 0 20px;white-space:pre-wrap;font-family:Arial,Helvetica,sans-serif;font-size:0.88rem;color:#333">{escape(mensaje)}</div>
      <p style="font-family:Arial,Helvetica,sans-serif;font-size:0.82rem;color:#6b6b6b">Tu mensaje original:</p>
      <div style="border-left:3px solid #ddd;padding:10px 18px;margin:0 0 20px;white-space:pre-wrap;font-family:Arial,Helvetica,sans-serif;font-size:0.82rem;color:#888">{escape(ticket.mensaje)}</div>
      <p style="font-family:Arial,Helvetica,sans-serif;font-size:0.85rem;color:#6b6b6b">Si necesitas agregar algo más, simplemente responde a este correo.</p>
    """
    html = _shell(f"Radicado {ticket.radicado}", "Respuesta a tu PQRS", body)
    return _send(
        subject=f"[LOTTUS] Respuesta a tu PQRS · {ticket.radicado}",
        to_email=ticket.email,
        html_body=html,
        reply_to=settings.PQRS_NOTIFY_EMAIL,
    )
