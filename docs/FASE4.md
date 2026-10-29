# Fase 4 · Estados financieros y reportes de caja

## 1. Alcance entregado

| N.º | Reporte | Contenido | Formatos |
|---|---|---|---|
| 15 | Balance general | Activo (efectivo por caja y cuenta, cartera interna y externa), pasivo (depósitos, ganancias por pagar) y patrimonio (aportaciones, fondos que no son utilidad, reserva, resultados anteriores y del ejercicio). Comparación con otra fecha y columna de variación. Verificación del cuadre. Cuentas de orden: intereses vencidos y mora por cobrar (solo con corte de hoy). | Pantalla, PDF con firmas, Excel |
| 16 | Estado de resultados | Ingresos financieros (intereses y mora de afiliados y externos), resultado de cada actividad, otros ingresos y gastos de operación por categoría, utilidad neta. Comparación opcional con el mismo período del año anterior. | Pantalla, PDF con firmas, Excel |
| 17 | Estado de cambios en el patrimonio | Columnas aportaciones, fondos no utilidad, reserva, resultados acumulados y total. Filas: saldo inicial, aportaciones por tipo (incluidas ganancias capitalizadas y excedentes), fondos recibidos, utilidad del período, reserva y ganancias distribuidas, saldo final. | Pantalla, PDF horizontal, Excel |
| 18 | Estado de flujo de efectivo | Método directo en tres grupos: operación, cartera de préstamos (inversión) y financiamiento. Efectivo inicial, aumento neto y efectivo final. | Pantalla, PDF con firmas, Excel |
| 19 | Indicadores financieros | Liquidez, colocación, morosidad, capitalización, endeudamiento, rentabilidad sobre aportaciones y activos, margen neto y peso de los intereses. | Pantalla, PDF, Excel |
| — | Estados financieros completos | Los reportes 15 a 19 de un período en un solo documento: PDF con una página por estado y firmas, o Excel con una hoja por estado. | Pantalla, PDF, Excel |
| 20 | Saldos por caja y cuenta | Saldo inicial, entradas, salidas y saldo final de cada caja y cuenta bancaria en el período. Cada fila abre su libro de caja. | Pantalla, PDF, Excel |
| 21 | Resumen diario de caja | Por día con operaciones: cantidad, entradas, salidas, neto y saldo al cierre. Por cuenta o consolidado (el consolidado no cuenta transferencias internas). Por defecto, el mes en curso. | Pantalla, PDF, Excel |
| 22 | Antigüedad de la cartera | Préstamos vigentes por días de atraso (al día, 1-30, 31-60, 61-90, más de 90): saldo, capital vencido, intereses vencidos, mora y porcentaje de la cartera. Índice de morosidad. | Pantalla, PDF horizontal, Excel |

Los estados están en **Reportes → Estados financieros**. Los reportes 20 y 21 están en **Caja y finanzas** y el 22
en **Préstamos**.

## 2. Cómo se arman

No hay asientos contables aparte: cada cifra sale de los mismos servicios que usan los módulos
(`apps/reportes/financieros.py`). Por eso los estados no pueden contradecir al libro de caja, a los préstamos ni a
la distribución de ganancias.

- **Base de efectivo.** Los intereses y la mora son ingreso cuando se cobran, igual que en la distribución. Los
  intereses vencidos y la mora pendiente se informan como cuentas de orden, fuera del balance.
- **Ejercicio = año calendario.** «Resultado del ejercicio» va del 1 de enero a la fecha de corte; lo anterior es
  «Resultados acumulados de ejercicios anteriores».
- **Distribuciones.** Al aprobarse, lo repartido pasa de resultados a **Ganancias distribuidas por pagar** (pasivo)
  y lo retenido pasa a **Reserva**. Al pagarse, baja el pasivo y el efectivo. Al capitalizarse, baja el pasivo y suben
  las aportaciones. Una distribución resta del ejercicio en que **termina su período**: distribuir el año anterior no
  toca el resultado del año en curso.
- **Fechas pasadas.** Un balance a una fecha anterior solo cuenta las distribuciones aprobadas hasta ese día. Las
  anulaciones se tratan como en el resto del sistema: lo anulado no cuenta en ninguna fecha.

**Cuadre (balance):** efectivo + cartera = depósitos + ganancias por pagar + aportaciones + fondos que no son
utilidad + reserva + resultados. Es la misma ecuación del resumen financiero (reporte 14), con el pasivo separado.
El patrimonio y el flujo de efectivo también traen su verificación: si alguna da distinto de cero, la pantalla lo
advierte en rojo.

Con los datos locales del 25/10/2026: activo L 118,252.98 = pasivo L 20,900.00 + patrimonio L 97,352.98. Las
diferencias del balance, del patrimonio y del flujo son L 0.00.

## 3. Firmas

Los PDF de los estados llevan espacio para la firma del **Tesorero**, del **Presidente** y del **Contador o
revisor**. Los nombres se configuran en **Configuración → Parámetros** (`coop.firma_tesorero`,
`coop.firma_presidente`, `coop.firma_revisor`). Si un nombre está vacío, la línea queda en blanco.

## 4. Permisos

| Reporte | Permiso |
|---|---|
| 15-19 y estados completos | Ver reportes + panel financiero (Tesorero, Presidente, Contador o supervisor, Administrador) |
| 20-21 | Ver reportes + consultar caja |
| 22 | Ver reportes + consultar préstamos (incluye al encargado de préstamos) |

## 5. Pruebas

Resultado de `pytest` el 26/10/2026: **300 pruebas aprobadas, 0 fallidas, tanto en SQLite como en PostgreSQL 16**
(257 de las fases 1 a 3 + 43 nuevas en `tests/test_estados_financieros.py`, `tests/test_saldo_caja.py` y
`tests/test_conciliacion_y_pendientes.py`). Desde esta fase, los datos de prueba ponen fondos en la caja antes de
desembolsar o gastar (ayudante `fondear` de `conftest.py`), porque ninguna salida puede dejarla en negativo.

| Escenario | Prueba |
|---|---|
| El balance cuadra y cada línea coincide con su módulo y con el reporte 14 | `test_balance_cuadra_y_coincide_con_cada_modulo` |
| La reserva de una distribución aparece en el patrimonio | `test_reserva_se_muestra_en_el_patrimonio` |
| La utilidad del estado de resultados es la misma que reparte la distribución; el saldo inicial no es ingreso | `test_estado_de_resultados_es_la_utilidad_que_se_reparte` |
| Saldo inicial + movimientos = saldo final del patrimonio, columna por columna | `test_cambios_en_el_patrimonio_cuadran_con_el_balance` |
| Flujo de efectivo igual al libro de caja, sin transferencias internas | `test_flujo_clasificado_cuadra_con_el_libro_de_caja` |
| Distribuir el ejercicio anterior no toca el ejercicio en curso | `test_resultados_de_ejercicios_anteriores` |
| Comparativos con variación | `test_balance_comparativo`, `test_resultados_comparativo_agrega_variacion` |
| Caja por cuenta y diaria igual a los saldos de caja | `test_caja_por_cuenta_y_diaria` |
| Clasificación por días de atraso e índice de morosidad | `test_antiguedad_de_la_cartera` |
| Pantalla, PDF y Excel de todos los reportes; paquete de 5 hojas | `test_reportes_en_pantalla_pdf_y_excel`, `test_paquete_de_estados_financieros` |
| Permisos | `test_permisos_estados_financieros` |

## 6. Limitaciones

- Es un balance de **base de efectivo**: no reconoce intereses devengados ni provisiones para préstamos incobrables.
  Si CAUNE necesita estados con base de devengo (por ejemplo, para una auditoría externa), hay que decidir cómo
  provisionar la cartera morosa.
- La antigüedad de la cartera y las cuentas de orden se calculan **a hoy**. El cálculo de la mora a una fecha pasada
  usa los pagos registrados hasta hoy, por eso no se ofrece con otra fecha.
- El ejercicio es el año calendario y no se puede configurar.

## 7. Pendientes de fases anteriores resueltos (26/10/2026)

| Pendiente | Resultado |
|---|---|
| Pruebas contra **PostgreSQL 16** | ✅ Toda la batería pasa en PostgreSQL 16 (contenedor `postgres:16`). Se encontró y corrigió un error que SQLite no detecta: anular un movimiento de caja fallaba en PostgreSQL (`FOR UPDATE cannot be applied to the nullable side of an outer join`). Ahora el bloqueo es solo de la fila del movimiento (`select_for_update(of=("self",))`). |
| **Respaldos y restauración** | ✅ Ejecutados con los mismos scripts de `docker-compose` sobre una base con datos ficticios. Se encontró que los scripts no corrían si el proyecto se clona en Windows (fin de línea CRLF: `set: Illegal option -`); se agregó `.gitattributes` para que `*.sh`, `Dockerfile` y `docker-compose.yml` siempre usen LF. `restaurar.sh` ahora compara 10 conteos y totales de la base restaurada con la base en uso y **termina con error si no coinciden**. La base restaurada dio el mismo balance general (cuadre L 0.00). |
| Retiros, desembolsos y gastos de actividades **no verificaban el saldo de la caja** | ✅ Ninguna salida de ningún módulo puede dejar una caja o cuenta en negativo en ninguna fecha. Tampoco se puede anular una entrada (aportación, depósito, pago de préstamo, ingreso de actividad) si ese dinero ya se usó. Se respeta el parámetro `caja.permitir_saldo_negativo`. |
| **Conciliación bancaria** | ✅ Caja y bancos → Conciliación bancaria. Ver sección 8. |
| El **estado de cuenta del afiliado** no mostraba préstamos ni ganancias | ✅ En pantalla y PDF: cada préstamo con el capital, los intereses y la mora pagados en el período, el saldo de capital al corte y el total por pagar hoy; y las ganancias de cada distribución con su forma de entrega. |
| Pantalla para **editar prestatarios externos** | ✅ Detalle del préstamo → «Datos del prestatario». Exige motivo, impide repetir identidades (también las de afiliados) y queda en auditoría. |

Para repetir las pruebas en PostgreSQL:

```bash
docker run -d --name caune-pg-pruebas -e POSTGRES_USER=caune -e POSTGRES_PASSWORD=pruebas-locales -e POSTGRES_DB=caune -p 127.0.0.1:55432:5432 postgres:16
TEST_DATABASE_URL=postgres://caune:pruebas-locales@127.0.0.1:55432/caune python -m pytest
```

## 8. Conciliación bancaria

1. **Nueva conciliación**: cuenta bancaria, fecha de corte del estado del banco y saldo que indica el banco.
2. El sistema lista las operaciones del libro de esa cuenta hasta la fecha de corte que no se conciliaron antes.
   Se marcan las que aparecen en el estado del banco.
3. Las no marcadas son **partidas en tránsito**: saldo del banco + entradas en tránsito − salidas en tránsito =
   saldo del banco ajustado. Debe ser igual al saldo de los libros.
4. Solo se **cierra** con diferencia cero. Si el banco registró algo que no está en los libros (comisiones,
   intereses), se registra primero en Caja como egreso o ingreso de esa cuenta.
5. La siguiente conciliación de la cuenta solo muestra lo que quedó pendiente. Una cerrada no se modifica: se anula
   con motivo, solo la última de cada cuenta. Hay una sola en proceso por cuenta.

PDF con el resumen, las partidas en tránsito y espacio para firmas. Permisos: Tesorero y Administrador, todo;
Presidente, consulta; Contador o supervisor, consulta y anulación.

## 9. Lo que todavía falta

| Pendiente | Impacto |
|---|---|
| **Condonación de mora** (decisión M3) | Bajo, hasta que CAUNE decida si se permite y quién la autoriza |
| Decisiones pendientes de CAUNE: D2, D4, D5, D6, D7, M1, M2 y si los depósitos generan ganancias | Se mantienen como parámetros configurables |
| Préstamo 22026003 (demostración) sin afiliado responsable | Solo datos de demostración; ya se puede asignar desde el detalle |
| Excel del estado de cuenta del afiliado | Solo incluye los movimientos; los préstamos y las ganancias están en pantalla y PDF |
| Una operación ya conciliada todavía puede anularse | Bajo: dejaría de aparecer en esa conciliación; conviene revisar antes de anular |
| Probar la aplicación completa con `docker compose up` y HTTPS en el servidor real | Alto antes de producción: se probaron PostgreSQL y los respaldos, no el despliegue completo |

## 10. Documentos impresos con membrete (26/10/2026)

Todo lo que se imprime lleva el membrete de CAUNE: sello con aro dorado, nombre oficial, siglas y año de
fundación, y los datos de **Configuración → Parámetros** (RTN, dirección, teléfono y correo, si están llenos), con la
línea marino y el filete dorado del sistema visual.

| Documento | Cómo sale |
|---|---|
| Recibos y comprobantes | Una hoja carta con **original y copia** y línea de corte. Recuadro con el número y la fecha, monto destacado con el valor en letras, firmas con el sello (solo si la operación está confirmada) y aviso de **ANULADO** con fecha, usuario y motivo. |
| Reportes, estados financieros, cuadro de amortización, estado de cuenta, conciliación | Membrete repetido en cada página, título y subtítulo del documento, indicadores destacados, filas alternadas, columnas con ancho según el contenido y pie con datos de la cooperativa, usuario, fecha y «Página x de y». Firmas donde corresponde: estados financieros (tesorero, presidente, contador), cuadro (prestatario y tesorería), estado de cuenta (tesorería y afiliado), conciliación (elaboró y revisó). |
| Pantallas con el botón «Imprimir» | Al imprimir desde el navegador aparece un membrete con la fecha y el usuario, el título de la pantalla como título del documento y un pie en cada hoja. Se ocultan el menú, los filtros y los botones. |
| Excel | Fila 1 con el membrete; al imprimir: hoja carta ajustada al ancho, encabezados de columna repetidos, nombre de la cooperativa en el encabezado y «Página x de y» en el pie. |

Comprobantes nuevos:

| Comprobante | Dónde |
|---|---|
| Ingreso, egreso o transferencia de caja | Detalle del movimiento de caja → **Comprobante PDF** |
| Ingreso o gasto de una actividad | Detalle de la actividad → número del registro |
| Desembolso de préstamo (con lo que suma el cuadro aprobado) | Detalle del préstamo → **Comprobante de desembolso** |
| Pago o capitalización de ganancias | Detalle de la distribución → número de la entrega |

El recibo de un pago de préstamo muestra el saldo de capital **después de ese pago**, aunque se reimprima meses
después (antes mostraba el saldo de hoy).

## 11. Liquidación y baja de afiliados (28/10/2026)

**Dónde:** ficha del afiliado → **Liquidar y dar de baja**. Lista en Afiliados → **Liquidaciones**.

| Paso | Quién | Qué pasa |
|---|---|---|
| 1. Calcular | Tesorero o Administrador | Se muestra el finiquito a hoy y se guarda **por aprobar** con el motivo del retiro. |
| 2. Aprobar y ejecutar | **Otra persona** (parámetro `afiliados.liquidacion_requiere_otro_usuario`) | Con fecha de hoy y desde la caja o cuenta elegida: paga sus préstamos con sus haberes, le entrega las ganancias aprobadas pendientes, le devuelve depósitos (RDEP) y aportaciones (RAPO) y lo pasa a **inactivo**. Todo o nada. |
| 3. Comprobante | — | PDF con original y copia, firmas y sello. |
| Anular | Contador o supervisor, Tesorero o Administrador | Anula todas sus operaciones y reactiva al afiliado con sus saldos. |

**Cálculo:** neto a entregar = aportaciones + depósitos + ganancias aprobadas por entregar − (capital + intereses del cuadro + mora de sus préstamos vigentes). Solo sale de la caja el neto: el pago del préstamo se compensa con sus haberes.

**No se puede liquidar si:** sus deudas superan sus haberes (debe pagar la diferencia); tiene préstamos propios aprobados sin desembolsar; o la caja no tiene el efectivo. Avalar préstamos de terceros o que haya una distribución en borrador solo generan avisos. Si los saldos cambian entre el cálculo y la aprobación, o se aprueba otro día, hay que recalcular.

La devolución de aportaciones (tipo RAPO) solo la registra la liquidación, aunque `movimientos.permitir_retiro_aportaciones` esté desactivado, y sus operaciones no se anulan por separado.

### Decisiones de CAUNE sobre el retiro (28/10/2026)

| Código | Decisión | Implementación |
|---|---|---|
| L1 | Se devuelve todo | 100 % de aportaciones y depósitos, más las ganancias aprobadas por entregar. |
| L2 | Si tiene préstamos pendientes, se le resta ese monto | Se resta el total pendiente de cada préstamo (capital, intereses del cuadro y mora) y el préstamo queda cancelado. |
| L2b | Préstamos de terceros que avala: se decide en cada caso | Opción «Descontar los préstamos de terceros que avala» al calcular (se puede cambiar al recalcular). Si se marca, se le resta lo que deben y esos préstamos quedan cancelados; si no, siguen vigentes y el sistema avisa que hay que asignarles otro responsable. |
| L3 | Solo las distribuciones aprobadas | Una distribución en borrador no se incluye; solo se avisa. |
| L4 | El plazo es inmediato | El dinero se entrega al aprobar y ejecutar la liquidación. |
