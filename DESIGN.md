---
name: CAUNE · Caja de Ahorro Unión y Esfuerzo
description: Sistema administrativo y financiero de una caja de ahorro familiar, firmado por su sello oficial.
colors:
  marino-950: "#0b1a33"
  marino-900: "#13284b"
  marino-800: "#1b3561"
  marino-700: "#24467d"
  marino-100: "#e6ecf6"
  marino-50: "#f1f4fa"
  union: "#1f6fd1"
  union-oscuro: "#1758a8"
  union-50: "#e8f1fc"
  esfuerzo: "#e8800f"
  esfuerzo-oscuro: "#b45f05"
  esfuerzo-50: "#fdf1e3"
  oro: "#c9a13b"
  oro-claro: "#e9d398"
  tinta: "#15233d"
  tinta-2: "#45526b"
  tinta-3: "#6b778d"
  borde: "#dbe2ec"
  borde-fuerte: "#c3cddd"
  fondo: "#f3f5f9"
  blanco: "#ffffff"
  rojo: "#b42318"
  rojo-50: "#fdecea"
  verde: "#1d7a4e"
  verde-50: "#e6f4ec"
typography:
  display:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", system-ui, -apple-system, Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.8rem"
    fontWeight: 750
    lineHeight: 1.2
    fontFeature: "\"tnum\" 1"
  headline:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", system-ui, -apple-system, Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.55rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.015em"
    fontFeature: "\"tnum\" 1"
  title:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", system-ui, -apple-system, Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.12rem"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  body:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", system-ui, -apple-system, Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", system-ui, -apple-system, Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 600
    lineHeight: 1.4
  table:
    fontFamily: "\"Segoe UI Variable Text\", \"Segoe UI\", system-ui, -apple-system, Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "\"tnum\" 1"
rounded:
  sm: "8px"
  nav: "10px"
  md: "12px"
  pill: "999px"
  sello: "50%"
spacing:
  xs: "0.5rem"
  sm: "0.75rem"
  md: "1rem"
  lg: "1.35rem"
  xl: "1.75rem"
  rail: "264px"
components:
  button-primario:
    backgroundColor: "{colors.union}"
    textColor: "{colors.blanco}"
    rounded: "{rounded.sm}"
    padding: "0.52rem 0.95rem"
    height: "2.4rem"
  button-primario-hover:
    backgroundColor: "{colors.union-oscuro}"
  button-secundario:
    backgroundColor: "{colors.blanco}"
    textColor: "{colors.marino-900}"
    rounded: "{rounded.sm}"
    padding: "0.52rem 0.95rem"
    height: "2.4rem"
  button-secundario-hover:
    backgroundColor: "{colors.marino-50}"
  button-peligro:
    backgroundColor: "{colors.rojo}"
    textColor: "{colors.blanco}"
    rounded: "{rounded.sm}"
    padding: "0.52rem 0.95rem"
  card:
    backgroundColor: "{colors.blanco}"
    rounded: "{rounded.md}"
    padding: "1.35rem"
  kpi:
    backgroundColor: "{colors.blanco}"
    textColor: "{colors.marino-900}"
    typography: "{typography.headline}"
    rounded: "{rounded.md}"
    padding: "1.05rem 1.15rem 1rem"
  kpi-destacado:
    backgroundColor: "{colors.marino-900}"
    textColor: "{colors.blanco}"
    rounded: "{rounded.md}"
  input:
    backgroundColor: "{colors.blanco}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.sm}"
    padding: "0.52rem 0.7rem"
    height: "2.5rem"
  badge-ok:
    backgroundColor: "{colors.marino-50}"
    textColor: "{colors.marino-800}"
    rounded: "{rounded.pill}"
    padding: "0.16rem 0.58rem"
  nav-item:
    textColor: "{colors.marino-100}"
    rounded: "{rounded.nav}"
    padding: "0.58rem 0.75rem"
  nav-item-activo:
    backgroundColor: "{colors.marino-700}"
    textColor: "{colors.blanco}"
  tabla-encabezado:
    backgroundColor: "{colors.marino-50}"
    textColor: "{colors.marino-800}"
    padding: "0.62rem 0.7rem"
  recibo:
    backgroundColor: "{colors.blanco}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.md}"
    padding: "2rem 2.2rem"
    width: "760px"
---

# Design System: CAUNE · Caja de Ahorro Unión y Esfuerzo

## Overview

**Creative North Star: "El Sello Institucional"**

El sistema se firma con el sello oficial de CAUNE: un disco circular con la familia dibujada y un aro dorado. Ese sello no es decoración; es la marca de constancia. Aparece en el riel lateral (72px sobre disco blanco con aro dorado), en el ingreso (132px, montado sobre la tarjeta), en el encabezado de toda constancia (56px) y, girado como un timbre de goma, en la línea de firmas de cada recibo confirmado (104px). Quien abre el sistema reconoce su caja de ahorro de inmediato, y quien recibe un recibo ve que la operación quedó sellada.

El mundo es el de una caja de ahorro en papel trasladada a pantalla: riel azul marino con filete dorado, superficie clara ligeramente azulada, tarjetas blancas con bordes finos, cifras tabulares alineadas a la derecha. La densidad es de oficina: tablas compactas, formularios en rejilla, una sola acción primaria por bloque. El color tiene significado contable: azul Unión para actuar y para depósitos, naranja Esfuerzo para aportaciones, dorado sólo como aro, filete y foco.

Se rechaza explícitamente el panel SaaS genérico gris con un acento verde. Las correcciones se muestran como anulación visible (tachado, timbre «ANULADO»), nunca como desaparición.

**Key Characteristics:**
- El sello circular con aro dorado identifica cada constancia oficial.
- Riel lateral azul marino fijo (264px) con filete dorado de 1px.
- Codificación de clase: naranja = aportación, azul = depósito, en bandas de KPI y marcadores de tabla.
- Cifras siempre tabulares y alineadas a la derecha.
- Iconos SVG de trazo (1.75px, extremos redondeados) heredando `currentColor`.
- Profundidad baja y difusa; el dorado es línea, nunca superficie.

## Colors

Una paleta institucional derivada del sello: marino profundo como estructura, dos acentos con significado contable y un dorado reservado para aros y filetes.

### Primary
- **Marino del Sello** (marino-900): el riel lateral, los títulos, las cifras de KPI, la línea doble del encabezado del recibo y la tarjeta KPI destacada. Es el color de la institución. Su escala (marino-950 a marino-50) cubre el telón del menú móvil (950), texto de encabezados de tabla y etiquetas (800), el ítem activo del riel y el borde de hover (700), y los fondos tenues de encabezados de tabla, filtros, notas y montos en letras (100, 50).

### Secondary
- **Azul Unión** (union): la acción. Botón primario, enlaces, foco de campos, casillas, banda superior del KPI de depósitos y marcador de tipo «depósito». Su versión oscura (union-oscuro) es el hover y el texto de avisos informativos; union-50 es el fondo de badges y alertas informativas.

### Tertiary
- **Naranja Esfuerzo** (esfuerzo): las aportaciones. Banda superior de 3px del KPI de aportaciones y marcador cuadrado de tipo «aportación». esfuerzo-oscuro marca el asterisco de campo obligatorio y el texto de advertencias; esfuerzo-50 es el fondo de advertencias.
- **Dorado del Aro** (oro): el aro del sello (anillo de 2px alrededor de cada logo), el filete de 1px del riel, el segundo filete bajo el encabezado del recibo, el anillo y el punto del badge «Confirmado», y el anillo de foco (al 45%). oro-claro es el filete bajo los encabezados con filete, el icono del ítem activo, el anillo interior del ítem activo y la selección de texto.

### Neutral
- **Tinta** (tinta): texto de cuerpo. tinta-2 para texto secundario (etiquetas de KPI, usuario, paginación); tinta-3 para texto atenuado, notas de ayuda y filas anuladas.
- **Borde** (borde): bordes de tarjeta, separadores de filas y de listas. borde-fuerte para campos, botones secundarios, la línea bajo el encabezado de tabla y el pulgar del scroll.
- **Fondo Azulado** (fondo): el lienzo de la aplicación, detrás de las tarjetas blancas (blanco).
- **Estados** (rojo, rojo-50, verde, verde-50): rojo para errores, anulaciones, botón de peligro y badge «Anulado»; verde sólo para alertas de éxito.

### Named Rules
**The Aro Rule.** El dorado es línea, anillo o punto: aros del sello, filetes de 1px, el punto del badge confirmado y el foco. Nunca es fondo de superficie, color de texto ni relleno de botón.

**The Clase Contable Rule.** Naranja significa aportación y azul significa depósito, siempre. Un nuevo tipo de movimiento hereda el color de su clase; no se inventa un tercer acento.

**The Una Acción Rule.** Azul Unión relleno aparece una vez por bloque: la acción primaria. Las demás acciones son botones blancos con borde.

## Typography

**Display Font:** pila de sistema («Segoe UI Variable Text», «Segoe UI», system-ui, con Roboto, «Helvetica Neue», Arial)
**Body Font:** la misma pila
**Label/Mono Font:** ui-monospace, «Cascadia Mono», Consolas para fragmentos de código
**PDF:** Helvetica (motor de PDF)

**Character:** Provisional. La interfaz usa hoy la fuente de la plataforma y los PDF usan Helvetica; una fuente propia autoalojada está pendiente del permiso del usuario para descargar archivos de fuente. La jerarquía se construye con peso (550 a 800) y cifras tabulares más que con tamaño. Cuando la fuente propia llegue, sustituye la familia en todos los roles sin cambiar la escala.

### Hierarchy
- **Display** (750, 1.8rem, 1.2): el monto del recibo, alineado a la derecha, en marino.
- **Headline** (700, 1.55rem, -0.015em): el valor de cada KPI del panel; 1.2rem en pantallas de 960px o menos.
- **Title** (650, 1.12rem, 1.2, -0.01em): encabezados de tarjeta (h2); el título de la barra superior usa 1.15rem/650 y h3 1rem/650. Los títulos equilibran líneas (`text-wrap: balance`).
- **Body** (400, 15px raíz, 1.5): texto general; ítems del riel a 0.93rem/500; tablas a 0.9rem.
- **Label** (600, 0.85rem): etiquetas de campo en marino-800. Términos de datos (dt) a 0.78rem/550 en tinta-3; encabezados de tabla a 0.78rem/650; badges a 0.74rem/650.
- **Grupo del riel** (650, 0.7rem, 0.1em, mayúsculas): sólo los separadores de sección dentro del riel (Operación, Consulta, Administración). No se usa fuera de la navegación.

### Named Rules
**The Cifra Tabular Rule.** Todo monto, número de operación, fecha en tabla y valor de KPI usa `font-variant-numeric: tabular-nums`; los montos van alineados a la derecha y sin corte de línea.

## Layout

Un riel lateral fijo de 264px y una columna principal con barra superior pegajosa (mínimo 60px, blanco al 94% con desenfoque). El contenido tiene relleno de 1.75rem y un ancho máximo de 1440px. El ritmo vertical entre tarjetas y KPI es 1.35rem; los espacios internos se mueven entre 0.5rem, 0.75rem y 1rem.

Las rejillas son de autoajuste: KPI con mínimo 210px, formularios 240px, datos de detalle 200px, filtros 150px, tarjetas de configuración 250px. El detalle usa dos columnas 2:1 que se apilan a 1100px o menos. El recibo se centra con ancho máximo de 760px.

A 960px o menos el riel se oculta fuera de pantalla y se abre con el botón de menú sobre un telón marino-950 al 45%; el contenido baja a 1rem de relleno y los KPI pasan a dos columnas. A 600px o menos las firmas del recibo se apilan y el sello confirmado se centra. A 420px o menos el KPI destacado ocupa la fila completa y, si queda una tarjeta huérfana al final, también se extiende. Esta regla de huérfanos está implementada pero sin verificar en captura a 375px (sólo se capturó 500px).

Las tablas se desplazan horizontalmente dentro de su tarjeta sin romper el relleno. En impresión desaparecen riel, barra, alertas y todo lo marcado como no imprimible; tarjetas y recibo pierden sombra y borde.

## Elevation & Depth

Profundidad baja y difusa. Sobre superficies claras la sombra se tiñe de marino (rgba de #13284b); sólo sobre el fondo marino (logo del riel, tarjeta y sello del ingreso) la caída es negra translúcida. Las tarjetas descansan en una sombra ambiental leve; la elevación alta se reserva para el KPI destacado, el riel abierto en móvil y el hover de las tarjetas de configuración. Las bandas de clase de los KPI se dibujan como sombra interior de 3px, no como borde. Los aros del sello son anillos de sombra sin desenfoque.

### Shadow Vocabulary
- **Reposo** (`box-shadow: 0 1px 2px rgba(19, 40, 75, .05), 0 4px 14px -6px rgba(19, 40, 75, .12)`): tarjetas, KPI, recibo.
- **Alta** (`box-shadow: 0 2px 4px rgba(19, 40, 75, .06), 0 12px 32px -12px rgba(19, 40, 75, .28)`): KPI destacado, riel móvil abierto, hover de tarjeta enlazada.
- **Aro** (`box-shadow: 0 0 0 2px #c9a13b`): todo sello circular.
- **Foco** (`box-shadow: 0 0 0 3px rgba(201, 161, 59, .45)`): foco visible global.

### Named Rules
**The Aro Sin Desenfoque Rule.** El anillo del sello y el foco son sombras de 0 desenfoque; la única sombra difusa alrededor de un sello es la caída suave bajo el logo del riel y del ingreso.

## Shapes

Esquinas suaves y moderadas: 12px en tarjetas, KPI y recibo; 8px en botones, campos, alertas, filtros y notas; 10px en ítems del riel; píldora completa en badges. El círculo es la forma de la marca: sello, avatar y punto del badge confirmado. El marcador de clase en tablas es un cuadrado de 0.6rem con 2px de radio, deliberadamente distinto del círculo del sello. El timbre «ANULADO» es un rectángulo de 14px de radio con borde rojo translúcido de 6px, girado -16°.

## Components

### Buttons
Sobrios y firmes; peso 600, icono de 1rem a la izquierda.
- **Shape:** esquinas suaves (8px), alto mínimo 2.4rem.
- **Primario:** relleno azul Unión, texto blanco, sombra teñida de azul; hover a union-oscuro.
- **Secundario (por defecto):** blanco con borde borde-fuerte y texto marino; hover a marino-50 con borde marino-700.
- **Peligro:** relleno rojo; hover más oscuro. Sólo para anular.
- **Pequeño:** 0.82rem, alto 2rem. **Enlace:** sin borde ni fondo, texto tinta-2, subrayado al hover.
- **Estados:** al presionar baja 1px; deshabilitado al 55% con cursor de progreso; foco con el anillo dorado.

### Chips (badges)
- **Style:** píldora, 0.74rem/650. «Confirmado» lleva fondo marino-50, anillo interior dorado y punto dorado delante: es el pequeño sello de la fila. Anulado en rojo-50/rojo, informativo en union-50, aviso en esfuerzo-50, inactivo en gris neutro.

### Cards / Containers
- **Corner Style:** 12px.
- **Background:** blanco sobre el fondo azulado.
- **Shadow Strategy:** Reposo (ver Elevation & Depth).
- **Border:** 1px borde.
- **Internal Padding:** 1.35rem (1.1rem en móvil). El encabezado de tarjeta alinea título y acciones; la variante con filete añade una línea oro-claro de 1px debajo.

### KPI
- Tarjeta compacta con etiqueta (0.82rem/550), valor tabular (Headline) y detalle (0.8rem, tinta-3). Banda superior de 3px naranja para aportaciones y azul para depósitos. El destacado invierte a fondo marino-900 con texto blanco y sombra alta.

### Inputs / Fields
- **Style:** borde 1px borde-fuerte, fondo blanco, 8px, alto mínimo 2.5rem; placeholder #75819a. Etiqueta encima en marino-800/600; ayuda en tinta-3.
- **Focus:** borde azul Unión y halo azul al 18% de 3px.
- **Error / Disabled:** borde rojo y fondo #fffafa; errores en rojo 0.82rem bajo el campo; resumen de errores en caja rojo-50. Obligatorio marcado con asterisco esfuerzo-oscuro.

### Navigation
- **Riel:** marino-900 con filete dorado a la derecha. Ítems a 0.93rem/500 en azul pálido con icono atenuado; hover a blanco sobre blanco al 6%; activo sobre marino-700 con anillo interior oro-claro y el icono en oro-claro. Separadores de grupo en mayúsculas pequeñas. Pie del riel con siglas y fase. En móvil se desliza desde la izquierda (0.25s, curva de salida suave).

### Tablas
- Encabezado sobre marino-50 en marino-800 con esquinas superiores de 8px; filas separadas por borde de 1px; hover de fila muy tenue; pie de totales en negrita sobre marino-50. Las filas anuladas se tachan con línea roja translúcida y se atenúan, excepto la celda de estado. Marcador de clase (cuadrado naranja o azul) delante del tipo.

### Sello (signature)
- **Encabezado sellado:** sello de 56px con aro dorado junto al nombre de la caja; identifica recibos, detalle de operación y estado de cuenta.
- **Sello confirmado:** en la línea de firmas del recibo, el sello de 104px girado -8° al 90% de opacidad, entre «Entregó» y «Recibió».
- **Timbre anulado:** palabra «ANULADO» en rojo translúcido girada -16° sobre el recibo.
- **Ingreso:** sello de 132px montado sobre la tarjeta, con anillo blanco de 4px y aro dorado de 2px, sobre fondo marino con un gran aro dorado concéntrico tenue.

### Recibo
- Hoja blanca de 760px máximo; encabezado con línea marino de 2px y filete dorado de 1px a 6px debajo; número de recibo tabular a la derecha; monto en Display; monto en letras sobre marino-50; firmas en tres columnas.

## Do's and Don'ts

### Do:
- **Do** poner el sello con aro dorado de 2px en el encabezado de toda constancia nueva (recibos, estados de cuenta, operaciones confirmadas).
- **Do** usar naranja Esfuerzo para aportaciones y azul Unión para depósitos en bandas de KPI y marcadores de tabla.
- **Do** alinear a la derecha y en cifras tabulares todo monto, con formato L 1,250.00.
- **Do** dibujar iconos como símbolos SVG de trazo de 1.75px con extremos redondeados, heredando el color del texto.
- **Do** mostrar las anulaciones de forma visible: fila tachada en tablas, timbre «ANULADO» en el recibo, badge rojo.
- **Do** usar el anillo dorado de foco (3px, 45%) en todo elemento interactivo y respetar `prefers-reduced-motion`.

### Don't:
- **Don't** construir el panel SaaS genérico gris con acento verde.
- **Don't** usar el dorado como fondo de superficie, texto o relleno de botón.
- **Don't** introducir un tercer color de acento para tipos de movimiento.
- **Don't** usar sombras duras desplazadas sin desenfoque; sobre superficies claras la sombra es difusa y teñida de marino.
- **Don't** usar etiquetas en mayúsculas pequeñas fuera de los separadores de grupo del riel.
- **Don't** recolorear, deformar ni recortar el logo oficial; se muestra completo dentro de su disco blanco (el único giro admitido es el del sello confirmado, -8°).
