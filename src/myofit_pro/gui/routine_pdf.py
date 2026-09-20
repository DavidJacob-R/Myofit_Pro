"""
Rutina en PDF, para entregársela al cliente.

Mismo enfoque que `progress_pdf.py`: `QPdfWriter` y `QTextDocument`, que
ya vienen con PySide6, y tinta oscura sobre blanco porque esto se
imprime.

El PDF lleva dos partes: la rutina que el cliente sigue día por día, y
la comparación de la medición anterior con la actual, que es lo que el
entrenador mira para decidir si algo hay que cambiar.
"""

from __future__ import annotations

import datetime as dt
import html

from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

_TINTA = "#1A1A1A"
_SUAVE = "#666666"
_BUENO = "#1B7F4B"
_OJO = "#B36B00"
_LINEA = "#DDDDDD"


def export_routine_pdf(
    path: str, trainer, client, routine, bloques, fuentes,
    split=None, comparacion=None,
) -> str:
    """
    Escribe la rutina en `path`.

    `bloques` es {día: [(nombre del ejercicio, músculo, RoutineExercise)]}
    y `fuentes` la lista de (fecha, músculo) de las evaluaciones que la
    originaron. Los dos los arma la pantalla, que es la que ya resolvió
    los nombres.
    """
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(300)
    writer.setTitle(f"Rutina de {client.full_name}")
    writer.setCreator("MyoFit Pro")

    document = QTextDocument()
    document.setDefaultStyleSheet(_stylesheet())
    document.setHtml(
        _build_html(trainer, client, routine, bloques, fuentes, split, comparacion)
    )
    # El ancho de página se fija en PUNTOS, no en píxeles del
    # dispositivo. `paintRectPixels(300)` devuelve unos 2245 px, y
    # QTextDocument interpreta ese número con su propia resolución
    # (~96 ppp), así que maquetaba una página enormemente ancha y
    # `print_` la encajaba entera en la hoja: todo salía diminuto en la
    # esquina superior izquierda. En puntos, las dos partes hablan la
    # misma unidad y el texto sale al tamaño que dice la hoja de estilo.
    document.setPageSize(
        writer.pageLayout().paintRect(QPageLayout.Unit.Point).size()
    )
    document.print_(writer)
    return path


def _stylesheet() -> str:
    return f"""
        body {{ color: {_TINTA}; font-size: 10pt; }}
        h1 {{ font-size: 19pt; margin-bottom: 2px; }}
        h2 {{ font-size: 12pt; margin-top: 18px; margin-bottom: 6px; }}
        h3 {{ font-size: 10pt; margin-top: 12px; margin-bottom: 2px; }}
        .sub {{ color: {_SUAVE}; font-size: 9pt; }}
        .destacado {{ font-size: 11pt; margin-top: 10px; margin-bottom: 8px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; font-size: 8pt; color: {_SUAVE};
              border-bottom: 1px solid {_TINTA}; padding: 4px 6px; }}
        td {{ padding: 5px 6px; border-bottom: 1px solid {_LINEA}; font-size: 9pt; }}
        .num {{ text-align: right; }}
        .nota {{ color: {_SUAVE}; font-size: 8pt; }}
    """


def _build_html(trainer, client, routine, bloques, fuentes, split=None, comparacion=None) -> str:
    return "".join([
        "<body>",
        _encabezado(trainer, client, routine, bloques),
        _dias(bloques, split),
        _comparativa(comparacion, fuentes),
        "<p class='nota'>Generado con MyoFit Pro.</p>",
        "</body>",
    ])


def _encabezado(trainer, client, routine, bloques) -> str:
    distintos = {r.exercise_id for items in bloques.values() for _, _, r in items}
    series = sum(r.sets for items in bloques.values() for _, _, r in items)

    datos = []
    if routine.goal:
        datos.append(f"Objetivo: {routine.goal}")
    if routine.experience_level:
        datos.append(routine.experience_level)
    datos.append(f"{len(bloques)} días por semana")
    datos.append(f"{len(distintos)} ejercicios")
    datos.append(f"{series} series por semana")

    return (
        f"<h1>{_e(client.full_name)}</h1>"
        f"<p class='sub'>{_e(routine.name)}</p>"
        f"<p class='sub'>{' &nbsp;·&nbsp; '.join(_e(d) for d in datos)}"
        f"<br/>Entrenador: {_e(trainer.full_name)} &nbsp;·&nbsp; "
        f"generada el {_fecha(routine.created_at)}</p><hr/>"
    )


def _dias(bloques, split=None) -> str:
    partes = ["<h2>La rutina</h2>"]
    for dia in sorted(bloques):
        items = bloques[dia]
        musculos = []
        for _, muscle, _ in items:
            if muscle not in musculos:
                musculos.append(muscle)

        plantilla = split[dia - 1] if split and 1 <= dia <= len(split) else None
        titulo = plantilla.weekday if plantilla else f"Día {dia}"
        if plantilla:
            titulo += f" &nbsp;·&nbsp; {plantilla.label}"

        filas = []
        for nombre, _, r in items:
            reps = f"{r.reps}-{r.reps_max}" if r.reps_max and r.reps_max != r.reps else str(r.reps)
            descanso = _descanso(r.rest_sec)
            carga = f"{r.load_pct_min}-{r.load_pct_max}% PR" if r.load_pct_min else "—"
            rir = "al fallo" if r.rir == 0 else (str(r.rir) if r.rir is not None else "—")
            marca = (
                " <span class='nota'>(variación)</span>"
                if getattr(r, "is_rotation", False) else ""
            )
            filas.append(
                f"<tr><td><b>{_e(nombre)}</b>{marca}</td>"
                f"<td class='num'>{r.sets} × {reps}</td>"
                f"<td class='num'>{descanso}</td>"
                f"<td class='num'>{carga}</td>"
                f"<td class='num'>{rir}</td></tr>"
            )

        partes.append(
            f"<h3>{titulo}</h3>"
            f"<p class='nota'>{_e('  ·  '.join(musculos))}</p>"
            "<table>"
            "<tr><th>EJERCICIO</th><th class='num'>SERIES × REPS</th>"
            "<th class='num'>DESCANSO</th><th class='num'>INTENSIDAD</th>"
            "<th class='num'>REPS EN RESERVA</th></tr>"
            + "".join(filas)
            + "</table>"
        )

    if split:
        from myofit_pro.routine_engine import rest_days

        libres = rest_days(split)
        if libres:
            partes.append(
                f"<p class='nota'>Descanso: {_e(', '.join(libres))}.</p>"
            )
    return "".join(partes)


def _comparativa(comparacion, fuentes) -> str:
    """
    La medición anterior contra la actual, sin veredictos.

    Deliberadamente escueta: son dos números por ejercicio para que el
    entrenador saque su propia conclusión. La lectura con criterio vive
    en el informe de progreso, que es otro documento.
    """
    if not comparacion:
        return ""

    filas = []
    for nombre, muscle, antes, ahora in comparacion:
        if antes is None:
            valores, delta, color = "—", f"{ahora:.0f}%", _SUAVE
        else:
            diferencia = ahora - antes
            valores = f"{antes:.0f}%  →  {ahora:.0f}%"
            delta = f"{diferencia:+.0f}"
            color = _BUENO if diferencia > 0 else (_OJO if diferencia < 0 else _SUAVE)
        filas.append(
            f"<tr><td><b>{_e(nombre)}</b></td><td>{_e(muscle)}</td>"
            f"<td class='num'>{valores}</td>"
            f"<td class='num' style='color:{color}'><b>{delta}</b></td></tr>"
        )

    encabezado = "<h2>Comparado con la evaluación anterior</h2>"
    if fuentes:
        fechas = sorted({f"{f:%d/%m/%Y}" for f, _ in fuentes})
        encabezado += f"<p class='sub'>Lecturas del {', '.join(fechas)}</p>"

    return (
        encabezado
        + "<table><tr><th>EJERCICIO</th><th>MÚSCULO</th>"
        "<th class='num'>ANTES → AHORA</th><th class='num'>CAMBIO</th></tr>"
        + "".join(filas)
        + "</table>"
    )


def _descanso(segundos: int | None) -> str:
    if not segundos:
        return "—"
    if segundos < 120:
        return f"{segundos} s"
    minutos = segundos / 60
    return f"{int(minutos)} min" if minutos == int(minutos) else f"{minutos:.1f} min"


def _e(text) -> str:
    return html.escape(str(text or ""))


def _fecha(when: dt.datetime) -> str:
    return f"{when:%d/%m/%Y}"
