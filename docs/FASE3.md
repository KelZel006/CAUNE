# Fase 3 · Caja y bancos, y distribución de ganancias

## 1. Alcance entregado

| Requerimiento | Estado | Dónde |
|---|---|---|
| Saldo de cada caja y cuenta bancaria, calculado (no guardado) | ✅ | `apps/caja` · Caja y bancos |
| Libro de caja que reúne todas las operaciones sin capturarlas otra vez | ✅ | `caja/services.py::lineas` · Reporte 12 |
| Ingresos y egresos varios por categoría; transferencias entre cajas y cuentas | ✅ | Caja y bancos → Ingreso / Egreso / Transferencia |
| Categorías de caja configurables, con o sin efecto en la utilidad | ✅ | Caja y bancos → Categorías |
| Control de saldo: ninguna salida deja una caja en negativo en ninguna fecha | ✅ | `caja.permitir_saldo_negativo` (por defecto: no) |
| **Cierre de caja** | ❌ No se hace (decisión de CAUNE) | — |
| Marcar afiliados que no participan en las ganancias de una actividad | ✅ | Detalle de la actividad → Participación en las ganancias |
| Cálculo de la distribución de ganancias por período | ✅ | `apps/distribucion` · Distribución de ganancias |
| Borrador, recálculo, aprobación por otra persona, anulación | ✅ | Detalle de la distribución |
| Pago en dinero o capitalización en la cuenta del afiliado | ✅ | Pagar o capitalizar |
| Reportes 10 a 14 (PDF y Excel) | ✅ | Reportes |
| Ganancias en la ficha del afiliado y dinero disponible en el panel | ✅ | |
| Cálculo y cobro de **mora** | ✅ | `prestamos/services.py::calcular_mora_cuota` · detalle del préstamo |
| Lo pagado de más en un préstamo va a **aportaciones** | ✅ | Tipo `EXP` · recibo de pago |
| **Afiliado responsable** de cada préstamo externo | ✅ | Formulario y detalle del préstamo |

## 2. Decisiones de CAUNE aplicadas (09/10/2026)

| Tema | Decisión | Implementación |
|---|---|---|
| Cierre de caja | No se hace | El saldo de cualquier fecha se calcula siempre desde las operaciones confirmadas. No hay arqueos, cierres diarios ni bloqueos de fechas. |
| Base del reparto | **Quien más aporta, más recibe** | Cada fondo se reparte en proporción al saldo de aportaciones del afiliado (tipos marcados «cuenta para la distribución»: por defecto APO sí, DEP no). |
| Quién recibe | Solo los afiliados (socios internos) | Los prestatarios externos nunca participan. |
| Ganancia capitalizada (10/10) | **Va a aportaciones** | Tipo `GAN` = aportación que cuenta para la distribución. |
| Pago de más en un préstamo (10/10) | Interno: **aportaciones del afiliado**. Externo: **depósito del afiliado que lo avala** | El pago guarda lo aplicado al préstamo y el excedente aparte; el excedente crea un movimiento `EXP` (aportación) o `EXA` (depósito del aval) en la misma caja. Un externo sin responsable no puede pagar de más. |
| Número de préstamo (10/10) | **1** interno / **2** externo + año en curso + correlativo de 3 dígitos que se reinicia cada año | Ej.: 12026001, 22026002, 12027001. Internos y externos comparten el correlativo del año (secuencia `PR2026`, `PR2027`…). Los préstamos existentes se renumeraron en orden de registro y quedó en auditoría. |
| Préstamos externos (10/10) | Los campos del tercero solo aparecen al elegir «Externo» y se indica el **afiliado responsable** | Obligatorio y activo al aprobar; se puede cambiar con motivo; aparece en la ficha del afiliado. |
| Mora (10/10) | Se calcula y se cobra | Ver sección 4 bis. |
| Exclusión por actividad | Se marca en cada actividad | Un afiliado marcado no recibe nada del resultado de **esa** actividad, pero sí su parte de los intereses y de las demás actividades. El fondo de la actividad se reparte solo entre los demás. |

## 3. Cómo se calcula una distribución

1. **Período**: fecha inicial y final (por defecto, del 1 de enero a hoy). Dos distribuciones no pueden cruzarse.
2. **Fondos**:
   - *Utilidad general* = intereses cobrados de préstamos (internos y externos) + ingresos de caja con categoría que
     cuenta como utilidad − egresos de caja con categoría que cuenta como utilidad. El capital recuperado y el saldo
     inicial de caja **no** son utilidad.
   - *Un fondo por actividad* con ingresos o gastos en el período: su resultado neto.
3. **Participantes**: afiliados que ingresaron antes del cierre, activos al último día del período (configurable) y
   con saldo de aportaciones.
4. **Base de cada afiliado** (parámetro `distribucion.base_calculo`):
   - `PROMEDIO_DIARIO` (por defecto): saldo de aportaciones al final de cada día del período, promediado. Premia el
     tiempo que el dinero estuvo en CAUNE; quien aporta el último día no recibe lo mismo que quien aportó todo el año.
   - `SALDO_CIERRE`: saldo de aportaciones al último día del período.
5. **Reserva** (`distribucion.porcentaje_reserva`, por defecto 0 %): se descuenta de cada fondo con ganancia.
6. **Reparto**: parte = a repartir × base del afiliado ÷ suma de bases de quienes participan en ese fondo. Los centavos
   se asignan por mayor residuo: la suma de las partes es exactamente el fondo.
7. **Pérdidas**: una actividad con pérdida reparte la pérdida entre quienes participan en ella. Si a un afiliado le
   resulta un total negativo, la distribución **no se puede aprobar** hasta revisar quién participa.

**Ejemplo verificado** (`test_excluido_de_actividad_recibe_solo_el_resto`): A, B y C aportaron 1,000 / 3,000 / 6,000.
Utilidad general 1,000 → 100 / 300 / 600. Rifa con ganancia de 500 y C marcado como no participante → A 125, B 375
(proporción 1,000 : 3,000). Totales: A 225, B 675, C 600.

### Ciclo de vida

| Estado | Qué se puede hacer |
|---|---|
| Calculada (borrador) | Revisar, recalcular, aprobar, anular |
| Aprobada | Pagar o capitalizar (por afiliado o a todos), anular si aún no hay entregas |
| Pagada o capitalizada | Consultar; anular una entrega la devuelve a Aprobada |
| Anulada | Solo consulta; el período queda libre |

- Al **aprobar**, el sistema recalcula y compara con el borrador. Si alguien registró o anuló operaciones del período,
  o cambió quién participa, exige recalcular primero.
- La aprueba un usuario **distinto** al que la calculó (`distribucion.aprobacion_requiere_otro_usuario`).
- **Pago**: sale de la caja o cuenta elegida y verifica que haya saldo. Es todo o nada: si a uno no le alcanza, no se
  registra ninguno.
- **Capitalización**: no sale dinero; se acredita en la cuenta del afiliado como «Ganancia capitalizada» (tipo `GAN`,
  depósito reembolsable, configurable en `distribucion.tipo_capitalizacion`).
- Una ganancia no se entrega dos veces: la base de datos lo impide con un índice único.

## 4 bis. Mora de préstamos

- **Fórmula:** mora de cada cuota = capital vencido y no pagado × (tasa de mora mensual ÷ 30) × días de atraso.
  Solo el capital genera mora; los intereses atrasados no.
- **Desde cuándo:** desde el vencimiento más los días de gracia (`prestamos.dias_gracia_mora`, por defecto 0).
- **Hasta cuándo:** a los **90 días** del vencimiento la mora de la cuota se **congela** y deja de aumentar
  (`prestamos.dias_maximos_mora`; 0 = sin límite). Los días de atraso se siguen mostrando.
- **Tasas** (`prestamos.tasa_mora_interna` 1 %, `prestamos.tasa_mora_externa` 5 % mensual): se **congelan** en
  cada préstamo al aprobarlo, igual que la tasa de interés. A los préstamos ya existentes se les asignó la tasa
  vigente al migrar.
- **Pagos parciales:** si se paga parte del capital vencido, la mora sigue corriendo sobre lo que quedó pendiente.
- **Orden de un pago de cuota:** mora → interés → capital. El abono extraordinario va solo a capital.
- **Se calcula, no se guarda:** la mora pendiente se calcula a la fecha de consulta (o a la fecha del pago). Lo
  que sí se guarda es cuánto de cada pago fue a mora.
- La **mora cobrada es ingreso**: suma a la utilidad general que se reparte, aparece aparte en el flujo de
  efectivo y en el reporte de pagos.
- Un préstamo pasa a «Cancelado (pagado)» solo cuando no debe capital, intereses ni mora.

**Ejemplo verificado** (`test_pago_cubre_mora_luego_interes_luego_capital`): cuota de 1,000 + 10 de interés,
vencida hace 30 días. A los 15 días de atraso paga 515: 5.00 a mora (1,000 × 1 % × 15 ÷ 30), 10 a interés y 500 a
capital. Hoy la mora generada es 5.00 + 500 × 1 % × 15 ÷ 30 = 7.50; pendiente 2.50; total por pagar 502.50.

## 4. Caja y bancos

El libro de caja **no se captura**: se arma con lo que ya registra cada módulo. Cada operación aparece una sola vez:

| Origen | Entra | Sale |
|---|---|---|
| Aportaciones y depósitos / retiros | ✅ | ✅ |
| Desembolsos de préstamos | | ✅ |
| Pagos de préstamos (capital e intereses) | ✅ | |
| Ingresos y gastos de actividades | ✅ | ✅ |
| Ingresos y egresos varios de caja | ✅ | ✅ |
| Transferencias entre cajas y cuentas | ✅ destino | ✅ origen |
| Ganancias pagadas | | ✅ |
| Ganancias capitalizadas | — | — (no mueven dinero) |

Los egresos, transferencias y pagos de ganancias no pueden dejar la cuenta en negativo **en ninguna fecha**, ni
siquiera si se registran con fecha anterior. Anular un ingreso que ya se gastó también se rechaza.

Categorías iniciales: Saldo inicial (no es utilidad), Intereses bancarios, Otros ingresos, Gastos administrativos,
Comisiones bancarias, Otros egresos.

## 5. Reportes nuevos

| N.º | Reporte | Contenido |
|---|---|---|
| 10 | Ganancias por afiliado | Base, porcentaje, parte de cada fondo, total y entrega (de una distribución) |
| 11 | Distribuciones de ganancias | Resultado, reserva, repartido y entregado por período |
| 12 | Libro de caja y bancos | Saldo inicial, cada entrada y salida con saldo acumulado, saldo final; por cuenta o consolidado |
| 13 | Flujo de efectivo | Entradas y salidas por origen (capital e intereses por separado) |
| 14 | Resumen financiero | Dinero + cartera frente a aportaciones + depósitos + utilidades no repartidas, con **verificación de cuadre** |

El resumen financiero comprueba que `dinero + préstamos por cobrar = aportaciones + depósitos + utilidades no
repartidas + fondos de caja que no son utilidad`. Si la diferencia no es cero, algo se registró fuera de su módulo.
Con los datos locales del 09/10/2026 la diferencia es L 0.00.

## 6. Modelo de datos nuevo

| Tabla | Contenido | Restricciones clave |
|---|---|---|
| `caja_categoriacaja` | Categorías de ingresos y egresos | nombre único |
| `caja_movimientocaja` | Ingresos, egresos y transferencias | monto > 0; tipo coherente (categoría o destino, destino ≠ origen); idempotencia; anulación coherente |
| `actividades_exclusionactividad` | Afiliado que no participa en una actividad | (actividad, afiliado) único |
| `distribucion_distribucion` | Período, reglas congeladas, estado | fin ≥ inicio; reserva 0-99.99; aprobación con usuario; anulación coherente |
| `distribucion_fondodistribucion` | Fotografía de cada fondo | tipo coherente con la actividad; un fondo por actividad |
| `distribucion_lineadistribucion` | Parte de cada afiliado en cada fondo | (fondo, afiliado) único |
| `distribucion_pagoganancia` | Pago o capitalización | monto > 0; **una entrega confirmada por afiliado y distribución**; capitalización con su movimiento |

**Se calcula, no se guarda:** saldos de caja y bancos, libro de caja, flujo de efectivo y resumen financiero. La
distribución sí guarda su fotografía, porque es una decisión aprobada que debe poder consultarse tal como se aprobó.

## 7. Permisos y roles

| Rol | Caja | Distribución |
|---|---|---|
| Administrador / Tesorero | Todo | Todo (calcular, aprobar, pagar, anular) |
| Presidente | Consulta | Consulta |
| Contador o supervisor | Consulta y anulación | Consulta y anulación |
| Encargados de préstamos y de actividades | Sin acceso | Sin acceso |

Marcar quién no participa en una actividad requiere el permiso «gestionar participación» (Tesorero y Administrador).
Todo se ajusta en Configuración → Roles.

## 8. Criterio de aceptación y resultados

Resultado de `pytest` el 10/10/2026: **257 pruebas aprobadas, 0 fallidas** (175 de las fases 1 y 2 + 82 nuevas).
Las pruebas de las fases 1 y 2 que verifican intereses y capital corren con la mora en cero (fixture `sin_mora`);
la mora tiene sus propias pruebas en `tests/test_mora.py`.

| Escenario | Pruebas |
|---|---|
| Quien más aporta recibe más | `test_quien_mas_aporta_mas_recibe` |
| Excluido de una actividad recibe solo del resto | `test_excluido_de_actividad_recibe_solo_el_resto`, `test_resumen_financiero_cuadra_con_todas_las_fuentes` |
| Promedio diario vs. saldo al cierre | `test_promedio_diario_premia_el_tiempo` |
| Centavos exactos | `test_centavos_por_mayor_residuo_suman_exacto`, `test_repartir_invariantes` |
| Solo afiliados activos con aportaciones; depósitos no cuentan | `test_inactivo_al_cierre_no_participa`, `test_afiliado_sin_aportaciones_ni_externos_participan` |
| Intereses y gastos de caja en la utilidad; saldo inicial no | `test_intereses_de_prestamos_internos_y_externos_son_utilidad`, `test_gastos_de_caja_restan_y_saldo_inicial_no_es_utilidad` |
| Aprobación por otra persona y con datos vigentes | `test_aprobacion_por_otro_usuario`, `test_no_se_aprueba_si_los_datos_cambiaron` |
| Períodos que no se cruzan | `test_periodos_no_se_cruzan`, `test_anulada_libera_el_periodo` |
| Pago y capitalización, sin entregar dos veces | `test_pagar_en_efectivo_sale_de_caja`, `test_capitalizar_acredita_deposito_sin_mover_caja`, `test_anular_pago_devuelve_a_aprobada` |
| Saldo de caja con todas las fuentes, sin duplicar | `test_saldo_reune_todas_las_fuentes_sin_duplicar` |
| Ninguna salida deja la caja en negativo | `test_egreso_sin_saldo_rechazado`, `test_egreso_con_fecha_anterior_no_puede_dejar_negativo_un_dia_posterior`, `test_pago_sin_efectivo_suficiente_no_registra_ninguno` |
| Reportes iguales a los servicios y cuadre en cero | `test_reportes_fase3_coinciden_con_servicios`, `test_resumen_financiero_cuadra_con_todas_las_fuentes` |
| Mora por días, gracia, tasa congelada, orden de aplicación | `tests/test_mora.py` |
| Pago de más: interno a aportaciones, externo a depósito del aval | `test_lo_pagado_de_mas_va_a_aportaciones`, `test_anular_pago_anula_el_excedente`, `test_externo_que_paga_de_mas_deja_deposito_al_aval` |
| Mora congelada a los 90 días | `test_mora_se_congela_a_los_90_dias`, `test_sin_limite_si_el_parametro_es_cero` |
| Número 1/2 + año + correlativo que se reinicia | `test_numero_de_prestamo_por_anio` |
| Afiliado responsable obligatorio en externos | `test_externo_exige_afiliado_responsable_activo`, `test_cambiar_responsable_y_ficha_del_afiliado` |
| Permisos | `test_permisos_fase3`, `test_permisos_caja`, `test_permisos_distribucion`, `test_presidente_no_marca_participacion` |

También se revisaron en el navegador, con los datos locales: Caja y bancos, detalle de actividad con la tarjeta de
participación y el detalle de una distribución calculada.

## 9. Limitaciones conocidas

- Igual que en las fases anteriores, las pruebas corrieron en SQLite; falta correrlas contra PostgreSQL 16.
- Sin cierre de caja, una operación registrada con fecha dentro de un período ya **aprobado** cambia los saldos de
  ese período, pero no cambia la distribución aprobada (su fotografía queda fija). El reporte 14 lo dejaría ver.
- Los retiros, desembolsos y gastos de actividades (fases 1 y 2) todavía no verifican el saldo de la caja; solo lo
  hacen los egresos, transferencias y pagos de ganancias nuevos.
- No hay conciliación bancaria contra el estado de cuenta del banco.
- 22026003 (antes PREST-0003, externo de demostración) se creó antes de exigir responsable: el detalle lo advierte y permite asignarlo.
- No hay condonación de mora ni cobro de mora sobre intereses atrasados.

## 10. Decisiones pendientes de CAUNE

| Código | Pregunta | Valor actual (configurable) |
|---|---|---|
| D2 | ¿Base del reparto: promedio diario o saldo al cierre? | Promedio diario |
| D4 | ¿Reserva antes de repartir? ¿Qué porcentaje? | 0 % |
| D5 | ¿Se paga en dinero o se capitaliza? | Se elige en cada entrega; lo capitalizado va a aportaciones |
| M1 | ¿Tasa de mora? | 1 % mensual internos, 5 % externos, sobre capital vencido |
| M2 | ¿Días de gracia? | 0 |
| M3 | ¿Se puede perdonar (condonar) la mora? | No hay opción todavía |
| D6 | ¿Qué hacer si una actividad con pérdida deja a alguien en negativo? | Se bloquea la aprobación |
| D7 | ¿Quién aprueba el reparto? | Tesorero o Administrador, distinto a quien calculó |
| — | ¿Los depósitos también deberían generar ganancias? | No (solo aportaciones) |
