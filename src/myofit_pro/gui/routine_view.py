"""
Rutina generada — equivalente a RoutineView.xaml. Genera una rutina
básica a partir de los músculos que el cliente ya tiene evaluados
(con MVC calculado): para cada músculo evaluado, toma hasta 2
ejercicios del catálogo (ExerciseRepository) con 3x12 por defecto.

Si no hay ejercicios cargados en el catálogo para esos músculos, lo
dice explícitamente en vez de generar una rutina vacía sin explicación.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, StrongBodyLabel
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.theme import ACCENT_VIOLET, Card, EmptyState, PageHeader, StatCard


class RoutineView(QWidget):
    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._clients = []
        self._build_ui()
        self.reload_clients()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(
            PageHeader("Rutina generada", "Basada en los músculos que el cliente ya tiene evaluados")
        )

        picker_card = Card()
        picker_row = QHBoxLayout()
        picker_row.addWidget(BodyLabel("Cliente:"))
        self.client_combo = ComboBox(picker_card)
        self.client_combo.currentIndexChanged.connect(self._on_client_changed)
        picker_row.addWidget(self.client_combo, stretch=1)
        picker_card.body.addLayout(picker_row)

        self.generate_btn = PrimaryPushButton("⚙️  Generar rutina a partir de evaluaciones")
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        picker_card.body.addWidget(self.generate_btn)
        layout.addWidget(picker_card)

        self.summary_card = StatCard(FIF.CALORIES, ACCENT_VIOLET, "Rutina actual", "—")
        layout.addWidget(self.summary_card)

        self.exercises_card = Card()
        self.exercises_card.body.addWidget(StrongBodyLabel("Ejercicios"))
        self.exercises_label = BodyLabel("Selecciona un cliente para ver su rutina.")
        self.exercises_label.setWordWrap(True)
        self.exercises_card.body.addWidget(self.exercises_label)

        self.empty_state = EmptyState(
            "🗒️",
            "Este cliente no tiene una rutina generada.\n"
            "Usa el botón de arriba para crear una a partir de sus evaluaciones.",
        )
        self.exercises_card.body.addWidget(self.empty_state)

        layout.addWidget(self.exercises_card, stretch=1)

    def reload_clients(self) -> None:
        self._clients = self.state.client_repo.list_for_trainer(self.state.current_trainer.id)
        self.client_combo.clear()
        self.client_combo.addItems([c.full_name for c in self._clients])
        if self._clients:
            self._show_routine_for_client(self._clients[0])

    def _on_client_changed(self, index: int) -> None:
        if 0 <= index < len(self._clients):
            self._show_routine_for_client(self._clients[index])

    def _current_client(self):
        idx = self.client_combo.currentIndex()
        if 0 <= idx < len(self._clients):
            return self._clients[idx]
        return None

    def _show_routine_for_client(self, client) -> None:
        routine = self.state.routine_repo.get_for_client(client.id)

        if routine is None:
            self.summary_card.set_value("Sin generar")
            self.exercises_label.setVisible(False)
            self.empty_state.setVisible(True)
            return

        if not routine.exercises:
            self.summary_card.set_value(routine.name)
            self.exercises_label.setVisible(True)
            self.exercises_label.setText("La rutina no tiene ejercicios asignados.")
            self.empty_state.setVisible(False)
            return

        self.summary_card.set_value(f"{len(routine.exercises)} ejercicios")
        self.empty_state.setVisible(False)
        self.exercises_label.setVisible(True)

        lines = []
        for re in sorted(routine.exercises, key=lambda x: x.order_index):
            exercise = self.state.exercise_repo.get(re.exercise_id)
            name = exercise.name if exercise else f"Ejercicio #{re.exercise_id}"
            lines.append(f"•  {name}  —  {re.sets} × {re.reps}")
        self.exercises_label.setText("\n".join(lines))

    def _on_generate_clicked(self) -> None:
        client = self._current_client()
        if client is None:
            return

        calibrations = self.state.calibration_repo.list_for_client(client.id)
        if not calibrations:
            QMessageBox.information(
                self, "Sin evaluaciones",
                "Este cliente todavía no tiene músculos evaluados. "
                "Haz una evaluación primero para poder generar una rutina.",
            )
            return

        # Un músculo por calibración distinta (ya viene ordenado por más reciente)
        seen_muscles: set[int] = set()
        muscle_ids = []
        for calib in calibrations:
            if calib.muscle_id not in seen_muscles:
                seen_muscles.add(calib.muscle_id)
                muscle_ids.append(calib.muscle_id)

        routine = self.state.routine_repo.create(
            client_id=client.id, name=f"Rutina — {client.goal}"
        )

        order_index = 0
        exercises_added = 0
        for muscle_id in muscle_ids:
            exercises = self.state.exercise_repo.list_for_muscle(muscle_id)
            for exercise in exercises[:2]:  # hasta 2 ejercicios por músculo evaluado
                self.state.routine_repo.add_exercise(
                    routine_id=routine.id,
                    exercise_id=exercise.id,
                    sets=3,
                    reps=12,
                    order_index=order_index,
                )
                order_index += 1
                exercises_added += 1

        if exercises_added == 0:
            QMessageBox.warning(
                self, "Catálogo vacío",
                "Se creó la rutina pero no hay ejercicios cargados en el catálogo "
                "para los músculos evaluados de este cliente.",
            )

        self._show_routine_for_client(client)