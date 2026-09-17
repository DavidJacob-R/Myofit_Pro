"""
Contenedor del wizard de evaluación completo (6 pasos).

Se registra UNA sola vez en el sidebar de MainWindow ("Nueva evaluación").
Internamente usa su propio QStackedWidget para moverse entre pasos, sin
depender de qfluentwidgets.FluentWindow.switchTo() -- eso evita que cada
paso aparezca como una entrada suelta en el menú lateral.

Header persistente: el nombre del paso, una línea que dice qué se espera
del entrenador, y el indicador de progreso. Nada más.

El encabezado decía tres veces lo mismo: un círculo con el número, el
texto "Paso 2 de 6" y la barra de progreso marcando el 2. Ahora solo
queda la barra, que es la única de las tres que además dice cuánto
falta. También se quitó la fila de píldoras con cliente y músculo: ese
dato ya lo eligió el entrenador dos pantallas antes y repetirlo en cada
paso solo agrega ruido.

Los pasos 4, 5 y 6 se crean al llegar a ellos, porque dependen de qué
músculo y cliente se eligieron antes.

Navegación: el contenedor lleva la pila de pasos visitados, en vez de que
cada vista sepa de dónde vino. Así el botón de volver siempre regresa a
donde el entrenador estaba de verdad, incluso cuando se retoma una
evaluación a la mitad y se entra directo al Paso 5.

Los dos botones de navegación viven juntos en un pie único, no uno
arriba y otro al final del contenido de cada paso. El contenedor le
pregunta al paso actual qué dice su botón de continuar, si se puede
presionar y qué hacer al presionarlo (ver `wizard_step.WizardStep`).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import PrimaryPushButton

from myofit_pro.database.models import EvaluationStatus
from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.evaluation_step2_view import EvaluationStep2View
from myofit_pro.gui.evaluation_step3_view import EvaluationStep3View
from myofit_pro.gui.evaluation_step4_view import EvaluationStep4View
from myofit_pro.gui.evaluation_step5_view import EvaluationStep5View
from myofit_pro.gui.evaluation_step6_view import EvaluationStep6View
from myofit_pro.gui.evaluation_wizard import EvaluationStartView, EvaluationStep1View
from myofit_pro.gui.theme import (
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    BackButton,
    Card,
    StepProgressBar,
)
from myofit_pro.gui.wizard_step import WizardStep

# Pantalla inicial (elegir cliente) + los 6 pasos numerados.
_START = 0
_LAST_STEP = 6

_STEP_TITLES = [
    "Cliente y objetivo",
    "Músculo a evaluar",
    "Colocación de electrodos",
    "Verificación de conexión",
    "Calibración MVC",
    "Batería de ejercicios",
    "Reporte",
]

# Qué se espera del entrenador en cada paso. Va en el header porque el
# contenido de algunos pasos es solo una gráfica y dos botones, y sin
# esta línea no queda claro qué hay que hacer.
_STEP_CAPTIONS = [
    "Elige con quién vas a trabajar y con qué objetivo",
    "Elige el músculo que vas a medir",
    "Coloca los dos sensores como indica la guía",
    "Confirma que ambos sensores están enviando buena señal",
    "Registra la contracción máxima que sirve de referencia",
    "Mide cada ejercicio y compara cuál activa más a este cliente",
    "Ranking de ejercicios y resultado, ya guardado",
]


class EvaluationWizardContainer(QWidget):
    evaluation_completed = Signal()   # se emite cuando el Paso 6 se muestra (datos ya guardados)
    pending_changed = Signal()        # cambió el número de evaluaciones en curso (badge del sidebar)

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state

        self._current_step = _START
        self._history: list[int] = []

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(24, 20, 24, 24)
        outer_layout.setSpacing(16)

        self._header_card = self._build_header()
        outer_layout.addWidget(self._header_card)

        # ── Contenido del paso actual ─────────────────────────────────
        self.stack = QStackedWidget(self)
        outer_layout.addWidget(self.stack, stretch=1)

        outer_layout.addLayout(self._build_footer())

        # Pasos fijos (no dependen de contexto elegido dinámicamente)
        self.start_view = EvaluationStartView(state)
        self.step1_view = EvaluationStep1View(state)
        self.step2_view = EvaluationStep2View(state)
        self.step3_view = EvaluationStep3View(state)

        for w in (self.start_view, self.step1_view, self.step2_view, self.step3_view):
            self.stack.addWidget(w)

        # Pasos dinámicos (se crean al llegar, ver _enter_step)
        self.step4_view: EvaluationStep4View | None = None
        self.step5_view: EvaluationStep5View | None = None
        self.step6_view: EvaluationStep6View | None = None

        # El avance lo dispara el botón del pie vía `on_continue()`, no
        # cada vista por su cuenta. Lo que sí hace falta es enterarse de
        # cuándo cambia si se puede continuar, porque el botón vive fuera
        # del paso.
        for view in (self.start_view, self.step1_view, self.step2_view, self.step3_view):
            view.continue_state_changed.connect(self._refresh_footer)

        self._enter_step(_START, record_previous=False)

    # ── Header ───────────────────────────────────────────────────────

    def _build_header(self) -> Card:
        card = Card()

        row = QHBoxLayout()
        row.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)

        self.step_title_label = QLabel(_STEP_TITLES[0])
        self.step_title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 19px; font-weight: 750; "
            f"letter-spacing: -0.3px; background: transparent; border: none;"
        )
        title_col.addWidget(self.step_title_label)

        self.step_caption_label = QLabel(_STEP_CAPTIONS[0])
        self.step_caption_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; "
            f"background: transparent; border: none;"
        )
        title_col.addWidget(self.step_caption_label)

        row.addLayout(title_col, stretch=1)

        self.progress_bar = StepProgressBar(total_steps=6)
        self.progress_bar.setMaximumWidth(260)
        row.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignVCenter)

        card.body.addLayout(row)
        return card

    def _build_footer(self) -> QHBoxLayout:
        """
        Pie común a todos los pasos: volver y continuar, juntos.

        El de continuar ocupa el resto del ancho porque es la acción
        principal, y el de volver queda a su izquierda, que es donde el
        usuario ya lo buscaba.
        """
        row = QHBoxLayout()
        row.setSpacing(10)

        self.back_btn = BackButton("Volver")
        self.back_btn.clicked.connect(self.go_back)
        row.addWidget(self.back_btn)

        self.next_btn = PrimaryPushButton(WizardStep.CONTINUE_LABEL)
        self.next_btn.clicked.connect(self._on_continue_clicked)
        row.addWidget(self.next_btn, stretch=1)
        return row

    def _current_view(self) -> WizardStep | None:
        widget = self.stack.currentWidget()
        return widget if isinstance(widget, WizardStep) else None

    def _refresh_footer(self) -> None:
        """Sincroniza el pie con lo que dice el paso actual."""
        view = self._current_view()
        if view is None:
            return
        self.next_btn.setText(view.CONTINUE_LABEL)
        self.next_btn.setEnabled(view.can_continue())
        self.back_btn.setVisible(bool(self._history))

    def _on_continue_clicked(self) -> None:
        view = self._current_view()
        if view is None:
            return

        if not view.can_continue():
            QMessageBox.information(self, "Falta un paso", view.blocked_reason())
            return

        if view.on_continue():
            self.go_to(self._current_step + 1)

    def _refresh_header(self, step: int) -> None:
        title_index = min(step, len(_STEP_TITLES) - 1)
        if step == _START:
            self.step_title_label.setText("Nueva evaluación")
            self.step_caption_label.setText(_STEP_CAPTIONS[0])
        else:
            self.step_title_label.setText(_STEP_TITLES[title_index])
            self.step_caption_label.setText(_STEP_CAPTIONS[title_index])

        self.progress_bar.set_current(step)
        self._refresh_footer()

    # ── Navegación interna ───────────────────────────────────────────

    def go_to(self, step: int) -> None:
        """Avanza a un paso, recordando el actual para poder volver."""
        self._enter_step(step, record_previous=True)

    def go_back(self) -> None:
        """
        Regresa al paso anterior.

        Salir del Paso 2 hacia el 1 tiene un efecto secundario que hay
        que deshacer: la sesión de evaluación se crea al elegir el
        músculo, así que si no se descartara aquí, cada ida y vuelta
        dejaría una evaluación vacía marcada como "en curso" y el badge
        del menú lateral iría subiendo solo.
        """
        if not self._history:
            return

        previous = self._history.pop()

        if self._current_step >= 2 and previous <= 1:
            self._discard_empty_session()

        self._enter_step(previous, record_previous=False)

    def _discard_empty_session(self) -> None:
        session_id = self.state.active_session_id
        if session_id is None:
            return

        session = self.state.evaluation_repo.get_with_results(session_id)
        # Solo se borra si de verdad quedó vacía. Una evaluación con
        # resultados ya es dato del cliente y no se toca desde aquí.
        if session is not None and not session.results and (
            session.status == EvaluationStatus.IN_PROGRESS.value
        ):
            self.state.delete_evaluation(session_id)
            self.pending_changed.emit()

        self.state.active_session_id = None

    def _enter_step(self, step: int, record_previous: bool) -> None:
        if record_previous:
            self._history.append(self._current_step)

        widget = self._prepare_step(step)
        self._current_step = step
        self.stack.setCurrentWidget(widget)
        if isinstance(widget, WizardStep):
            widget.on_enter()
        self._refresh_header(step)

    def _prepare_step(self, step: int) -> QWidget:
        """Deja listo el widget de un paso y lo devuelve."""
        if step == _START:
            return self.start_view

        if step == 1:
            return self.step1_view

        if step == 2:
            self.pending_changed.emit()
            return self.step2_view

        if step == 3:
            return self.step3_view

        if step == 4:
            return self._rebuild_step4()

        if step == 5:
            return self._rebuild_step5()

        return self._rebuild_step6()

    def _dispose(self, old: QWidget | None) -> None:
        """
        Quita del stack la instancia anterior de un paso dinámico.

        Estos pasos se reconstruyen en vez de reutilizarse porque cada
        uno se suscribe a las señales del servicio de sensores y guarda
        los buffers de su captura. Volver a un paso de medición tiene
        que empezar de cero, no continuar la medición pasada.
        """
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()

    def _rebuild_step4(self) -> QWidget:
        self._dispose(self.step4_view)
        view = EvaluationStep4View(self.state)
        view.continue_state_changed.connect(self._refresh_footer)
        self.stack.addWidget(view)
        self.step4_view = view
        return view

    def _rebuild_step5(self) -> QWidget:
        self._dispose(self.step5_view)
        view = EvaluationStep5View(self.state)
        view.continue_state_changed.connect(self._refresh_footer)
        self.stack.addWidget(view)
        self.step5_view = view
        return view

    def _rebuild_step6(self) -> QWidget:
        self._dispose(self.step6_view)
        view = EvaluationStep6View(self.state)
        view.start_new_evaluation.connect(self.reset_to_start)
        self.stack.addWidget(view)
        self.step6_view = view
        # El reporte es el final del flujo: volver atrás desde aquí
        # llevaría a repetir una medición que ya se guardó.
        self._history.clear()
        self.evaluation_completed.emit()
        self.pending_changed.emit()
        return view

    def reset_to_start(self) -> None:
        """Vuelve al inicio del wizard para empezar una evaluación nueva."""
        self.state.active_client = None
        self.state.active_muscle = None
        self.state.active_session_id = None
        self.state.set_active_mvc(None)
        self._history.clear()
        self._enter_step(_START, record_previous=False)

    def start_for_client(self, client) -> None:
        """
        Salta directo al Paso 1 (elegir músculo) con el cliente ya
        elegido -- usado por el botón "Nueva evaluación" del perfil de
        cliente, para no obligar a re-seleccionarlo en el Paso 0.
        """
        self.state.active_client = client
        self.state.active_goal = client.goal
        self._history.clear()
        self._enter_step(1, record_previous=True)

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

        # Se entra directo al paso donde quedó, así que la pila arranca
        # vacía: no hay pasos previos que el entrenador haya visto en
        # esta pasada y a los que tenga sentido regresar.
        self._history.clear()

        if session.mvc_calibration_id:
            # Ya se había calibrado: retomar directo en la evaluación en vivo
            self.state.set_active_mvc(
                self.state.calibration_repo.get(session.mvc_calibration_id)
            )
            self._enter_step(5, record_previous=False)
        else:
            # Falta calibrar: retomar en la guía de colocación
            self._enter_step(2, record_previous=False)
