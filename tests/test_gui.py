"""
Pruebas de la interfaz, con widgets reales.

Hasta ahora la GUI se verificaba con guiones que había que correr a
mano. Estas pruebas hacen lo mismo dentro de `pytest`: construyen los
widgets de verdad contra una base temporal y comprueban navegación,
estado y lo que queda escrito en pantalla.

No cubren pintado ni gestos del ratón —eso sigue siendo revisión
visual—, sino lo que se rompe en silencio cuando alguien cambia una
señal, un nombre de campo o el orden de una pantalla.

NECESITAN SERVIDOR GRÁFICO
==========================

qfluentwidgets usa funciones nativas de ventana y revienta con
`QT_QPA_PLATFORM=offscreen`, así que estas pruebas se saltan solas si no
hay pantalla. En un servidor de integración habría que darles una
(xvfb) o dejarlas fuera a propósito.
"""

from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    or (sys.platform.startswith("linux") and not os.environ.get("DISPLAY")),
    reason="la interfaz necesita un servidor gráfico real",
)


def textos_de(widget) -> str:
    """Todo el texto visible de un widget, para poder buscar en él."""
    partes = []
    for hijo in widget.findChildren(object):
        if hasattr(hijo, "text"):
            try:
                valor = hijo.text()
            except TypeError:
                continue
            if isinstance(valor, str):
                partes.append(valor)
    return " | ".join(partes)


# ── Ficha del cliente ────────────────────────────────────────────────


class TestFichaDelCliente:
    def test_el_historial_se_agrupa_en_dias_plegables(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.client_profile_view import ClientProfileView
        from myofit_pro.gui.theme import CollapsibleGroup

        vista = ClientProfileView(app_state)
        qtbot.addWidget(vista)
        vista.load_client(client_fixture)

        grupos = vista.findChildren(CollapsibleGroup)
        assert len(grupos) == 2  # dos evaluaciones en días distintos

    def test_el_dia_mas_reciente_viene_abierto(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.client_profile_view import ClientProfileView
        from myofit_pro.gui.theme import CollapsibleGroup

        vista = ClientProfileView(app_state)
        qtbot.addWidget(vista)
        vista.load_client(client_fixture)

        grupos = vista.findChildren(CollapsibleGroup)
        assert grupos[0].is_expanded
        assert not grupos[1].is_expanded

    def test_ya_no_muestra_calibraciones_mvc(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.client_profile_view import ClientProfileView

        vista = ClientProfileView(app_state)
        qtbot.addWidget(vista)
        vista.load_client(client_fixture)
        assert "Calibraciones MVC" not in textos_de(vista)

    def test_el_boton_de_progreso_se_habilita_con_evaluaciones(
        self, app_state, client_fixture, qtbot
    ):
        from myofit_pro.gui.client_profile_view import ClientProfileView

        vista = ClientProfileView(app_state)
        qtbot.addWidget(vista)
        vista.load_client(client_fixture)
        assert vista.progress_btn.isEnabled()

    def test_sin_evaluaciones_el_progreso_queda_deshabilitado(self, app_state, qtbot):
        from myofit_pro.gui.client_profile_view import ClientProfileView

        nuevo = app_state.client_repo.create(
            trainer_id=app_state.current_trainer.id, full_name="Sin Datos", goal="Fuerza"
        )
        vista = ClientProfileView(app_state)
        qtbot.addWidget(vista)
        vista.load_client(nuevo)
        assert not vista.progress_btn.isEnabled()


# ── Selector de cliente con búsqueda ─────────────────────────────────


class TestSelectorDeCliente:
    def test_resuelve_el_cliente_escrito(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.client_picker import ClientPicker

        picker = ClientPicker()
        qtbot.addWidget(picker)
        picker.set_clients([client_fixture])
        picker.setText(client_fixture.full_name)
        assert picker.current_client().id == client_fixture.id

    def test_un_nombre_que_no_existe_no_resuelve_a_nadie(
        self, app_state, client_fixture, qtbot
    ):
        """
        Mientras se teclea, el texto es un nombre a medias. Devolver un
        cliente cualquiera ahí filtraría por quien no se pidió.
        """
        from myofit_pro.gui.client_picker import ClientPicker

        picker = ClientPicker()
        qtbot.addWidget(picker)
        picker.set_clients([client_fixture])
        picker.setText("no existe")
        assert picker.current_client() is None

    def test_limpiar_deja_el_campo_vacio(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.client_picker import ClientPicker

        picker = ClientPicker()
        qtbot.addWidget(picker)
        picker.set_clients([client_fixture])
        picker.clear_selection()
        assert picker.current_client() is None
        assert picker.currentText() == ""

    def test_recargar_conserva_la_seleccion(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.client_picker import ClientPicker

        otro = app_state.client_repo.create(
            trainer_id=app_state.current_trainer.id, full_name="Beto", goal="Fuerza"
        )
        picker = ClientPicker()
        qtbot.addWidget(picker)
        picker.set_clients([client_fixture, otro])
        picker.select(otro)

        picker.set_clients([client_fixture, otro])
        assert picker.current_client().id == otro.id

    def test_un_cliente_borrado_deja_de_estar_seleccionado(
        self, app_state, client_fixture, qtbot
    ):
        from myofit_pro.gui.client_picker import ClientPicker

        otro = app_state.client_repo.create(
            trainer_id=app_state.current_trainer.id, full_name="Beto", goal="Fuerza"
        )
        picker = ClientPicker()
        qtbot.addWidget(picker)
        picker.set_clients([client_fixture, otro])
        picker.select(otro)

        picker.set_clients([client_fixture])
        assert picker.current_client().id == client_fixture.id


# ── Reporte de una evaluación ────────────────────────────────────────


class TestReporte:
    def test_muestra_el_ranking_de_ejercicios(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.session_report import SessionReportBody

        sesiones = app_state.evaluation_repo.list_for_client(client_fixture.id)
        cuerpo = SessionReportBody(app_state)
        qtbot.addWidget(cuerpo)
        cuerpo.load(sesiones[0].id)

        texto = textos_de(cuerpo)
        assert "Ranking de ejercicios" in texto
        assert "Balance entre canales" in texto

    def test_sin_sesion_muestra_el_estado_vacio(self, app_state, qtbot):
        from myofit_pro.gui.session_report import SessionReportBody

        cuerpo = SessionReportBody(app_state)
        qtbot.addWidget(cuerpo)
        cuerpo.load(None)
        assert "Selecciona una evaluación" in textos_de(cuerpo)

    def test_una_sesion_que_no_existe_no_revienta(self, app_state, qtbot):
        from myofit_pro.gui.session_report import SessionReportBody

        cuerpo = SessionReportBody(app_state)
        qtbot.addWidget(cuerpo)
        cuerpo.load(99999)
        assert "No se encontró" in textos_de(cuerpo)


# ── Historial ────────────────────────────────────────────────────────


class TestHistorial:
    def test_filtrar_por_cliente_deja_solo_sus_evaluaciones(self, app_state, qtbot):
        from myofit_pro.gui.history_view import HistoryView

        vista = HistoryView(app_state)
        qtbot.addWidget(vista)
        vista.reload()

        otro = app_state.client_repo.create(
            trainer_id=app_state.current_trainer.id, full_name="Beto", goal="Fuerza"
        )
        vista.reload()
        vista.client_filter.setText(otro.full_name)
        vista._apply_filter()
        assert vista.list_layout.count() == 0

    def test_sin_filtro_se_ven_todas(self, app_state, qtbot):
        from myofit_pro.gui.history_view import HistoryView

        vista = HistoryView(app_state)
        qtbot.addWidget(vista)
        vista.reload()
        vista._clear_filter()
        assert vista.list_layout.count() == 2


# ── Contenedor del historial: lista + reporte ────────────────────────


class TestContenedorDelHistorial:
    def test_arranca_en_la_lista(self, app_state, qtbot):
        from myofit_pro.gui.history_container import HistoryContainer

        contenedor = HistoryContainer(app_state)
        qtbot.addWidget(contenedor)
        assert not contenedor.is_showing_report()

    def test_abrir_una_evaluacion_entra_al_reporte(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.history_container import HistoryContainer

        contenedor = HistoryContainer(app_state)
        qtbot.addWidget(contenedor)
        sesiones = app_state.evaluation_repo.list_for_client(client_fixture.id)
        contenedor.show_report(sesiones[0].id)
        assert contenedor.is_showing_report()

    def test_volver_regresa_a_la_lista(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.history_container import HistoryContainer

        contenedor = HistoryContainer(app_state)
        qtbot.addWidget(contenedor)
        sesiones = app_state.evaluation_repo.list_for_client(client_fixture.id)
        contenedor.show_report(sesiones[0].id)
        contenedor.report_view.back_requested.emit()
        assert not contenedor.is_showing_report()

    def test_el_boton_de_volver_dice_de_donde_se_vino(
        self, app_state, client_fixture, qtbot
    ):
        from myofit_pro.gui.history_container import HistoryContainer

        contenedor = HistoryContainer(app_state)
        qtbot.addWidget(contenedor)
        sesiones = app_state.evaluation_repo.list_for_client(client_fixture.id)
        contenedor.show_report(sesiones[0].id, "Vista general")
        assert "Vista general" in textos_de(contenedor.report_view)


# ── Rutinas ──────────────────────────────────────────────────────────


class TestRutinas:
    def test_generar_crea_una_rutina_del_cliente(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.routines_list_view import RoutinesListView

        vista = RoutinesListView(app_state)
        qtbot.addWidget(vista)
        vista.reload()
        vista._on_generate_clicked()

        assert len(app_state.routine_repo.list_for_client(client_fixture.id)) == 1

    def test_generar_dos_veces_conserva_el_historial(
        self, app_state, client_fixture, qtbot
    ):
        from myofit_pro.gui.routines_list_view import RoutinesListView

        vista = RoutinesListView(app_state)
        qtbot.addWidget(vista)
        vista.reload()
        vista._on_generate_clicked()
        vista._on_generate_clicked()

        assert len(app_state.routine_repo.list_for_client(client_fixture.id)) == 2

    def test_la_rutina_guarda_de_qué_evaluaciones_salio(
        self, app_state, client_fixture, qtbot
    ):
        from myofit_pro.gui.routines_list_view import RoutinesListView

        vista = RoutinesListView(app_state)
        qtbot.addWidget(vista)
        vista.reload()
        vista._on_generate_clicked()

        rutina = app_state.routine_repo.list_for_client(client_fixture.id)[0]
        assert rutina.source_session_ids

    def test_el_detalle_usa_dias_de_la_semana(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.routine_detail_view import RoutineDetailView
        from myofit_pro.gui.routines_list_view import RoutinesListView

        lista = RoutinesListView(app_state)
        qtbot.addWidget(lista)
        lista.reload()
        lista._on_generate_clicked()

        rutina = app_state.routine_repo.list_for_client(client_fixture.id)[0]
        detalle = RoutineDetailView(app_state)
        qtbot.addWidget(detalle)
        detalle.load_routine(rutina.id)

        texto = textos_de(detalle)
        assert "Lunes" in texto
        assert "de tu PR" in texto

    def test_el_detalle_trae_la_comparativa_y_no_la_prescripcion_repetida(
        self, app_state, client_fixture, qtbot
    ):
        from myofit_pro.gui.routine_detail_view import RoutineDetailView
        from myofit_pro.gui.routines_list_view import RoutinesListView

        lista = RoutinesListView(app_state)
        qtbot.addWidget(lista)
        lista.reload()
        lista._on_generate_clicked()

        rutina = app_state.routine_repo.list_for_client(client_fixture.id)[0]
        detalle = RoutineDetailView(app_state)
        qtbot.addWidget(detalle)
        detalle.load_routine(rutina.id)

        texto = textos_de(detalle)
        assert "Comparado con la evaluación anterior" in texto
        assert "Cómo se hace cada ejercicio" not in texto
        assert "De dónde salió" not in texto

    def test_la_comparativa_enfrenta_la_ultima_contra_la_anterior(
        self, app_state, client_fixture, qtbot
    ):
        """
        Los dos valores salen de evaluaciones distintas, no del promedio
        guardado en la rutina: si salieran de ahí, la diferencia sería de
        un punto y no diría nada.
        """
        from myofit_pro.gui.routine_detail_view import RoutineDetailView
        from myofit_pro.gui.routines_list_view import RoutinesListView

        lista = RoutinesListView(app_state)
        qtbot.addWidget(lista)
        lista.reload()
        lista._on_generate_clicked()

        rutina = app_state.routine_repo.list_for_client(client_fixture.id)[0]
        detalle = RoutineDetailView(app_state)
        qtbot.addWidget(detalle)
        detalle.load_routine(rutina.id)

        filas = detalle._comparison_rows()
        assert filas
        assert any(antes is not None and antes != ahora for _, _, antes, ahora in filas)

    def test_la_edicion_guarda_las_series_cambiadas(
        self, app_state, client_fixture, qtbot
    ):
        from myofit_pro.gui.routine_detail_view import RoutineDetailView
        from myofit_pro.gui.routines_list_view import RoutinesListView

        lista = RoutinesListView(app_state)
        qtbot.addWidget(lista)
        lista.reload()
        lista._on_generate_clicked()

        rutina = app_state.routine_repo.list_for_client(client_fixture.id)[0]
        detalle = RoutineDetailView(app_state)
        qtbot.addWidget(detalle)
        detalle.load_routine(rutina.id)

        detalle._toggle_edit()
        primer_dia = sorted(detalle._draft)[0]
        detalle._draft[primer_dia][0]["sets"] = 9
        detalle._save_edit()

        guardada = app_state.routine_repo.get(rutina.id)
        assert any(e.sets == 9 for e in guardada.exercises)

    def test_la_edicion_puede_quitar_un_ejercicio(
        self, app_state, client_fixture, qtbot
    ):
        from myofit_pro.gui.routine_detail_view import RoutineDetailView
        from myofit_pro.gui.routines_list_view import RoutinesListView

        lista = RoutinesListView(app_state)
        qtbot.addWidget(lista)
        lista.reload()
        lista._on_generate_clicked()

        rutina = app_state.routine_repo.list_for_client(client_fixture.id)[0]
        antes = len(rutina.exercises)

        detalle = RoutineDetailView(app_state)
        qtbot.addWidget(detalle)
        detalle.load_routine(rutina.id)
        detalle._toggle_edit()
        primer_dia = sorted(detalle._draft)[0]
        detalle._remove_row(primer_dia, 0)
        detalle._save_edit()

        assert len(app_state.routine_repo.get(rutina.id).exercises) == antes - 1

    def test_descartar_la_edicion_no_toca_la_rutina(
        self, app_state, client_fixture, qtbot
    ):
        from myofit_pro.gui.routine_detail_view import RoutineDetailView
        from myofit_pro.gui.routines_list_view import RoutinesListView

        lista = RoutinesListView(app_state)
        qtbot.addWidget(lista)
        lista.reload()
        lista._on_generate_clicked()

        rutina = app_state.routine_repo.list_for_client(client_fixture.id)[0]
        antes = [(e.exercise_id, e.sets) for e in rutina.exercises]

        detalle = RoutineDetailView(app_state)
        qtbot.addWidget(detalle)
        detalle.load_routine(rutina.id)
        detalle._toggle_edit()
        primer_dia = sorted(detalle._draft)[0]
        detalle._draft[primer_dia][0]["sets"] = 9
        detalle._cancel_edit()

        despues = [
            (e.exercise_id, e.sets)
            for e in app_state.routine_repo.get(rutina.id).exercises
        ]
        assert despues == antes


# ── Progreso ─────────────────────────────────────────────────────────


class TestProgreso:
    def test_compara_las_dos_evaluaciones(self, app_state, client_fixture, qtbot):
        from myofit_pro.gui.client_progress_view import ClientProgressView

        vista = ClientProgressView(app_state)
        qtbot.addWidget(vista)
        vista.load_client(client_fixture)

        texto = textos_de(vista)
        assert client_fixture.full_name in texto
        assert "Ejercicio por ejercicio" in texto

    def test_un_cliente_sin_evaluaciones_lo_dice(self, app_state, qtbot):
        from myofit_pro.gui.client_progress_view import ClientProgressView

        nuevo = app_state.client_repo.create(
            trainer_id=app_state.current_trainer.id, full_name="Sin Datos", goal="Fuerza"
        )
        vista = ClientProgressView(app_state)
        qtbot.addWidget(vista)
        vista.load_client(nuevo)
        assert "todavía no tiene evaluaciones" in textos_de(vista)


# ── Ventana principal ────────────────────────────────────────────────


class TestVentanaPrincipal:
    def test_el_menu_no_repite_secciones(self, app_state, qtbot):
        from qfluentwidgets import NavigationPushButton

        from myofit_pro.gui.main_window import MainWindow

        ventana = MainWindow(app_state.current_trainer)
        ventana.eval_wizard.check_pending_evaluation = lambda: None
        qtbot.addWidget(ventana)

        nombres = [
            b.text()
            for b in ventana.navigationInterface.findChildren(NavigationPushButton)
            if b.text()
        ]
        assert len(nombres) == len(set(nombres))
        assert "Rutinas" in nombres
        assert "Historial sEMG" in nombres
        # El reporte y la rutina no son secciones propias sino detalles.
        assert "Reporte muscular" not in nombres
        assert "Rutina generada" not in nombres

    def test_todas_las_secciones_se_construyen(self, app_state, qtbot):
        from myofit_pro.gui.main_window import MainWindow

        ventana = MainWindow(app_state.current_trainer)
        ventana.eval_wizard.check_pending_evaluation = lambda: None
        qtbot.addWidget(ventana)

        for indice in range(ventana.stackedWidget.count()):
            ventana.stackedWidget.setCurrentIndex(indice)
            assert ventana.stackedWidget.currentWidget() is not None

    def test_el_doble_clic_del_menu_sube_la_pantalla(self, app_state, qtbot):
        from PySide6.QtWidgets import QScrollArea

        from myofit_pro.gui.main_window import MainWindow

        ventana = MainWindow(app_state.current_trainer)
        ventana.eval_wizard.check_pending_evaluation = lambda: None
        qtbot.addWidget(ventana)
        ventana.show()

        ventana.switchTo(ventana.clients_container)
        ventana.clients_container.show_profile(
            app_state.client_repo.list_for_trainer(app_state.current_trainer.id)[0]
        )
        areas = [
            a
            for a in ventana.clients_container.profile_view.findChildren(QScrollArea)
            if a.isVisible()
        ]
        assert areas
        barra = areas[0].verticalScrollBar()
        barra.setValue(barra.maximum())

        ventana.scroll_current_to_top()
        assert barra.value() == 0
