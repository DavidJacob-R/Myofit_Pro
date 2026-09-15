"""
Historial sEMG — lista de tarjetas en vez de tabla.

Cada tarjeta muestra cliente, músculo, fecha, score y una mini-gráfica
(Sparkline) de la señal real guardada en DuckDB. Las evaluaciones en
curso se destacan con borde ámbar y ofrecen "Retomar" o "Cancelar"
ahí mismo, para que ninguna quede colgada indefinidamente.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox, PushButton

from myofit_pro.database.models import EvaluationStatus
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_RED,
    BG_CARD,
    BG_CARD_HOVER,
    BORDER,
    BORDER_STRONG,
    RADIUS_CARD,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Avatar,
    EmptyState,
    PageHeader,
    Pill,
    Sparkline,
    score_color,
)

_ALL_CLIENTS = "Todos los clientes"


class _SessionCard(QWidget):
    """Tarjeta de una evaluación en el historial."""

    resume_requested = Signal(int)   # session_id
    cancel_requested = Signal(int)   # session_id
    open_requested = Signal(int)     # session_id

    def __init__(
        self,
        session,
        client_name: str,
        muscle_name: str,
        signal_values: list[float],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("sessionCard")
        # Sin WA_StyledBackground un QWidget ignora el background-color de
        # la hoja de estilo y la tarjeta sale sin fondo ni borde.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.session = session
        in_progress = session.status == EvaluationStatus.IN_PROGRESS.value
        cancelled = session.status == EvaluationStatus.CANCELLED.value

        self._accent = ACCENT_AMBER if in_progress else BORDER
        self._interactive = session.status == EvaluationStatus.COMPLETED.value
        self._apply_style(hover=False)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 13, 18, 13)
        outer.setSpacing(14)
        outer.addWidget(Avatar(client_name, size=44))

        # ── Columna central: textos + sparkline ───────────────────
        left = QVBoxLayout()
        left.setSpacing(5)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(f"{client_name}  ·  {muscle_name}")
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        title_row.addWidget(title)

        if in_progress:
            title_row.addWidget(Pill("En curso", ACCENT_AMBER))
        elif cancelled:
            title_row.addWidget(Pill("Cancelada", ACCENT_RED))
        title_row.addStretch(1)
        left.addLayout(title_row)

        reps = session.results[0].series_count if session.results else 0
        detail_parts = [
            session.started_at.strftime("%d/%m/%Y · %H:%M"),
            session.goal,
        ]
        if in_progress:
            detail_parts.append("sin terminar")
        elif cancelled:
            detail_parts.append("cancelada")
        else:
            detail_parts.append(f"{reps} repeticiones")

        detail = QLabel("  ·  ".join(detail_parts))
        detail.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent; border: none;"
        )
        left.addWidget(detail)

        if signal_values and not in_progress and not cancelled:
            spark = Sparkline(signal_values, score_color(session.overall_score))
            spark.setMaximumWidth(280)
            spark.setStyleSheet("background: transparent; border: none;")
            left.addWidget(spark)

        outer.addLayout(left, stretch=1)

        # ── Columna derecha: score o acciones ─────────────────────
        if in_progress:
            actions = QHBoxLayout()
            actions.setSpacing(6)
            resume_btn = PushButton("Retomar")
            resume_btn.clicked.connect(lambda: self.resume_requested.emit(session.id))
            cancel_btn = PushButton("Cancelar")
            cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(session.id))
            actions.addWidget(resume_btn)
            actions.addWidget(cancel_btn)
            outer.addLayout(actions)
        else:
            score_col = QVBoxLayout()
            score_col.setSpacing(0)
            score_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            score_text = (
                f"{session.overall_score:.0f}%" if session.overall_score is not None else "—"
            )
            score_label = QLabel(score_text)
            score_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            score_label.setStyleSheet(
                f"color: {score_color(session.overall_score)}; font-size: 23px; "
                f"font-weight: 800; letter-spacing: -0.4px; "
                f"background: transparent; border: none;"
            )
            caption = QLabel("score")
            caption.setAlignment(Qt.AlignmentFlag.AlignRight)
            caption.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 600; "
                f"letter-spacing: 0.3px; background: transparent; border: none;"
            )
            score_col.addWidget(score_label)
            score_col.addWidget(caption)
            outer.addLayout(score_col)

            if self._interactive:
                chevron = QLabel("›")
                chevron.setStyleSheet(
                    f"color: {TEXT_MUTED}; font-size: 20px; font-weight: 700; "
                    f"background: transparent; border: none;"
                )
                outer.addWidget(chevron)
                self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _apply_style(self, hover: bool) -> None:
        bg = BG_CARD_HOVER if hover else BG_CARD
        border = BORDER_STRONG if hover else self._accent
        self.setStyleSheet(
            f"QWidget#sessionCard {{ background-color: {bg}; "
            f"border-radius: {RADIUS_CARD}px; border: 1px solid {border}; }}"
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        if self._interactive:
            self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._interactive:
            self._apply_style(hover=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._interactive and event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self.session.id)
        super().mouseReleaseEvent(event)


class HistoryView(QWidget):
    session_selected = Signal(int)          # abrir reporte
    resume_session_requested = Signal(int)  # retomar evaluación en curso

    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._sessions = []
        self._clients = []
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.addWidget(
            PageHeader("Historial sEMG", "Clic en una evaluación para ver su reporte")
        )
        header_row.addStretch(1)
        refresh_btn = PushButton("↻  Actualizar")
        refresh_btn.clicked.connect(self.reload)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)

        filter_row = QHBoxLayout()
        filter_label = QLabel("Filtrar:")
        filter_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        filter_row.addWidget(filter_label)
        self.client_filter = ComboBox(self)
        self.client_filter.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.client_filter, stretch=1)
        layout.addLayout(filter_row)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._list_host = QWidget()
        self._list_host.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self._list_host)
        self.list_layout.setSpacing(10)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._list_host)
        layout.addWidget(scroll, stretch=1)

        self.empty_state = EmptyState(
            "📊",
            "Todavía no hay evaluaciones registradas.\n"
            "Ve a 'Nueva evaluación' para hacer la primera.",
        )
        layout.addWidget(self.empty_state)

    def reload(self) -> None:
        self._sessions = self.state.evaluation_repo.list_for_trainer_with_results(
            self.state.current_trainer.id
        )
        self._clients = self.state.client_repo.list_for_trainer(self.state.current_trainer.id)

        current = self.client_filter.currentText()
        self.client_filter.blockSignals(True)
        self.client_filter.clear()
        self.client_filter.addItems([_ALL_CLIENTS] + [c.full_name for c in self._clients])
        if current and current in [_ALL_CLIENTS] + [c.full_name for c in self._clients]:
            self.client_filter.setCurrentText(current)
        self.client_filter.blockSignals(False)

        self._apply_filter()

    def _apply_filter(self) -> None:
        selected = self.client_filter.currentText()
        if selected and selected != _ALL_CLIENTS:
            client = next((c for c in self._clients if c.full_name == selected), None)
            sessions = [s for s in self._sessions if client and s.client_id == client.id]
        else:
            sessions = self._sessions

        self._render_sessions(sessions)

    def _render_sessions(self, sessions) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.empty_state.setVisible(len(sessions) == 0)
        self._list_host.setVisible(len(sessions) > 0)

        for session in sessions:
            client = self.state.client_repo.get(session.client_id)
            muscle = self.state.muscle_repo.get(session.muscle_id)
            signal_values = self._load_signal_preview(session.id)

            card = _SessionCard(
                session=session,
                client_name=client.full_name if client else "—",
                muscle_name=muscle.name if muscle else "—",
                signal_values=signal_values,
            )
            card.open_requested.connect(self.session_selected.emit)
            card.resume_requested.connect(self.resume_session_requested.emit)
            card.cancel_requested.connect(self._on_cancel_requested)
            self.list_layout.addWidget(card)

    def _load_signal_preview(self, session_id: int, points: int = 60) -> list[float]:
        """
        Saca una versión reducida de la envolvente guardada en DuckDB
        para dibujar el sparkline. Si no hay ráfaga guardada para esa
        sesión, devuelve lista vacía y la tarjeta simplemente no
        muestra gráfica (en vez de inventar datos).
        """
        try:
            df = self.state.burst_store.load_bursts_for_session(session_id)
        except Exception:
            return []

        if df is None or len(df) == 0:
            return []

        envelope = df.iloc[0].get("envelope")
        if envelope is None or len(envelope) < 2:
            return []

        values = np.asarray(envelope, dtype=float)
        if len(values) > points:
            step = len(values) // points
            values = values[::step][:points]
        return values.tolist()

    def _on_cancel_requested(self, session_id: int) -> None:
        confirm = QMessageBox.question(
            self,
            "Cancelar evaluación",
            "¿Marcar esta evaluación como cancelada?\n\n"
            "Se conserva en el historial pero ya no aparecerá como pendiente.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.evaluation_repo.cancel_session(session_id)
            self.reload()