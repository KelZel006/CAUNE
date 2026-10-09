# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
- **Tesorero** (usuario principal): acceso total al sistema. Registra afiliados, aportaciones, depósitos y retiros, emite recibos y estados de cuenta, y administra la configuración.
- **Presidente**: consulta los reportes de importancia (panel financiero, listado de afiliados, estados de cuenta, aportaciones y depósitos). No registra operaciones.
- Otros roles configurables (supervisor, encargados de préstamos y actividades) para fases futuras.
- Los afiliados no usan el sistema directamente en esta versión.

## Product Purpose
Sistema de gestión administrativa y financiera de **CAUNE · Caja de Ahorro Unión y Esfuerzo** (fundada en 2022), una caja de ahorro familiar de Honduras. Centraliza afiliados, aportaciones, depósitos, préstamos, actividades económicas y la distribución de ganancias, de modo que cada movimiento pueda verificarse y cada cálculo justificarse. El éxito es que la directiva opere sin errores financieros y que cada afiliado confíe en sus saldos.

## Positioning
Reemplaza hojas de Airtable sin integridad contable: los saldos se calculan siempre a partir de operaciones inmutables y auditadas. Las correcciones se hacen por anulación con motivo, nunca por edición.

## Operating Context
- Moneda: Lempiras (L 1,250.00). Fechas en DD/MM/AAAA. Zona horaria America/Tegucigalpa. Idioma español.
- Recibos impresos o en PDF, con el monto en letras y espacio para firmas. Reportes en PDF y Excel.
- Se desarrolla por fases. Fase 1: afiliados, aportaciones y depósitos, usuarios, configuración, reportes 1-3. Fase 2: préstamos internos (1 % mensual) y externos (5 % mensual) con cuadro de amortización, pagos y abonos; actividades económicas con resultados; reportes 4-9.

## Capabilities and Constraints
- Django 5.2 + PostgreSQL 16, con plantillas renderizadas en el servidor.
- Permisos verificados en el servidor. Auditoría inmutable.
- Reglas financieras pendientes de aprobación por CAUNE: se mantienen como parámetros configurables (ver docs/FASE1.md).

## Brand Commitments
- Nombre oficial: **Caja de Ahorro Unión y Esfuerzo**. Siglas: **CAUNE**. Año de fundación: 2022.
- Logo oficial: `static/img/logo-caune.webp`. Sello circular con una familia: dos adultos (azul marino y azul / naranja) y un niño al centro, formando un corazón, rodeados por un aro dorado.

## Evidence on Hand
- Logo oficial (archivo indicado arriba). No hay testimonios, cifras públicas ni otros activos de marca; no deben inventarse.

## Product Principles
1. La claridad financiera está por encima de la decoración.
2. Toda cifra debe poder rastrearse hasta las operaciones que la originan.
3. Nada se borra en silencio: se corrige por anulación con motivo y queda en auditoría.
4. Las reglas que no ha aprobado CAUNE se configuran; no se suponen.
