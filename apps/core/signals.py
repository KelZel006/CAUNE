from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from . import auditoria


@receiver(user_logged_in)
def auditar_ingreso(sender, request, user, **kwargs):
    auditoria.registrar(auditoria.Accion.INGRESO, usuario=user, entidad="auth.User", entidad_id=user.pk)


@receiver(user_logged_out)
def auditar_salida(sender, request, user, **kwargs):
    if user is not None:
        auditoria.registrar(auditoria.Accion.SALIDA, usuario=user, entidad="auth.User", entidad_id=user.pk)


@receiver(user_login_failed)
def auditar_ingreso_fallido(sender, credentials, request=None, **kwargs):
    usuario = str(credentials.get("username", ""))[:150]
    auditoria.registrar(auditoria.Accion.INGRESO_FALLIDO, entidad="auth.User",
                        descripcion=f"Intento fallido con el usuario «{usuario}»")
