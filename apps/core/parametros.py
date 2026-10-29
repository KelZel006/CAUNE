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
    "coop.firma_presidente": dict(nombre="Nombre del presidente (firma de estados financieros)", tipo=T.TEXTO,
                                  grupo=G.GENERAL, valor=""),
    "coop.firma_tesorero": dict(nombre="Nombre del tesorero (firma de estados financieros)", tipo=T.TEXTO,
                                grupo=G.GENERAL, valor=""),
    "coop.firma_revisor": dict(nombre="Nombre del contador o revisor (firma de estados financieros)", tipo=T.TEXTO,
                               grupo=G.GENERAL, valor=""),
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
    "afiliados.liquidacion_requiere_otro_usuario": dict(
        nombre="La liquidación de un afiliado la aprueba un usuario distinto al que la calculó", tipo=T.BOOLEANO,
        grupo=G.OPERACION, valor="true", afecta_calculos=True,
        descripcion="Control de doble persona para el retiro de afiliados (devolución de aportaciones y depósitos).",
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
    "prestamos.tasa_mora_interna": dict(
        nombre="Tasa de mora de préstamos internos (% mensual)", tipo=T.DECIMAL, grupo=G.PRESTAMOS, valor="1.00",
        afecta_calculos=True,
        descripcion="Se cobra sobre el capital de cada cuota vencida y no pagada, por día de atraso "
                    "(tasa ÷ 30 por día). Se copia a cada préstamo al aprobarlo.",
    ),
    "prestamos.tasa_mora_externa": dict(
        nombre="Tasa de mora de préstamos externos (% mensual)", tipo=T.DECIMAL, grupo=G.PRESTAMOS, valor="5.00",
        afecta_calculos=True,
        descripcion="Se cobra sobre el capital de cada cuota vencida y no pagada, por día de atraso "
                    "(tasa ÷ 30 por día). Se copia a cada préstamo al aprobarlo.",
    ),
    "prestamos.dias_gracia_mora": dict(
        nombre="Días de gracia antes de cobrar mora", tipo=T.ENTERO, grupo=G.PRESTAMOS, valor="0",
        afecta_calculos=True,
        descripcion="La mora empieza a contar este número de días después del vencimiento. Se copia a cada "
                    "préstamo al aprobarlo.",
    ),
    "prestamos.dias_maximos_mora": dict(
        nombre="Días de atraso tras los cuales la mora se congela", tipo=T.ENTERO, grupo=G.PRESTAMOS, valor="90",
        afecta_calculos=True,
        descripcion="Pasados estos días desde el vencimiento de una cuota, su mora deja de aumentar. 0 = sin límite. "
                    "Se copia a cada préstamo al aprobarlo.",
    ),
    "caja.permitir_saldo_negativo": dict(
        nombre="Permitir egresos que dejen la caja o cuenta en negativo", tipo=T.BOOLEANO, grupo=G.CAJA,
        valor="false", afecta_calculos=True,
        descripcion="Si está desactivado, un egreso, una transferencia o un pago de ganancias no puede dejar "
                    "la caja o cuenta con saldo negativo en ninguna fecha.",
    ),
    "distribucion.base_calculo": dict(
        nombre="Base para repartir las ganancias", tipo=T.TEXTO, grupo=G.GANANCIAS, valor="PROMEDIO_DIARIO",
        afecta_calculos=True,
        descripcion="Quien más aporta, más recibe. PROMEDIO_DIARIO: saldo de aportaciones promedio de cada día del "
                    "período (cuenta cuánto tiempo estuvo el dinero). SALDO_CIERRE: saldo de aportaciones al último "
                    "día del período.",
    ),
    "distribucion.porcentaje_reserva": dict(
        nombre="Reserva antes de repartir (% de cada utilidad positiva)", tipo=T.DECIMAL, grupo=G.GANANCIAS,
        valor="0.00", afecta_calculos=True,
        descripcion="Porcentaje que se queda en CAUNE como reserva antes de repartir. 0 = se reparte todo.",
    ),
    "distribucion.incluir_inactivos": dict(
        nombre="Incluir afiliados inactivos al cierre del período", tipo=T.BOOLEANO, grupo=G.GANANCIAS,
        valor="false", afecta_calculos=True,
        descripcion="Si está desactivado, solo reciben ganancias los afiliados activos al último día del período.",
    ),
    "distribucion.aprobacion_requiere_otro_usuario": dict(
        nombre="La distribución la aprueba un usuario distinto al que la calculó", tipo=T.BOOLEANO,
        grupo=G.GANANCIAS, valor="true", afecta_calculos=True,
        descripcion="Control de doble persona antes de pagar o capitalizar ganancias.",
    ),
    "distribucion.tipo_capitalizacion": dict(
        nombre="Tipo de movimiento para capitalizar ganancias", tipo=T.TEXTO, grupo=G.GANANCIAS, valor="GAN",
        afecta_calculos=True,
        descripcion="Código del tipo de entrada donde se acreditan las ganancias capitalizadas (por defecto GAN, "
                    "una aportación).",
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


def _validar_gracia(valor):
    if valor is None or not (0 <= valor <= 90):
        raise ValueError("Los días de gracia deben estar entre 0 y 90.")


def _validar_maximo_mora(valor):
    if valor is None or not (0 <= valor <= 3650):
        raise ValueError("Indique entre 0 y 3650 días (0 = sin límite).")


def _validar_base(valor):
    if valor not in ("PROMEDIO_DIARIO", "SALDO_CIERRE"):
        raise ValueError("Indique PROMEDIO_DIARIO o SALDO_CIERRE.")


def _validar_porcentaje(valor):
    if valor is None or not (0 <= valor < 100):
        raise ValueError("El porcentaje debe estar entre 0 y 99.99.")


def _validar_tipo_capitalizacion(valor):
    from apps.aportaciones.models import TipoMovimiento

    if not TipoMovimiento.objects.filter(codigo=valor, activo=True,
                                         naturaleza=TipoMovimiento.Naturaleza.ENTRADA).exists():
        raise ValueError("Indique el código de un tipo de movimiento de entrada activo.")


# Validaciones de negocio adicionales al tipo de dato
VALIDADORES = {
    "prestamos.tasa_mora_interna": _validar_tasa,
    "prestamos.tasa_mora_externa": _validar_tasa,
    "prestamos.dias_gracia_mora": _validar_gracia,
    "prestamos.dias_maximos_mora": _validar_maximo_mora,
    "distribucion.base_calculo": _validar_base,
    "distribucion.porcentaje_reserva": _validar_porcentaje,
    "distribucion.tipo_capitalizacion": _validar_tipo_capitalizacion,
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
