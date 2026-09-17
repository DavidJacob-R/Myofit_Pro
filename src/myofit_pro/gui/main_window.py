"""
Shell de navegación principal — equivalente a Views/MainShell.xaml(.cs).

Usa qfluentwidgets.FluentWindow, que ya trae la barra de navegación
lateral y el área de contenido (stackedWidget) integradas.

Dos secciones usan un patrón de "contenedor con navegación interna"
(un solo item de sidebar, varias pantallas adentro): el wizard de
evaluación (EvaluationWizardContainer) y clientes (ClientsContainer,
lista + perfil de detalle). Esto evita que pasos/pantallas intermedias
aparezcan sueltos en el menú lateral.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import FluentWindow, InfoBadge, InfoBadgePosition, NavigationItemPosition

from myofit_pro.database.models import Trainer
from myofit_pro.gui.alerts_view import AlertsView
from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.clients_container import ClientsContainer
from myofit_pro.gui.dashboard_view import DashboardView
from myofit_pro.gui.evaluation_wizard_container import EvaluationWizardContainer
from myofit_pro.gui.history_view import HistoryView
from myofit_pro.gui.report_view import ReportView
from myofit_pro.gui.routine_view import RoutineView
from myofit_pro.gui.sensors_view import SensorsView
from myofit_pro.gui.theme import apply_dark_theme
from myofit_pro.gui.trainer_profile_view import TrainerProfileView


class MainWindow(FluentWindow):
    logout_requested = Signal()

    def __init__(self, trainer: Trainer):
        super().__init__()
        apply_dark_theme(self)
        self.setWindowTitle("MyoFit Pro")
        self.resize(1200, 800)

        self.state = AppState(current_trainer=trainer)
        self._pending_badge: InfoBadge | None = None
        self._report_origin = None   # sección desde la que se abrió el reporte

        # La flecha de "regresar" que FluentWindow pone arriba del sidebar
        # no aplica aquí: la navegación es plana (cada sección es raíz) y
        # las pantallas anidadas traen su propio botón de volver.
        self.navigationInterface.setReturnButtonVisible(False)
        self.navigationInterface.setExpandWidth(230)

        self._build_interfaces()
        self._build_navigation()
        self._wire_cross_section_signals()
        self.refresh_pending_badge()

        self.closeEvent = self._on_close  # type: ignore[method-assign]

    # ── Construcción de las sub-interfaces (una por sección del sidebar) ──

    def _build_interfaces(self) -> None:
        self.dashboard_view = DashboardView(self.state)
        self.clients_container = ClientsContainer(self.state)
        self.eval_wizard = EvaluationWizardContainer(self.state)
        self.history_view = HistoryView(self.state)
        self.report_view = ReportView(self.state)
        self.routine_view = RoutineView(self.state)
        self.sensors_view = SensorsView(self.state)
        self.alerts_view = AlertsView(self.state)
        self.profile_view = TrainerProfileView(self.state)

        # qfluentwidgets.FluentWindow.addSubInterface requiere que cada
        # widget ya tenga un objectName único ANTES de registrarlo.
        for name, widget in (
            ("dashboardView", self.dashboard_view),
            ("clientsContainer", self.clients_container),
            ("evalWizard", self.eval_wizard),
            ("historyView", self.history_view),
            ("reportView", self.report_view),
            ("routineView", self.routine_view),
            ("sensorsView", self.sensors_view),
            ("alertsView", self.alerts_view),
            ("profileView", self.profile_view),
        ):
            widget.setObjectName(name)

    def _build_navigation(self) -> None:
        add = self.addSubInterface
        add(self.dashboard_view, FIF.HOME, "Vista general")
        add(self.clients_container, FIF.PEOPLE, "Mis clientes")
        self._eval_nav_item = add(self.eval_wizard, FIF.ADD, "Nueva evaluación")
        add(self.history_view, FIF.HISTORY, "Historial sEMG")
        add(self.sensors_view, FIF.SPEED_HIGH, "Sensores sEMG")
        add(self.report_view, FIF.DOCUMENT, "Reporte muscular")
        add(self.routine_view, FIF.CALENDAR, "Rutina generada")
        add(self.alerts_view, FIF.RINGER, "Alertas", position=NavigationItemPosition.BOTTOM)
        add(self.profile_view, FIF.PEOPLE, "Mi perfil", position=NavigationItemPosition.BOTTOM)

        # Al entrar a "Nueva evaluación", avisar si quedó una sin terminar
        self.stackedWidget.currentChanged.connect(self._on_section_changed)

    # ── Señales que cruzan de una sección a otra ─────────────────────

    def _wire_cross_section_signals(self) -> None:
        # Perfil de cliente -> "Nueva evaluación" salta directo al Paso 1
        self.clients_container.start_evaluation_requested.connect(self._start_evaluation_for_client)
        # Perfil de cliente -> ver reporte de una sesión pasada
        self.clients_container.view_report_requested.connect(self._open_report)
        # Historial -> ver reporte de una sesión
        self.history_view.session_selected.connect(self._open_report)
        # Vista general -> ver reporte de una evaluación reciente
        self.dashboard_view.session_selected.connect(self._open_report)
        # Historial -> retomar una evaluación en curso
        self.history_view.resume_session_requested.connect(self._resume_evaluation)

        # Vista general -> atajos a las otras secciones
        self.dashboard_view.new_evaluation_requested.connect(
            lambda: self.switchTo(self.eval_wizard)
        )
        self.dashboard_view.clients_requested.connect(self._open_clients)
        self.dashboard_view.sensors_requested.connect(
            lambda: self.switchTo(self.sensors_view)
        )
        self.dashboard_view.client_selected.connect(self._open_client_profile)

        # Reporte -> volver a donde se venía
        self.report_view.back_requested.connect(self._leave_report)

        # Al completarse una evaluación (Paso 6), refrescar las pantallas
        # que dependen de datos que el wizard acaba de guardar.
        self.eval_wizard.evaluation_completed.connect(self._refresh_all)

        # Borrar una evaluación cambia cifras que otras secciones ya
        # tienen dibujadas, así que se refrescan todas.
        self.history_view.data_changed.connect(self._refresh_all)
        self.clients_container.data_changed.connect(self._refresh_all)

        # Badge de evaluaciones pendientes
        self.eval_wizard.pending_changed.connect(self.refresh_pending_badge)

        # Cerrar sesión desde Mi perfil
        self.profile_view.logout_requested.connect(self._on_logout)

    def _refresh_all(self) -> None:
        self.history_view.reload()
        self.dashboard_view.refresh()
        self.clients_container.list_view.reload()
        self.refresh_pending_badge()

    def _on_section_changed(self, _index: int) -> None:
        current = self.stackedWidget.currentWidget()
        if current is self.eval_wizard:
            self.eval_wizard.check_pending_evaluation()
        elif current is self.history_view:
            self.history_view.reload()
        elif current is self.clients_container:
            self.clients_container.list_view.reload()

    def _start_evaluation_for_client(self, client) -> None:
        self.eval_wizard.start_for_client(client)
        self.switchTo(self.eval_wizard)

    def _resume_evaluation(self, session_id: int) -> None:
        self.eval_wizard.resume_session(session_id)
        self.switchTo(self.eval_wizard)

    def _open_clients(self) -> None:
        self.clients_container.show_list()
        self.switchTo(self.clients_container)

    def _open_client_profile(self, client) -> None:
        self.clients_container.show_profile(client)
        self.switchTo(self.clients_container)

    def _open_report(self, session_id: int) -> None:
        # Se recuerda de dónde se llegó para que el botón de volver del
        # reporte regrese ahí y no a una sección fija. El reporte se
        # abre desde la vista general, el historial y el perfil de un
        # cliente, y en los tres casos "volver" significa algo distinto.
        current = self.stackedWidget.currentWidget()
        if current is not self.report_view:
            self._report_origin = current
        self.report_view.load_session(session_id)
        self.switchTo(self.report_view)

    def _leave_report(self) -> None:
        self.switchTo(self._report_origin or self.dashboard_view)

    # ── Badge de evaluaciones pendientes ─────────────────────────────

    def refresh_pending_badge(self) -> None:
        """Muestra un contador junto a 'Nueva evaluación' si hay
        evaluaciones sin terminar."""
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
        self.state.shutdown()
        self.logout_requested.emit()
        self.close()

    def _on_close(self, event) -> None:
        self.state.shutdown()
        event.accept()