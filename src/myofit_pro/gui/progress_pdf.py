"""
Informe de progreso en PDF.

Usa `QPdfWriter` + `QTextDocument`, que ya vienen con PySide6. No se
agregó ReportLab ni WeasyPrint: son dependencias grandes y con binarios
nativos, y lo que hay que imprimir es una tabla y unos párrafos.

DISEÑO PARA PAPEL, NO PARA PANTALLA
===================================

Va en tinta oscura sobre blanco: la paleta oscura de la app se imprime
fatal y gasta tinta.
"""

from __future__ import annotations

import datetime as dt
import html

from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

from myofit_pro.progress import Verdict, trend_for

# Paleta para papel: tinta oscura sobre blanco, con acentos sobrios que
# siguen distinguiéndose impresos en blanco y negro.
_TINTA = "#1A1A1A"
_SUAVE = "#666666"
_BUENO = "#1B7F4B"
_OJO = "#B36B00"
_MALO = "#B3261E"
_LINEA = "#DDDDDD"

_VERDICT_COLOR: dict[Verdict, str] = {
    Verdict.MAS_FUERTE: _BUENO,
    Verdict.MAS_EFICIENTE: _BUENO,
    Verdict.RECLUTA_MAS: _BUENO,
    Verdict.SIN_CAMBIO: _SUAVE,
    Verdict.MENOS_CARGA: _MALO,
    Verdict.SIN_CARGA: _OJO,
    Verdict.NUEVO: _SUAVE,
}


def export_progress_pdf(path: str, trainer, client, report, sessions) -> str:
    """
    Escribe el informe en `path` y devuelve la ruta.

    `report` es un `progress.ProgressReport` y `sessions` la lista
    completa de evaluaciones del músculo, de la más vieja a la más
    reciente, para poder imprimir la trayectoria.
    """
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(300)
    writer.setTitle(f"Progreso de {client.full_name} — {report.muscle_name}")
    writer.setCreator("MyoFit Pro")

    document = QTextDocument()
    document.setDefaultStyleSheet(_stylesheet())
    document.setHtml(_build_html(trainer, client, report, sessions))
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
        h1 {{ font-size: 19pt; color: {_TINTA}; margin-bottom: 2px; }}
        h2 {{ font-size: 12pt; color: {_TINTA}; margin-top: 18px; margin-bottom: 6px; }}
        .sub {{ color: {_SUAVE}; font-size: 9pt; }}
        .headline {{ font-size: 12pt; margin-top: 10px; margin-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; font-size: 8pt; color: {_SUAVE};
              border-bottom: 1px solid {_TINTA}; padding: 4px 6px; }}
        td {{ padding: 6px; border-bottom: 1px solid {_LINEA}; font-size: 9pt;
              vertical-align: top; }}
        .num {{ text-align: right; }}
        .nota {{ color: {_SUAVE}; font-size: 8pt; }}
    """


def _build_html(trainer, client, report, sessions) -> str:
    partes = [
        "<body>",
        _encabezado(trainer, client, report),
        _resumen(report),
        _tabla(report, sessions),
        _trayectoria(sessions),
        "<p class='nota'>Generado con MyoFit Pro.</p>",
        "</body>",
    ]
    return "".join(p for p in partes if p)


def _encabezado(trainer, client, report) -> str:
    datos = [f"Objetivo: {_e(client.goal)}"]
    if client.age_years:
        datos.append(f"{client.age_years} años")
    if client.weight_kg:
        datos.append(f"{client.weight_kg:.1f} kg")
    if client.experience_level:
        datos.append(_e(client.experience_level))

    periodo = (
        f"{_fecha(report.before.date)} → {_fecha(report.after.date)}"
        if report.before
        else f"Primera evaluación · {_fecha(report.after.date)}"
    )

    return (
        f"<h1>{_e(client.full_name)}</h1>"
        f"<p class='sub'>{' &nbsp;·&nbsp; '.join(_e(d) for d in datos)}</p>"
        f"<p class='sub'>Progreso de <b>{_e(report.muscle_name)}</b> &nbsp;·&nbsp; {periodo}"
        f"<br/>Entrenador: {_e(trainer.full_name)} &nbsp;·&nbsp; "
        f"informe generado el {_fecha(dt.datetime.now())}</p>"
        f"<hr/>"
    )


def _resumen(report) -> str:
    filas = []

    crecimiento = report.delta_circumference
    if crecimiento is not None:
        color = _BUENO if crecimiento > 0 else _SUAVE
        filas.append(
            f"<b>Perímetro del músculo:</b> "
            f"<span style='color:{color}'>{crecimiento:+.1f} cm</span> "
            f"({report.before.circumference_cm:.1f} → {report.after.circumference_cm:.1f} cm)"
        )
    balance = report.delta_balance
    if balance is not None and abs(balance) >= 1.0:
        # Por debajo de un punto no se califica: un "+0 puntos (más
        # desbalanceado)" es una advertencia sobre algo que no pasó.
        color = _BUENO if balance < 0 else _OJO
        lectura = "más parejo" if balance < 0 else "más desbalanceado"
        filas.append(
            f"<b>Balance entre sensores:</b> "
            f"<span style='color:{color}'>{balance:+.0f} puntos</span> ({lectura})"
        )
    elif report.after.balance_gap is not None:
        filas.append(
            f"<b>Balance entre sensores:</b> "
            f"{report.after.balance_gap:.0f} puntos de diferencia, sin cambio"
        )
    if report.days_between:
        filas.append(f"<b>Tiempo entre evaluaciones:</b> {report.days_between} días")

    detalle = ("<p class='sub'>" + "<br/>".join(filas) + "</p>") if filas else ""
    return f"<p class='headline'>{_e(report.headline())}</p>{detalle}"


def _tabla(report, sessions) -> str:
    if not report.comparisons:
        return ""

    filas = []
    for c in report.comparisons:
        color = _VERDICT_COLOR[c.verdict]
        peso = ""
        if c.after.load_kg:
            peso = f"{c.after.load_kg:.1f} kg".replace(".0 kg", " kg")
            if c.delta_load:
                peso += f" ({c.delta_load:+.1f})".replace(".0)", ")")

        antes = f"{c.before.activation_pct:.0f}%" if c.before else "—"
        delta = f"{c.delta_activation:+.0f}" if c.delta_activation is not None else "—"
        umbral = f"±{c.threshold:.0f}" if c.before else "—"

        filas.append(
            "<tr>"
            f"<td><b>{_e(c.name)}</b><br/>"
            f"<span style='color:{color}; font-size:8pt'>{_e(c.message())}</span></td>"
            f"<td class='num'>{antes}</td>"
            f"<td class='num'>{c.after.activation_pct:.0f}%</td>"
            # La diferencia de activación va en tinta neutra, no en el
            # color del veredicto: un −4 en verde desconcierta a quien
            # recorre la columna. Quien califica es la línea de texto de
            # la izquierda, que además explica por qué.
            f"<td class='num'><b>{delta}</b></td>"
            f"<td class='num' style='color:{_SUAVE}'>{umbral}</td>"
            f"<td class='num'>{peso or '—'}</td>"
            "</tr>"
        )

    return (
        "<h2>Ejercicio por ejercicio</h2>"
        "<table>"
        "<tr><th>EJERCICIO Y LECTURA</th><th class='num'>ANTES</th><th class='num'>AHORA</th>"
        "<th class='num'>Δ ACTIVACIÓN</th><th class='num'>UMBRAL</th>"
        "<th class='num'>PESO</th></tr>"
        + "".join(filas)
        + "</table>"
    )


def _trayectoria(sessions) -> str:
    """
    Historia completa de cada ejercicio, si hay más de dos evaluaciones.

    En pantalla es una mini-gráfica; en papel es una lista de valores,
    que se lee igual de bien y no obliga a incrustar una imagen.
    """
    if len(sessions) < 3:
        return ""

    ultima = sessions[-1]
    filas = []
    for ejercicio in ultima.exercises:
        puntos = trend_for(sessions, ejercicio.exercise_id)
        if len(puntos) < 3:
            continue
        valores = " → ".join(f"{v:.0f}%" for _, v in puntos)
        fechas = " · ".join(f"{d:%d/%m}" for d, _ in puntos)
        filas.append(
            f"<tr><td><b>{_e(ejercicio.name)}</b></td>"
            f"<td>{valores}<br/><span class='nota'>{fechas}</span></td></tr>"
        )

    if not filas:
        return ""
    return (
        "<h2>Trayectoria completa</h2>"
        "<table>"
        "<tr><th>EJERCICIO</th><th>ACTIVACIÓN EN CADA EVALUACIÓN</th></tr>"
        + "".join(filas)
        + "</table>"
    )


def _e(text) -> str:
    return html.escape(str(text or ""))


def _fecha(when: dt.datetime) -> str:
    return f"{when:%d/%m/%Y}"
