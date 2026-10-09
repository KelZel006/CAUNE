# Fase 2 · Préstamos y actividades económicas

## 1. Alcance entregado

| Requerimiento | Estado | Dónde |
|---|---|---|
| Registro de préstamos internos (afiliados) y externos | ✅ | `apps/prestamos` · Préstamos → Nuevo |
| Tasas editables (1 % interno, 5 % externo, mensuales) con historial | ✅ | Configuración → Datos generales y reglas (grupo Préstamos) |
| Condiciones congeladas en cada préstamo; excepciones de tasa autorizadas | ✅ | `Prestamo.tasa`, `tasa_configurada`, `excepcion_autorizada_por` |
| Cuadro de amortización: cuota fija y capital fijo | ✅ | `prestamos/amortizacion.py` |
| Vista previa del cuadro antes de aprobar | ✅ | Botón «Ver cuadro de amortización» |
| Desembolso, anulación de préstamos no desembolsados | ✅ | Detalle del préstamo |
| Pagos de cuota, pagos parciales y abonos extraordinarios a capital | ✅ | Registrar pago |
| Distribución de cada pago entre interés y capital, por cuota | ✅ | `AplicacionPago` y recibo |
| Saldo de capital, intereses cobrados y pendientes, próxima cuota | ✅ | Calculados en `prestamos/services.py` |
| Recibo de pago (pantalla y PDF); cuadro en PDF y Excel | ✅ | |
| Actividades, subactividades, ingresos y gastos | ✅ | `apps/actividades` |
| Resultado por actividad, subactividad y período (ganancia o pérdida) | ✅ | Detalle de la actividad y reportes 8-9 |
| Reportes 4 a 9 (PDF y Excel) | ✅ | Reportes |
| Roles: Encargado de préstamos y Encargado de actividades con permisos propios | ✅ | `apps/core/roles.py` |
| Control de mora, penalizaciones, cobranza | ❌ Fuera de alcance (documento maestro) | |

## 2. Decisiones de CAUNE aplicadas (08/10/2026)

| Código | Decisión | Implementación |
|---|---|---|
| P1 | Tasas **mensuales** | `prestamos.periodicidad_tasa = MENSUAL`; el sistema rechaza otra periodicidad hasta que se programe. |
| P2 | Interés **por cuota** | Interés de la cuota = saldo de capital × tasa mensual, redondeo HALF_UP a 2 decimales. La última cuota se ajusta para dejar el saldo en 0.00. |
| P4 | Pagos parciales **sí**, interés primero | Un pago cubre, cuota por cuota en orden, primero el interés pendiente y luego el capital. Configurable (`prestamos.permitir_pagos_parciales`). |
| P5 | Abono extraordinario **sin efecto en el cuadro** | El abono va solo a capital de las cuotas siguientes, en orden de vencimiento. Las cuotas, sus montos y sus intereses se mantienen como se acordaron. **Consecuencia:** quien adelanta capital sigue debiendo los intereses del cuadro en sus fechas. Si CAUNE decide más adelante reducir plazo o cuota, se agregará como opción con recálculo versionado. |

### Reglas adicionales aplicadas (configurables o documentadas)
- Monto aprobado ≤ monto solicitado; plazo entre 1 y `prestamos.plazo_maximo` (60).
- Solo afiliados **activos** reciben préstamos internos. Una identidad de afiliado no puede registrarse como prestatario externo.
- Una tasa distinta a la configurada exige el permiso «autorizar excepción de tasa» y un motivo (Tesorero y Administrador lo tienen; el Encargado de préstamos no).
- El primer vencimiento debe ser posterior a la aprobación y el desembolso anterior al primer vencimiento.
- Los pagos se registran en orden de fecha; el préstamo pasa a **Cancelado (pagado)** cuando no queda capital ni interés pendiente.
- **Anulación de pagos:** solo el último pago confirmado del préstamo, con motivo y por un usuario distinto al que lo registró. Un préstamo solo se anula antes de su desembolso.
- **Intereses como ingreso:** se reconocen cuando se **cobran** (base de efectivo). El capital recuperado no es ganancia.
- Actividades **cerradas** no admiten registros; una subactividad debe pertenecer a su actividad. Anulación con motivo y doble persona.
- Cada préstamo, pago, desembolso y gasto/ingreso guarda su caja o cuenta: en la Fase 3 cada uno generará **un único** movimiento de caja (sin duplicar).

## 3. Modelo de datos nuevo

| Tabla | Contenido | Restricciones clave |
|---|---|---|
| `prestamos_prestatarioexterno` | Nombre, identidad (única), contacto | identidad 13 dígitos |
| `prestamos_prestamo` | Condiciones congeladas, fechas, estado | montos > 0, aprobado ≤ solicitado, tasa ≥ 0, plazo ≥ 1, prestatario coherente con el tipo, desembolso con cuenta |
| `prestamos_cuotaamortizacion` | Cuadro aprobado | (préstamo, número) único; cuota = capital + interés; no modificable |
| `prestamos_pagoprestamo` | Pagos y abonos | monto > 0; clave de idempotencia única; anulación coherente |
| `prestamos_aplicacionpago` | Interés y capital aplicados por cuota | ≥ 0, no vacía, (pago, cuota) única; no modificable |
| `actividades_actividad` / `actividades_subactividad` | Actividades y subactividades | nombre único (por actividad) |
| `actividades_movimientoactividad` | Ingresos y gastos | monto > 0; idempotencia; anulación coherente |

**Se calcula, no se guarda:** saldo de capital, intereses cobrados y pendientes, estado de cada cuota, resultado de actividades.

## 4. Criterio de aceptación y resultados

> *«Comprobar mediante casos de prueba que las amortizaciones, los saldos pendientes y las ganancias o pérdidas se calculan correctamente.»*

Resultado de `pytest` el 08/10/2026: **175 pruebas aprobadas, 0 fallidas** (103 de la Fase 1 + 72 nuevas).

| Escenario obligatorio | Pruebas |
|---|---|
| Préstamos internos al 1 % y externos al 5 % | `test_interno_usa_1_por_ciento_y_externo_5` |
| Cambiar tasas sin afectar préstamos existentes | `test_cambio_de_tasa_no_afecta_prestamos_existentes` |
| Cuotas con distintos plazos y métodos | `test_amortizacion.py` (cálculos a mano, caso PREST-001 de Airtable, 10 combinaciones de invariantes) |
| Pagos parciales y abonos a capital | `test_pago_parcial_cubre_interes_primero`, `test_abono_extraordinario_no_cambia_el_cuadro` |
| Saldo pendiente después de cada pago | `test_saldo_despues_de_cada_pago` |
| Actividades con múltiples ingresos y gastos; ganancias y pérdidas | `test_actividades.py` |
| Una operación no se registra dos veces | `test_pago_no_se_duplica`, doble POST en `test_flujo_prestamo_por_la_web` |
| Usuarios sin acceso a funciones no autorizadas | `test_permisos_fase2`, `test_presidente_no_registra_pagos` |
| Reportes comparados con los movimientos de origen | `test_reportes_fase2_coinciden_con_servicios` |

Hallazgo durante las pruebas: en Airtable, PREST-001 (15,000 al 18 % anual, 12 cuotas) tenía una cuota escrita a mano de L 1,375.50; el cálculo correcto es **L 1,375.20**.

## 5. Limitaciones conocidas
- Igual que en la Fase 1, las pruebas corrieron en SQLite; falta correrlas contra PostgreSQL 16 antes de producción.
- La restricción `cuota = capital + interés` tolera medio centavo porque SQLite compara decimales como flotantes; en PostgreSQL la igualdad es exacta.
- Los prestatarios externos se crean desde el formulario del préstamo; no hay pantalla para editarlos todavía.
- Solo frecuencia de pago mensual (es la única periodicidad aprobada).

## 6. Decisiones que necesito de CAUNE para la Fase 3
D1 (intereses cobrados vs. devengados para la ganancia; hoy: cobrados), D2 (participación: saldo al cierre o ponderado por tiempo), D3 (afiliados que ingresan o salen a mitad del período), D4 (reservas: cuáles y qué porcentaje), D5 (período anual; pago o capitalización), D6 (tratamiento de pérdidas), D7 (quién aprueba el reparto), C1 (control de caja por categorías antes que contabilidad completa).
