# Fase 1 · Administración básica

## 1. Alcance entregado

| Requerimiento | Estado | Dónde |
|---|---|---|
| Gestión de afiliados (crear, consultar, editar, buscar, activar/inactivar) | ✅ | `apps/afiliados` |
| Historial de estados con fecha efectiva y motivo | ✅ | `CambioEstadoAfiliado` |
| Aportaciones, depósitos y retiros con tipos configurables | ✅ | `apps/aportaciones` |
| Saldos acumulados (calculados, nunca almacenados) | ✅ | `aportaciones/services.py` |
| Recibos imprimibles y PDF, con monto en letras | ✅ | `/movimientos/<id>/recibo/` |
| Estado de cuenta por afiliado y período (HTML, PDF, Excel) | ✅ | `/afiliados/<id>/estado-de-cuenta/` |
| Reportes 1 (afiliados), 2 (estado de cuenta) y 3 (aportaciones y depósitos) | ✅ | `apps/reportes` |
| Usuarios, roles configurables y permisos verificados en el servidor | ✅ | Configuración → Usuarios / Roles |
| Bloqueo tras 5 intentos fallidos de ingreso | ✅ | django-axes |
| Auditoría inmutable (ingresos, altas, cambios, anulaciones, configuración) | ✅ | `HistorialAuditoria` |
| Configuración: datos de CAUNE, reglas, tipos, cajas/cuentas, numeración | ✅ | Configuración |
| Esquema de base de datos y migraciones | ✅ | `apps/*/migrations` |
| Respaldos automáticos y prueba de restauración | ✅ (scripts) | `scripts/`, `docker-compose.yml` |
| Préstamos, actividades, caja y bancos, distribución | ⏳ Fases 2 y 3 | — |

## 2. Decisiones aplicadas (según las recomendaciones aprobadas)

| Código | Decisión | Cómo quedó implementada |
|---|---|---|
| G1 | Corrección de errores | Las operaciones no se editan ni se borran (lo impiden el modelo, el queryset y el admin). Un usuario con permiso «anular» marca la operación como **ANULADA** con un motivo de al menos 10 caracteres. Por defecto debe ser **otro usuario distinto al que la registró** (parámetro `movimientos.anulacion_requiere_otro_usuario`). La operación sigue visible, deja de sumar y queda en auditoría. |
| G2 | Migración | Se empieza desde cero. No se migraron los 5 préstamos «de prueba» de Airtable. |
| G3 | Tecnología | Django 5.2 LTS + PostgreSQL 16 + Docker. |
| A1 | Aportación vs. depósito | Clase `APORTACION` = capital del afiliado. Clase `DEPOSITO` = ahorro reembolsable. Cada tipo de movimiento tiene clase y naturaleza (entrada o retiro), que se bloquean cuando ya tiene movimientos. |
| A2 | Retiros | Solo de depósitos (tipo `RDEP`). Los retiros de aportaciones están deshabilitados por parámetro (`movimientos.permitir_retiro_aportaciones`). Un retiro no puede dejar el saldo negativo **en ninguna fecha**, ni siquiera cuando se registra con fecha anterior. |
| A3 | Participación de los depósitos en las ganancias | **Pendiente.** Se guarda como bandera por tipo (`participa_distribucion`): por defecto APO = sí y DEP = no. Se usará en la Fase 3. |
| — | Afiliados inactivos | No admiten movimientos nuevos (parámetro `afiliados.permitir_movimientos_inactivos`). |

### Reglas de validación de movimientos
- Monto > 0, máximo 2 decimales y menor de L 1,000,000,000,000. La base de datos también lo exige con `CHECK monto > 0`.
- La fecha no puede ser futura ni anterior al ingreso del afiliado.
- Efectivo solo en una **caja**. Transferencia o depósito bancario solo en una **cuenta bancaria**. El cheque puede ir en cualquiera.
- La referencia es obligatoria para transferencias, depósitos bancarios y cheques.
- El tipo y la caja o cuenta deben estar activos.
- **Doble registro**: cada formulario lleva una clave única (`clave_idempotencia`). Si se reenvía, devuelve la misma operación sin crear otra, y la base de datos lo garantiza con un índice único.
- **Concurrencia**: cada registro o anulación bloquea la fila del afiliado (`SELECT … FOR UPDATE`), y la numeración bloquea la fila de su secuencia.

## 3. Modelo de datos (Fase 1)

| Tabla | Qué se guarda | Restricciones clave |
|---|---|---|
| `afiliados_afiliado` | Datos personales, estado | `codigo` y `identidad` únicos, identidad de 13 dígitos, `CHECK estado` |
| `afiliados_cambioestadoafiliado` | Activaciones e inactivaciones | FK PROTECT |
| `aportaciones_tipomovimiento` | Clasificación configurable | `codigo` y `nombre` únicos |
| `aportaciones_movimientoafiliado` | Cada operación | `numero_operacion` y `clave_idempotencia` únicos, `CHECK monto > 0`, `CHECK` de coherencia de anulación, índices (afiliado, fecha) y (fecha) |
| `core_cuentafondo` | Cajas y cuentas bancarias | (banco, número de cuenta) únicos para bancos |
| `core_secuencia` | Correlativos AF-0001 y OP-000001 | prefijo único, solo avanza |
| `core_parametro` / `core_historialparametro` | Reglas y datos de CAUNE, con historial | clave única |
| `core_historialauditoria` | Bitácora inmutable | sin UPDATE ni DELETE desde la aplicación |
| `auth_user` / `auth_group` / `auth_permission` | Usuarios, roles y permisos | contraseñas con Argon2 |

**Se calcula, no se guarda:** saldos de aportaciones y depósitos, saldo total, saldo inicial y final del estado de
cuenta, y totales de los reportes. Todo sale de `aportaciones/services.py`.

Todos los importes se guardan como `NUMERIC(14,2)` (`Decimal` en Python), con redondeo HALF_UP a 2 decimales.

## 4. Criterio de aceptación y resultados

> *«Registrar afiliados y movimientos, consultar saldos y generar recibos correctamente.»*

Resultado de `pytest` el 08/10/2026: **89 pruebas aprobadas, 0 fallidas** (SQLite en memoria).

| Escenario obligatorio (sección 16) | Pruebas |
|---|---|
| Crear, editar e inactivar afiliados | `test_afiliados.py` (14) |
| Registrar aportaciones y depósitos | `test_movimientos.py::test_registrar_*`, `test_vistas.py::test_flujo_completo_*` |
| Verificar saldos individuales | `test_saldos_individuales_independientes`, `test_saldos_anotados_coinciden_con_servicio`, `test_estado_de_cuenta_cuadra_con_saldos` |
| Una operación no se registra dos veces | `test_misma_clave_no_registra_dos_veces`, doble POST en `test_flujo_completo_*` |
| Usuarios sin acceso a funciones no autorizadas | `test_permisos.py` (18) |
| Comparar reportes con movimientos de origen | `test_reporte_movimientos_coincide_con_origen`, `test_reporte_afiliados`, Excel del estado de cuenta |
| Montos inválidos, afiliados inexistentes, registros incompletos | `test_montos_invalidos`, `test_afiliado_inexistente`, `test_registro_incompleto_rechazado` |
| No eliminar transacciones confirmadas en silencio | `test_movimiento_confirmado_no_se_edita_ni_elimina`, `test_base_de_datos_rechaza_*`, `test_auditoria_inmutable` |
| Cambios de configuración registrados | `test_parametro_que_afecta_calculos_exige_motivo_y_guarda_historial` |

También se verificó de forma manual en el navegador, con datos ficticios: ingreso, panel, ficha de afiliado,
rechazo de un retiro sin saldo (el error aparece junto al campo), recibo en pantalla y en PDF, estado de cuenta en
PDF y la vista de celular.

## 5. Limitaciones conocidas y pendientes

- **Las pruebas no se han corrido contra PostgreSQL.** El equipo de desarrollo no tenía PostgreSQL ni Docker. Antes de
  producción hay que correr `TEST_DATABASE_URL=… pytest` contra PostgreSQL 16. SQLite ignora `SELECT … FOR UPDATE`, así
  que las pruebas de concurrencia real solo tienen sentido en PostgreSQL.
- Los respaldos y la restauración están escritos pero **no se han ejecutado** por la misma razón. Se validan en la Fase 4.
- Caja y bancos: en esta fase cada operación indica la caja o cuenta, pero los saldos, transferencias y conciliaciones
  llegan en la Fase 3. Los movimientos de la Fase 1 entrarán al libro de caja sin necesidad de capturarlos otra vez.
- El estado de cuenta todavía no muestra préstamos, pagos ni ganancias (fases 2 y 3).
- La identidad se valida con el formato hondureño de 13 dígitos. Si CAUNE tiene afiliados con otro documento, hay que
  definir cómo registrarlos.

## 6. Decisiones que necesito de CAUNE para la Fase 2

P1 (periodicidad del 1 % y del 5 %), P2 (cálculo del interés por cuota o por días), P3 (frecuencias y plazo máximo),
P4 (pagos parciales y orden de aplicación), P5 (abono extraordinario: reducir plazo o cuota), P6 (quién aprueba los
préstamos y las excepciones de tasa).
