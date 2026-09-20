"""Ventana principal y navegación entre secciones.

Posición en el flujo
--------------------
Se abre tras la autenticación, desde `myofit_pro.main.AuthWindow`. Crea
el `myofit_pro.gui.app_state.AppState` que comparten todas las vistas y
es el único punto donde se conectan las señales que cruzan de una sección
a otra.

Estructura de la navegación
---------------------------
Hereda de ``qfluentwidgets.FluentWindow``, que aporta la barra lateral y
el área de contenido apiladas.

Cuatro secciones aplican el patrón de contenedor con navegación interna
—una sola entrada en la barra lateral y varias pantallas dentro—, de modo
que los pasos intermedios y las pantallas de detalle no aparezcan sueltos
en el menú:

`myofit_pro.gui.evaluation_wizard_container.EvaluationWizardContainer`
    Los seis pasos del asistente de evaluación.
`myofit_pro.gui.clients_container.ClientsContainer`
    Lista, ficha y progreso del cliente.
`myofit_pro.gui.history_container.HistoryContainer`
    Lista de evaluaciones e informe de cada una.
`myofit_pro.gui.routines_container.RoutinesContainer`
    Lista de rutinas por fecha y rutina completa.

Señales entre secciones
-----------------------
Las vistas no se conocen entre sí: emiten señales que
`MainWindow._wire_cross_section_signals` conecta. Así, la ficha de un
cliente puede abrir el asistente de evaluación sin depender de él.

See Also
--------
myofit_pro.gui.app_state : Estado compartido que esta ventana construye.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QScrollArea
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import FluentWindow, InfoBadge, InfoBadgePosition, NavigationItemPosition

from myofit_pro.database.models import Trainer
from myofit_pro.gui.alerts_view import AlertsView
from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.clients_container import ClientsContainer
from myofit_pro.gui.dashboard_view import DashboardView
from myofit_pro.gui.evaluation_wizard_container import EvaluationWizardContainer
from myofit_pro.gui.history_container import HistoryContainer
from myofit_pro.gui.routines_container import RoutinesContainer
from myofit_pro.gui.sensors_view import SensorsView
from myofit_pro.gui.theme import apply_dark_theme
from myofit_pro.gui.trainer_profile_view import TrainerProfileView


class MainWindow(FluentWindow):
    """Ventana principal de la aplicación.

    Parameters
    ----------
    trainer : myofit_pro.database.models.Trainer
        Entrenador autenticado.

    Attributes
    ----------
    logout_requested : PySide6.QtCore.Signal
        Se emite al cerrar sesión, para que
        `myofit_pro.main.AuthWindow` vuelva a mostrarse.
    state : myofit_pro.gui.app_state.AppState
        Estado compartido por todas las vistas.
    """

    logout_requested = Signal()

    def __init__(self, trainer: Trainer):
        super().__init__()
        apply_dark_theme(self)
        self.setWindowTitle("MyoFit Pro")
        self.resize(1200, 800)

        self.state = AppState(current_trainer=trainer)
        self._pending_badge: InfoBadge | None = None
        self._report_origin = None

        # La navegación es plana —cada sección es raíz— y las pantallas
        # anidadas traen su propio botón de volver, así que la flecha de
        # retroceso de FluentWindow sobra.
        self.navigationInterface.setReturnButtonVisible(False)
        self.navigationInterface.setExpandWidth(230)

        self._build_interfaces()
        self._build_navigation()
        self._wire_cross_section_signals()
        self.refresh_pending_badge()

        self.closeEvent = self._on_close  # type: ignore[method-assign]

    # ── Construcción de las sub-interfaces (una por sección del sidebar) ──

    def _build_interfaces(self) -> None:
        """Instancia las vistas de las secciones y les asigna su nombre.

        Notes
        -----
        ``FluentWindow.addSubInterface`` exige que cada widget tenga un
        ``objectName`` único antes de registrarlo.
        """
        self.dashboard_view = DashboardView(self.state)
        self.clients_container = ClientsContainer(self.state)
        self.eval_wizard = EvaluationWizardContainer(self.state)
        self.history = HistoryContainer(self.state)
        self.routines = RoutinesContainer(self.state)
        self.sensors_view = SensorsView(self.state)
        self.alerts_view = AlertsView(self.state)
        self.profile_view = TrainerProfileView(self.state)

        for name, widget in (
            ("dashboardView", self.dashboard_view),
            ("clientsContainer", self.clients_container),
            ("evalWizard", self.eval_wizard),
            ("historyContainer", self.history),
            ("routinesContainer", self.routines),
            ("sensorsView", self.sensors_view),
            ("alertsView", self.alerts_view),
            ("profileView", self.profile_view),
        ):
            widget.setObjectName(name)

    def _build_navigation(self) -> None:
        """Registra las secciones en la barra lateral.

        Notes
        -----
        El informe de una evaluación no constituye una entrada propia:
        es la pantalla de detalle del historial.
        """
        add = self.addSubInterface
        add(self.dashboard_view, FIF.HOME, "Vista general")
        add(self.clients_container, FIF.PEOPLE, "Mis clientes")
        self._eval_nav_item = add(self.eval_wizard, FIF.ADD, "Nueva evaluación")
        add(self.history, FIF.HISTORY, "Historial sEMG")
        add(self.sensors_view, FIF.SPEED_HIGH, "Sensores sEMG")
        add(self.routines, FIF.CALENDAR, "Rutinas")
        add(self.alerts_view, FIF.RINGER, "Alertas", position=NavigationItemPosition.BOTTOM)
        add(self.profile_view, FIF.PEOPLE, "Mi perfil", position=NavigationItemPosition.BOTTOM)

        self.stackedWidget.currentChanged.connect(self._on_section_changed)

        self._install_double_click_to_top()

    def _install_double_click_to_top(self) -> None:
        """Asocia el doble clic en la barra lateral al desplazamiento al inicio.

        Notes
        -----
        Las secciones extensas —una rutina de cinco días, la ficha de un
        cliente con historial— obligarían a arrastrar la barra de
        desplazamiento de vuelta. Es el mismo gesto que la barra de
        estado de un teléfono móvil.
        """
        from qfluentwidgets import NavigationPushButton

        for boton in self.navigationInterface.findChildren(NavigationPushButton):
            boton.mouseDoubleClickEvent = (
                lambda event, b=boton: self._on_nav_double_click(event, b)
            )

    def _on_nav_double_click(self, event, boton) -> None:
        """Atiende el doble clic sobre un icono de la barra lateral."""
        del event, boton  # El doble clic siempre recae en la sección activa.
        self.scroll_current_to_top()

    def scroll_current_to_top(self) -> None:
        """Desplaza al inicio la pantalla visible.

        Notes
        -----
        Localiza las áreas de desplazamiento del widget activo en lugar
        de requerir un método propio en cada sección: los contenedores
        albergan varias pantallas y solo la visible tiene barra que
        mover.
        """
        actual = self.stackedWidget.currentWidget()
        if actual is None:
            return
        for area in actual.findChildren(QScrollArea):
            if area.isVisible():
                area.verticalScrollBar().setValue(0)

    # ── Señales que cruzan de una sección a otra ─────────────────────

    def _wire_cross_section_signals(self) -> None:
        """Conecta las señales que cruzan de una sección a otra.

        Es el único punto donde las secciones se relacionan entre sí;
        ninguna de ellas importa a las demás.
        """
        # Desde la ficha del cliente: iniciar evaluación o ver un informe.
        self.clients_container.start_evaluation_requested.connect(self._start_evaluation_for_client)
        self.clients_container.view_report_requested.connect(
            lambda sid: self._open_report(sid, "Ficha del cliente")
        )
        # Desde la vista general: abrir el informe de una evaluación.
        self.dashboard_view.session_selected.connect(
            lambda sid: self._open_report(sid, "Vista general")
        )
        # Desde el historial: retomar una evaluación en curso.
        self.history.resume_session_requested.connect(self._resume_evaluation)

        # Atajos de la vista general a las demás secciones.
        self.dashboard_view.new_evaluation_requested.connect(
            lambda: self.switchTo(self.eval_wizard)
        )
        self.dashboard_view.clients_requested.connect(self._open_clients)
        self.dashboard_view.sensors_requested.connect(
            lambda: self.switchTo(self.sensors_view)
        )
        self.dashboard_view.client_selected.connect(self._open_client_profile)

        self.history.report_closed.connect(self._leave_report)

        # Cualquier cambio en los datos altera cifras que otras secciones
        # ya tienen dibujadas, de modo que se refrescan todas.
        self.eval_wizard.evaluation_completed.connect(self._refresh_all)
        self.history.data_changed.connect(self._refresh_all)
        self.clients_container.data_changed.connect(self._refresh_all)
        self.routines.data_changed.connect(self._refresh_all)

        self.eval_wizard.pending_changed.connect(self.refresh_pending_badge)
        self.profile_view.logout_requested.connect(self._on_logout)

    def _refresh_all(self) -> None:
        """Recarga todas las secciones tras un cambio en los datos."""
        self.history.reload()
        self.dashboard_view.refresh()
        self.clients_container.list_view.reload()
        self.routines.reload()
        self.refresh_pending_badge()

    def _on_section_changed(self, _index: int) -> None:
        """Recarga la sección a la que se acaba de entrar.

        Notes
        -----
        Los contenedores solo recargan su lista si no tienen abierta una
        pantalla de detalle: hacerlo la cerraría de golpe.
        """
        current = self.stackedWidget.currentWidget()
        if current is self.eval_wizard:
            self.eval_wizard.check_pending_evaluation()
        elif current is self.history:
            if not self.history.is_showing_report():
                self.history.reload()
        elif current is self.clients_container:
            self.clients_container.list_view.reload()
        elif current is self.routines:
            if not self.routines.is_showing_detail():
                self.routines.reload()

    def _start_evaluation_for_client(self, client) -> None:
        """Abre el asistente de evaluación ya centrado en un cliente."""
        self.eval_wizard.start_for_client(client)
        self.switchTo(self.eval_wizard)

    def _resume_evaluation(self, session_id: int) -> None:
        """Abre el asistente retomando una evaluación sin terminar."""
        self.eval_wizard.resume_session(session_id)
        self.switchTo(self.eval_wizard)

    def _open_clients(self) -> None:
        """Muestra la lista de clientes."""
        self.clients_container.show_list()
        self.switchTo(self.clients_container)

    def _open_client_profile(self, client) -> None:
        """Muestra la ficha de un cliente."""
        self.clients_container.show_profile(client)
        self.switchTo(self.clients_container)

    def _open_report(self, session_id: int, back_label: str = "Historial") -> None:
        """Abre el informe de una evaluación.

        Parameters
        ----------
        session_id : int
            Evaluación a mostrar.
        back_label : str, default="Historial"
            Texto del botón de retroceso, que nombra la sección de
            procedencia.

        Notes
        -----
        El informe reside en el historial pero se abre también desde la
        vista general y desde la ficha del cliente. Se registra la
        sección de origen para que el retroceso regrese a ella y no a un
        destino fijo.
        """
        current = self.stackedWidget.currentWidget()
        self._report_origin = None if current is self.history else current
        self.history.show_report(session_id, back_label)
        self.switchTo(self.history)

    def _leave_report(self) -> None:
        """Regresa a la sección desde la que se abrió el informe.

        Si se llegó desde el propio historial no hace nada, porque el
        contenedor ya ha vuelto a su lista.
        """
        if self._report_origin is not None:
            self.switchTo(self._report_origin)
            self._report_origin = None

    # ── Badge de evaluaciones pendientes ─────────────────────────────

    def refresh_pending_badge(self) -> None:
        """Actualiza el contador de evaluaciones sin terminar.

        Muestra un distintivo junto a la entrada de nueva evaluación
        cuando hay sesiones abiertas, y lo retira cuando no las hay.
        """
        count = self.state.evaluation_repo.count_in_progress(self.state.current_trainer.id)

        if self._pending_badge is not None:
            self._pending_badge.deleteLater()
            self._pending_badge = None

        if count > 0:
            self._pending_badge = InfoBadge.attension(
                text=str(count),
                parent=self.navigationInterface,
                target=self._eval_nav_item,
                position=InfoBadgePosition.NAVIGATION_ITEM,
            )

    # ── Cierre limpio ─────────────────────────────────────────────────

    def _on_logout(self) -> None:
        """Cierra la sesión y libera los recursos del estado compartido."""
        self.state.shutdown()
        self.logout_requested.emit()
        self.close()

    def _on_close(self, event) -> None:
        """Libera los recursos al cerrarse la ventana."""
        self.state.shutdown()
        event.accept()