"""Parámetros configurables. Toda regla pendiente de aprobación por CAUNE vive aquí,
no escrita a fuego en el código."""
from django.core.exceptions import ValidationError
from django.db import transaction

from . import auditoria
from .models import HistorialParametro, Parametro

T = Parametro.Tipo
G = Parametro.Grupo

DEFINICIONES = {
    "coop.nombre": dict(nombre="Nombre de la cooperativa", tipo=T.TEXTO, grupo=G.GENERAL,
                        valor="Caja de Ahorro Unión y Esfuerzo"),
    "coop.siglas": dict(nombre="Siglas", tipo=T.TEXTO, grupo=G.GENERAL, valor="CAUNE"),
    "coop.fundacion": dict(nombre="Año de fundación", tipo=T.TEXTO, grupo=G.GENERAL, valor="2022"),
    "coop.rtn": dict(nombre="RTN", tipo=T.TEXTO, grupo=G.GENERAL, valor=""),
    "coop.direccion": dict(nombre="Dirección", tipo=T.TEXTO, grupo=G.GENERAL, valor=""),
    "coop.telefono": dict(nombre="Teléfono", tipo=T.TEXTO, grupo=G.GENERAL, valor=""),
    "coop.correo": dict(nombre="Correo electrónico", tipo=T.TEXTO, grupo=G.GENERAL, valor=""),
    "afiliados.permitir_movimientos_inactivos": dict(
        nombre="Permitir movimientos a afiliados inactivos", tipo=T.BOOLEANO, grupo=G.OPERACION,
        valor="false", afecta_calculos=True,
        descripcion="Si está desactivado, no se pueden registrar aportaciones, depósitos ni retiros "
                    "a afiliados inactivos.",
    ),
    "movimientos.permitir_retiro_aportaciones": dict(
        nombre="Permitir tipos de retiro de aportaciones", tipo=T.BOOLEANO, grupo=G.OPERACION,
        valor="false", afecta_calculos=True,
        descripcion="Decisión A2: por defecto las aportaciones son capital no retirable. "
                    "Solo los depósitos reembolsables admiten retiros.",
    ),
    "movimientos.anulacion_requiere_otro_usuario": dict(
        nombre="La anulación debe hacerla un usuario distinto al que registró", tipo=T.BOOLEANO,
        grupo=G.OPERACION, valor="true", afecta_calculos=True,
        descripcion="Decisión G1: control de doble persona para corregir operaciones.",
    ),
    "prestamos.tasa_interna": dict(
        nombre="Tasa de préstamos internos (% mensual)", tipo=T.DECIMAL, grupo=G.PRESTAMOS, valor="1.00",
        afecta_calculos=True,
        descripcion="Se copia a cada préstamo al aprobarlo; un cambio no afecta préstamos existentes.",
    ),
    "prestamos.tasa_externa": dict(
        nombre="Tasa de préstamos externos (% mensual)", tipo=T.DECIMAL, grupo=G.PRESTAMOS, valor="5.00",
        afecta_calculos=True,
        descripcion="Se copia a cada préstamo al aprobarlo; un cambio no afecta préstamos existentes.",
    ),
    "prestamos.periodicidad_tasa": dict(
        nombre="Periodicidad de las tasas", tipo=T.TEXTO, grupo=G.PRESTAMOS, valor="MENSUAL", afecta_calculos=True,
        descripcion="Decisión P1: MENSUAL. Es la única modalidad que el sistema calcula hoy.",
    ),
    "prestamos.metodos_permitidos": dict(
        nombre="Métodos de amortización permitidos", tipo=T.TEXTO, grupo=G.PRESTAMOS,
        valor="CUOTA_FIJA,CAPITAL_FIJO", afecta_calculos=True,
        descripcion="Separados por coma: CUOTA_FIJA (sistema francés) y/o CAPITAL_FIJO (saldo decreciente).",
    ),
    "prestamos.plazo_maximo": dict(
        nombre="Plazo máximo (cuotas mensuales)", tipo=T.ENTERO, grupo=G.PRESTAMOS, valor="60", afecta_calculos=True,
    ),
    "prestamos.permitir_pagos_parciales": dict(
        nombre="Permitir pagos parciales de cuotas", tipo=T.BOOLEANO, grupo=G.PRESTAMOS, valor="true",
        afecta_calculos=True,
        descripcion="Decisión P4: se acepta cualquier monto; cubre primero el interés y luego el capital.",
    ),
    "prestamos.permitir_excepcion_tasa": dict(
        nombre="Permitir tasas de excepción autorizadas", tipo=T.BOOLEANO, grupo=G.PRESTAMOS, valor="true",
        afecta_calculos=True,
        descripcion="Si se permite, una tasa distinta a la configurada exige permiso de autorización y motivo.",
    ),
}


def _validar_metodos(valor):
    metodos = [m.strip() for m in str(valor).split(",") if m.strip()]
    if not metodos or any(m not in ("CUOTA_FIJA", "CAPITAL_FIJO") for m in metodos):
        raise ValueError("Indique CUOTA_FIJA y/o CAPITAL_FIJO separados por coma.")


def _validar_tasa(valor):
    if valor is None or not (0 <= valor <= 100):
        raise ValueError("La tasa debe estar entre 0 y 100.")


def _validar_periodicidad(valor):
    if valor != "MENSUAL":
        raise ValueError("Por ahora el sistema solo calcula tasas MENSUALES (decisión P1).")


def _validar_plazo(valor):
    if valor is None or not (1 <= valor <= 360):
        raise ValueError("El plazo máximo debe estar entre 1 y 360 cuotas.")


# Validaciones de negocio adicionales al tipo de dato
VALIDADORES = {
    "prestamos.tasa_interna": _validar_tasa,
    "prestamos.tasa_externa": _validar_tasa,
    "prestamos.periodicidad_tasa": _validar_periodicidad,
    "prestamos.metodos_permitidos": _validar_metodos,
    "prestamos.plazo_maximo": _validar_plazo,
}


def obtener(clave):
    parametro = Parametro.objects.filter(clave=clave).first()
    if parametro is not None:
        return parametro.valor_tipado()
    definicion = DEFINICIONES[clave]
    return Parametro.convertir(definicion["tipo"], definicion["valor"])


def asegurar_parametros():
    for clave, d in DEFINICIONES.items():
        Parametro.objects.get_or_create(
            clave=clave,
            defaults=dict(nombre=d["nombre"], tipo=d["tipo"], grupo=d["grupo"], valor=d["valor"],
                          descripcion=d.get("descripcion", ""), afecta_calculos=d.get("afecta_calculos", False)),
        )


@transaction.atomic
def actualizar(parametro, valor_nuevo, usuario, motivo=""):
    if not usuario.has_perm("core.change_parametro"):
        raise ValidationError("No tiene permiso para modificar la configuración.")
    parametro = Parametro.objects.select_for_update().get(pk=parametro.pk)
    try:
        tipado = Parametro.convertir(parametro.tipo, valor_nuevo)
        if parametro.clave in VALIDADORES:
            VALIDADORES[parametro.clave](tipado)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    valor_nuevo = "" if valor_nuevo is None else str(valor_nuevo).strip()
    if parametro.tipo == Parametro.Tipo.BOOLEANO:
        valor_nuevo = "true" if Parametro.convertir(parametro.tipo, valor_nuevo) else "false"
    if valor_nuevo == parametro.valor:
        return parametro, False
    if parametro.afecta_calculos and len(motivo.strip()) < 10:
        raise ValidationError("Este parámetro afecta cálculos: indique un motivo (mínimo 10 caracteres).")
    anterior = parametro.valor
    parametro.valor = valor_nuevo
    parametro.actualizado_por = usuario
    parametro.save(update_fields=["valor", "actualizado_por", "actualizado_en"])
    HistorialParametro.objects.create(parametro=parametro, valor_anterior=anterior, valor_nuevo=valor_nuevo,
                                      motivo=motivo.strip(), cambiado_por=usuario)
    auditoria.registrar(auditoria.Accion.CONFIGURAR, usuario=usuario, objeto=parametro,
                        descripcion=f"Parámetro {parametro.clave}. Motivo: {motivo.strip()}",
                        antes={"valor": anterior}, despues={"valor": valor_nuevo})
    return parametro, True
