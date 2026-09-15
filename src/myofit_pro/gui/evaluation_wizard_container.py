"""
Contenedor del wizard de evaluación completo (6 pasos).

Se registra UNA sola vez en el sidebar de MainWindow ("Nueva evaluación").
Internamente usa su propio QStackedWidget para moverse entre pasos, sin
depender de qfluentwidgets.FluentWindow.switchTo() -- eso evita que cada
paso aparezca como una entrada suelta en el menú lateral.

Header persistente: título del paso actual + indicador de progreso
(StepProgressBar) siempre visible arriba, se actualiza en cada
transición. Los pasos 4 y 5 se crean dinámicamente al llegar a ellos,
porque dependen de qué músculo/cliente se eligió en los pasos previos.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import StrongBodyLabel

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.evaluation_step2_view import EvaluationStep2View
from myofit_pro.gui.evaluation_step3_view import EvaluationStep3View
from myofit_pro.gui.evaluation_step4_view import EvaluationStep4View
from myofit_pro.gui.evaluation_step5_view import EvaluationStep5View
from myofit_pro.gui.evaluation_step6_view import EvaluationStep6View
from myofit_pro.gui.evaluation_wizard import EvaluationStartView, EvaluationStep1View
from myofit_pro.gui.theme import StepProgressBar

_STEP_TITLES = [
    "Cliente y objetivo",
    "Músculo a evaluar",
    "Colocación de electrodos",
    "Verificación de conexión",
    "Calibración MVC",
    "Evaluación en vivo",
    "Reporte",
]


class EvaluationWizardContainer(QWidget):
    evaluation_completed = Signal()   # se emite cuando el Paso 6 se muestra (datos ya guardados)
    pending_changed = Signal()        # cambió el número de evaluaciones en curso (badge del sidebar)

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(24, 20, 24, 24)
        outer_layout.setSpacing(16)

        # ── Header persistente: título + progreso ────────────────────
        header_row = QHBoxLayout()
        self.step_title_label = StrongBodyLabel(_STEP_TITLES[0])
        header_row.addWidget(self.step_title_label)
        header_row.addStretch(1)
        self.progress_bar = StepProgressBar(total_steps=6)
        self.progress_bar.setMaximumWidth(280)
        header_row.addWidget(self.progress_bar)
        outer_layout.addLayout(header_row)

        # ── Contenido del paso actual ─────────────────────────────────
        self.stack = QStackedWidget(self)
        outer_layout.addWidget(self.stack, stretch=1)

        # Pasos fijos (no dependen de contexto elegido dinámicamente)
        self.start_view = EvaluationStartView(state)
        self.step1_view = EvaluationStep1View(state)
        self.step2_view = EvaluationStep2View(state)
        self.step3_view = EvaluationStep3View(state)

        for w in (self.start_view, self.step1_view, self.step2_view, self.step3_view):
            self.stack.addWidget(w)

        # Pasos dinámicos (se crean al llegar, ver _go_to_step4/5/6)
        self.step4_view: EvaluationStep4View | None = None
        self.step5_view: EvaluationStep5View | None = None
        self.step6_view: EvaluationStep6View | None = None

        self.start_view.started.connect(self._go_to_step1)
        self.step1_view.muscle_selected.connect(self._go_to_step2)
        self.step2_view.ready_to_continue.connect(self._go_to_step3)
        self.step3_view.connection_verified.connect(self._go_to_step4)

        self._show(self.start_view, header_text="Nueva evaluación", progress_step=0)

    # ── Navegación interna ───────────────────────────────────────────

    def _show(self, widget: QWidget, header_text: str, progress_step: int) -> None:
        self.stack.setCurrentWidget(widget)
        self.step_title_label.setText(header_text)
        self.progress_bar.set_current(progress_step)

    def _go_to_step1(self) -> None:
        self.step1_view.reload()
        self._show(self.step1_view, f"Paso 1 de 6 — {_STEP_TITLES[1]}", 1)

    def _go_to_step2(self) -> None:
        self.pending_changed.emit()
        self.step2_view.refresh()
        self._show(self.step2_view, f"Paso 2 de 6 — {_STEP_TITLES[2]}", 2)

    def _go_to_step3(self) -> None:
        self._show(self.step3_view, f"Paso 3 de 6 — {_STEP_TITLES[3]}", 3)

    def _go_to_step4(self) -> None:
        if self.step4_view is not None:
            self.stack.removeWidget(self.step4_view)
            self.step4_view.deleteLater()

        self.step4_view = EvaluationStep4View(self.state)
        self.step4_view.calibration_saved.connect(self._go_to_step5)
        self.stack.addWidget(self.step4_view)
        self._show(self.step4_view, f"Paso 4 de 6 — {_STEP_TITLES[4]}", 4)

    def _go_to_step5(self) -> None:
        if self.step5_view is not None:
            self.stack.removeWidget(self.step5_view)
            self.step5_view.deleteLater()

        self.step5_view = EvaluationStep5View(self.state)
        self.step5_view.evaluation_finished.connect(self._go_to_step6)
        self.stack.addWidget(self.step5_view)
        self._show(self.step5_view, f"Paso 5 de 6 — {_STEP_TITLES[5]}", 5)

    def _go_to_step6(self) -> None:
        if self.step6_view is not None:
            self.stack.removeWidget(self.step6_view)
            self.step6_view.deleteLater()

        self.step6_view = EvaluationStep6View(self.state)
        self.step6_view.start_new_evaluation.connect(self.reset_to_start)
        self.stack.addWidget(self.step6_view)
        self._show(self.step6_view, f"Paso 6 de 6 — {_STEP_TITLES[6]}", 6)
        self.evaluation_completed.emit()
        self.pending_changed.emit()

    def reset_to_start(self) -> None:
        """Vuelve al inicio del wizard para empezar una evaluación nueva."""
        self.state.active_client = None
        self.state.active_muscle = None
        self.state.active_session_id = None
        self.state.active_mvc = None
        self.start_view.reload()
        self._show(self.start_view, "Nueva evaluación", 0)

    def start_for_client(self, client) -> None:
        """
        Salta directo al Paso 1 (elegir músculo) con el cliente ya
        elegido -- usado por el botón "Nueva evaluación" del perfil de
        cliente, para no obligar a re-seleccionarlo en el Paso 0.
        """
        self.state.active_client = client
        self.state.active_goal = client.goal
        self._go_to_step1()

    # ── Evaluaciones en curso ────────────────────────────────────────

    def check_pending_evaluation(self) -> None:
        """
        Llamar al navegar a esta sección: si hay una evaluación sin
        terminar, ofrece retomarla o descartarla en vez de dejarla
        colgada para siempre.
        """
        pending = self.state.evaluation_repo.find_in_progress(
            self.state.current_trainer.id
        )
        if pending is None:
            return
        # Si ya estamos trabajando en esa misma sesión, no molestar
        if self.state.active_session_id == pending.id:
            return

        client = self.state.client_repo.get(pending.client_id)
        muscle = self.state.muscle_repo.get(pending.muscle_id)

        box = QMessageBox(self)
        box.setWindowTitle("Evaluación sin terminar")
        box.setText(
            f"Tienes una evaluación sin terminar:\n\n"
            f"{client.full_name if client else '—'} · {muscle.name if muscle else '—'}\n"
            f"Iniciada el {pending.started_at.strftime('%d/%m/%Y a las %H:%M')}"
        )
        resume_btn = box.addButton("Retomar", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Ahora no", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked == resume_btn:
            self.resume_session(pending.id)
        elif clicked == discard_btn:
            self.state.evaluation_repo.cancel_session(pending.id)
            self.pending_changed.emit()

    def resume_session(self, session_id: int) -> None:
        """
        Retoma una evaluación en curso: recarga su contexto (cliente,
        músculo, MVC si ya se calibró) y salta al paso donde se quedó.
        """
        session = self.state.evaluation_repo.get_with_results(session_id)
        if session is None:
            return

        client = self.state.client_repo.get(session.client_id)
        muscle = self.state.muscle_repo.get(session.muscle_id)
        if client is None or muscle is None:
            return

        self.state.set_eval_context(client, muscle, session.goal)
        self.state.active_session_id = session.id

        if session.mvc_calibration_id:
            # Ya se había calibrado: retomar directo en la evaluación en vivo
            self.state.active_mvc = self.state.calibration_repo.get(
                session.mvc_calibration_id
            )
            self._go_to_step5()
        else:
            # Falta calibrar: retomar en la guía de colocación
            self._go_to_step2()