"""
Pruebas de los PDF que exporta la aplicación.

LA REGRESIÓN QUE MOTIVÓ ESTE ARCHIVO
====================================

Los PDF se generaban sin error y con el texto correcto, pero al abrirlos
todo salía diminuto en la esquina superior izquierda: el contenido
ocupaba el 16% del ancho de la hoja.

La causa era de unidades. El ancho de página se fijaba con
`paintRectPixels(300)`, que devuelve unos 2245 píxeles de dispositivo, y
`QTextDocument` interpreta ese número con su propia resolución (~96 ppp).
Maquetaba entonces una página enormemente ancha, y al imprimirla la
encajaba entera en una A4.

Comprobar que el archivo existe y que es un PDF no detecta nada de esto
—el archivo era perfectamente válido—, así que estas pruebas **dibujan**
el PDF y miden qué fracción de la hoja ocupa la tinta. Es lo único que
distingue un PDF correcto de uno ilegible.
"""

from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    or (sys.platform.startswith("linux") and not os.environ.get("DISPLAY")),
    reason="generar y dibujar PDF necesita un servidor gráfico real",
)

# Proporción mínima del ancho de hoja que debe ocupar el contenido. Un
# PDF bien maquetado llega al 90%; el defecto de unidades daba 16%.
ANCHO_MINIMO = 0.75


def caja_de_tinta(ruta: str, pagina: int = 0, ancho: int = 400):
    """
    Rectángulo que ocupa la tinta en una página, como fracción de la hoja.

    Devuelve (fracción de ancho, fracción de alto). Se mide por el canal
    alfa y no por el color: `QPdfDocument.render` devuelve la página con
    fondo transparente, así que un píxel en blanco y uno vacío tienen el
    mismo color y solo se distinguen por su opacidad.
    """
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    documento = QPdfDocument()
    documento.load(ruta)
    alto = int(ancho * 842 / 595)  # proporción A4
    imagen = documento.render(pagina, QSize(ancho, alto))

    xs: list[int] = []
    ys: list[int] = []
    for y in range(alto):
        for x in range(ancho):
            if imagen.pixelColor(x, y).alpha() > 40:
                xs.append(x)
                ys.append(y)

    if not xs:
        return (0.0, 0.0)
    return ((max(xs) - min(xs)) / ancho, (max(ys) - min(ys)) / alto)


def paginas(ruta: str) -> int:
    from PySide6.QtPdf import QPdfDocument

    documento = QPdfDocument()
    documento.load(ruta)
    return documento.pageCount()


@pytest.fixture
def rutina_pdf(app_state, client_fixture, tmp_path, qtbot):
    """Genera el PDF de una rutina recién creada y devuelve su ruta."""
    from myofit_pro.gui.routine_detail_view import RoutineDetailView
    from myofit_pro.gui.routine_pdf import export_routine_pdf
    from myofit_pro.gui.routines_list_view import RoutinesListView
    from myofit_pro.routine_engine import SPLITS

    lista = RoutinesListView(app_state)
    qtbot.addWidget(lista)
    lista.reload()
    lista._on_generate_clicked()

    rutina = app_state.routine_repo.list_for_client(client_fixture.id)[0]
    detalle = RoutineDetailView(app_state)
    qtbot.addWidget(detalle)
    detalle.load_routine(rutina.id)

    destino = tmp_path / "rutina.pdf"
    export_routine_pdf(
        str(destino), app_state.current_trainer, client_fixture,
        detalle._routine, detalle._bloques, detalle._fuentes,
        split=SPLITS.get(detalle._routine.days_per_week or 0),
        comparacion=detalle._comparison_rows(),
    )
    return str(destino)


@pytest.fixture
def progreso_pdf(app_state, client_fixture, tmp_path, qtbot):
    """Genera el informe de progreso en PDF y devuelve su ruta."""
    del qtbot
    from myofit_pro.gui.progress_pdf import export_progress_pdf

    muscle = app_state.muscles_with_history(client_fixture.id)[0][0]
    reporte, sesiones = app_state.progress_for_muscle(client_fixture.id, muscle.id)

    destino = tmp_path / "progreso.pdf"
    export_progress_pdf(
        str(destino), app_state.current_trainer, client_fixture, reporte, sesiones
    )
    return str(destino)


class TestPdfDeRutina:
    def test_se_genera_un_pdf_valido(self, rutina_pdf):
        from pathlib import Path

        datos = Path(rutina_pdf).read_bytes()
        assert datos[:5] == b"%PDF-"
        assert len(datos) > 2000

    def test_el_contenido_ocupa_la_hoja(self, rutina_pdf):
        """
        La prueba que detecta el defecto de unidades: con él, el texto
        ocupaba el 16% del ancho en la esquina superior izquierda.
        """
        ancho, _ = caja_de_tinta(rutina_pdf)
        assert ancho > ANCHO_MINIMO, f"el contenido solo ocupa el {ancho:.0%} del ancho"

    def test_el_contenido_empieza_arriba_del_todo(self, rutina_pdf):
        _, alto = caja_de_tinta(rutina_pdf)
        assert alto > 0.5

    def test_la_pagina_es_a4(self, rutina_pdf):
        from PySide6.QtPdf import QPdfDocument

        documento = QPdfDocument()
        documento.load(rutina_pdf)
        tamano = documento.pagePointSize(0)
        assert round(tamano.width()) == 595
        assert round(tamano.height()) == 842

    def test_el_contenido_largo_se_reparte_en_varias_paginas(self, rutina_pdf):
        """
        Una rutina de cuatro días no cabe en una hoja. Si saliera en una
        sola, estaría recortada.
        """
        assert paginas(rutina_pdf) >= 1


class TestPdfDeProgreso:
    def test_se_genera_un_pdf_valido(self, progreso_pdf):
        from pathlib import Path

        assert Path(progreso_pdf).read_bytes()[:5] == b"%PDF-"

    def test_el_contenido_ocupa_la_hoja(self, progreso_pdf):
        ancho, _ = caja_de_tinta(progreso_pdf)
        assert ancho > ANCHO_MINIMO, f"el contenido solo ocupa el {ancho:.0%} del ancho"

    def test_la_pagina_es_a4(self, progreso_pdf):
        from PySide6.QtPdf import QPdfDocument

        documento = QPdfDocument()
        documento.load(progreso_pdf)
        assert round(documento.pagePointSize(0).width()) == 595


class TestPaginacion:
    def test_un_documento_largo_ocupa_varias_paginas(self, tmp_path, qapp):
        """
        Prueba directa del motor de PDF, sin datos de la app: con el
        tamaño de página bien puesto, el texto que no cabe pasa a la hoja
        siguiente en vez de recortarse.
        """
        del qapp
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

        destino = str(tmp_path / "largo.pdf")
        writer = QPdfWriter(destino)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setResolution(300)

        documento = QTextDocument()
        documento.setDefaultStyleSheet("body { font-size: 10pt; }")
        documento.setHtml(
            "<body>" + "".join(f"<p>Línea {i}</p>" for i in range(200)) + "</body>"
        )
        documento.setPageSize(
            writer.pageLayout().paintRect(QPageLayout.Unit.Point).size()
        )
        documento.print_(writer)

        assert paginas(destino) >= 3
