# Design system: manuales técnicos Inter (VP Ingeniería y Operaciones)

Extraído de `Manual_Matriz_Fusiones_y_Auditor.pdf` (14 págs., generado con python-docx → Word 2016).
Valores medidos del PDF (fuentes embebidas, colores RGB del contenido y posiciones de texto).

## Página
| Elemento | Valor |
|---|---|
| Formato | A4 vertical (595 × 842 pt) |
| Márgenes laterales | 72 pt (2,54 cm) |
| Encabezado | Imagen en todas las páginas: recuadro de esquinas redondeadas con borde azul, logo **inter** a la izquierda y "VICE-PRESIDENCIA DE INGENIERÍA / Y OPERACIONES" (sans bold, mayúsculas, alineado a la derecha) |
| Pie | Logo **inter** pequeño + línea horizontal azul fina hasta el margen derecho. Sin número de página |
| Portada | Solo encabezado; título y subtítulo centrados a ~55 % de la altura |

## Color
| Token | Hex | Uso |
|---|---|---|
| `inter-blue` | `#005DAF` (RGB 0, 93, 175) | Títulos, subtítulos, encabezado/pie, fondo de cabecera de tablas |
| `text` | `#000000` | Cuerpo, celdas, bordes de tabla |
| `on-blue` | `#FFFFFF` | Texto de cabecera de tablas |
| `highlight` | amarillo pálido (~`#FFF2CC`) | Filas resaltadas en capturas de atributos (Fig. 3) |
| `code-bg` | gris azulado oscuro (~`#1E2A36`) | Capturas de línea de comandos (texto claro, monospace) |
| `annotation` | rojo (~`#D0021B`) | Recuadros y rótulos de anotación sobre capturas (Fig. 1) |

Un solo color de marca; sin acentos secundarios.

## Tipografía
Familia única: **Cambria** (serif), regular y bold. Sin cursivas.

| Nivel | Tamaño | Peso / color | Alineación |
|---|---|---|---|
| Título portada | 21 pt | Regular, `inter-blue` | Centrado |
| Subtítulo portada | 12,5 pt | Regular, negro | Centrado |
| H1 (sección) | 16 pt | Regular, MAYÚSCULAS, `inter-blue` | Centrado |
| H2 (subsección) | 12,5 pt | Regular, `inter-blue` | Izquierda |
| Cuerpo | 11 pt | Regular, negro; **bold** para nombres de botones, atributos clave y advertencias | Justificado, sangría de 1.ª línea ~1,25 cm |
| Celdas de tabla | 9,5–10 pt | Regular, negro | Izquierda |
| Cabecera de tabla | 10 pt | Regular, blanco sobre `inter-blue` | Centrado |
| Pie de figura | 10 pt | Regular, negro: `Figura N°X Descripción` | Centrado, debajo de la figura |
| Comandos / archivos en línea | ~9 pt | Versalitas/tamaño reducido (p. ej. `FIND`, `<plano>_REVISION.txt`) | En línea |

## Componentes
- **Tabla de referencia**: 3 columnas (p. ej. Atributo · Qué se escribe · Ejemplo, o Mensaje · Qué quiere decir · Cómo se corrige), cabecera azul sólida, bordes negros finos en todas las celdas, sin cebrado. Cada tabla lleva su `Figura N°X`.
- **Captura de consola**: bloque oscuro con barra de título "Command Line", texto monospace claro, primera línea (`Command: ...`) en azul claro.
- **Captura de TXT/Bloc de notas**: barra de título gris clara con el nombre de archivo, cuerpo blanco monospace, borde gris.
- **Tabla Excel**: cabecera gris claro bold sans, celdas sans pequeñas, filas omitidas indicadas con `…`.
- **Nota**: párrafo que empieza con **Nota:** en bold, sin caja ni color.
- **FAQ**: H2 en forma de pregunta + párrafo de respuesta.

## Estructura del documento
Portada → INTRODUCCIÓN → secciones por tema (H1 mayúsculas) con subsecciones (H2) → tablas de errores/avisos → PREGUNTAS FRECUENTES.
Numeración continua de figuras (tablas y capturas comparten la serie `Figura N°`). Cada H1 empieza en página nueva.
