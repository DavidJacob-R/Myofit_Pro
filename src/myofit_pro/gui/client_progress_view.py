"""
Progreso de un cliente: la evaluación más reciente contra la anterior.

QUÉ SE COMPARA Y POR QUÉ ASÍ
============================

Ejercicio por ejercicio, y no el score de la sesión. El score de una
sesión es el promedio de las series que se midieron ese día: si en la
evaluación 1 mediste curl con barra, martillo y concentrado, y en la 2
mediste barra, predicador y araña, los dos promedios no son comparables
— cambiaron los ejercicios, no la persona.

Siempre las dos últimas. Cuando se hace una evaluación nueva, la que era
"actual" pasa a ser "anterior" y la vieja deja de mostrarse. Pero cada
ejercicio lleva su mini-gráfica con todas sus mediciones históricas,
porque a la cuarta evaluación la trayectoria dice más que el último
salto: tres subidas seguidas son una tendencia, una subida sola puede
ser el día.

LO QUE ESTA PANTALLA NO AFIRMA
==============================

Que el músculo creció. Eso lo dice la cinta métrica (la circunferencia
que se captura en el Paso 5), no la señal. El sEMG mide actividad
eléctrica, y más actividad puede venir de mejor técnica, de menos grasa
entre el músculo y el electrodo, o de un electrodo colocado más cerca
del punto motor. Por eso el crecimiento se muestra como un dato aparte y
solo si se midió.

El veredicto de cada ejercicio lo decide `progress.py`, que es lógica
pura y está cubierto por pruebas. Aquí solo se dibuja.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox, PushButton
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_LIME,
    ACCENT_RED,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    BG_CARD,
    BORDER,
    RADIUS_CARD,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Avatar,
    BackButton,
    Card,
    DataChip,
    EmptyState,
    IconBadge,
    Pill,
    Sparkline,
    clear_layout,
    format_date_es,
)
from myofit_pro.progress import Verdict, trend_for

#: Color de cada veredicto. Verde y turquesa son buenas noticias, ámbar
#: es "no se puede afirmar", gris es "no pasó nada medible".
VERDICT_COLORS: dict[Verdict, str] = {
    Verdict.MAS_FUERTE: ACCENT_LIME,
    Verdict.MAS_EFICIENTE: ACCENT_TEAL,
    Verdict.RECLUTA_MAS: ACCENT_TEAL,
    Verdict.SIN_CAMBIO: TEXT_MUTED,
    Verdict.MENOS_CARGA: ACCENT_RED,
    Verdict.SIN_CARGA: ACCENT_AMBER,
    Verdict.NUEVO: ACCENT_BLUE,
}

VERDICT_ICONS: dict[Verdict, str] = {
    Verdict.MAS_FUERTE: "▲",
    Verdict.MAS_EFICIENTE: "▲",
    Verdict.RECLUTA_MAS: "▲",
    Verdict.SIN_CAMBIO: "=",
    Verdict.MENOS_CARGA: "▼",
    Verdict.SIN_CARGA: "?",
    Verdict.NUEVO: "+",
}


class _ComparisonRow(QWidget):
    """
    Una fila de comparación: antes → ahora, el veredicto y la tendencia.

    No usa `ListRow` porque necesita tres bloques de información con
    pesos visuales distintos (identidad, lectura, números), y meterlos en
    el hueco de "subtítulo" los aplastaría todos al mismo nivel.
    """

    def __init__(self, comparison, trend: list[float], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("comparisonRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        color = VERDICT_COLORS[comparison.verdict]
        self.setStyleSheet(
            f"QWidget#comparisonRow {{ background-color: {BG_CARD}; "
            f"border: 1px solid {BORDER}; border-radius: {RADIUS_CARD - 4}px; }}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 16, 12)
        row.setSpacing(14)

        row.addWidget(
            IconBadge(VERDICT_ICONS[comparison.verdict], color, size=38),
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        # ── Identidad y lectura ──────────────────────────────────────
        info = QVBoxLayout()
        info.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        name = QLabel(comparison.name)
        name.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        title_row.addWidget(name)

        salto = comparison.delta_rank
        if salto:
            title_row.addWidget(
                Pill(
                    f"{'subió' if salto > 0 else 'bajó'} {abs(salto)} "
                    f"{'puesto' if abs(salto) == 1 else 'puestos'}",
                    ACCENT_VIOLET if salto > 0 else TEXT_MUTED,
                )
            )
        title_row.addStretch(1)
        info.addLayout(title_row)

        verdict = QLabel(comparison.message())
        verdict.setWordWrap(True)
        verdict.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 600; "
            f"background: transparent; border: none;"
        )
        info.addWidget(verdict)

        row.addLayout(info, stretch=1)

        # ── Tendencia ────────────────────────────────────────────────
        # Solo con tres o más puntos: dos puntos ya se ven en los números
        # de la derecha y una línea de dos puntos no es una tendencia.
        #
        # Va en gris y NO en el color del veredicto a propósito. La línea
        # dibuja la activación, y que baje no es mala noticia: el caso de
        # arriba (más peso con menos activación) es progreso y su línea
        # va hacia abajo. Pintarla de verde mientras cae, o de rojo
        # mientras sube, sería contradecir el veredicto que está al lado.
        if len(trend) >= 3:
            spark = Sparkline(trend, TEXT_SECONDARY)
            spark.setFixedSize(90, 38)
            spark.setStyleSheet("background: transparent; border: none;")
            spark.setToolTip(
                "Activación en cada evaluación, de la más vieja a la más reciente: "
                + "  →  ".join(f"{v:.0f}%" for v in trend)
            )
            row.addWidget(spark, alignment=Qt.AlignmentFlag.AlignVCenter)

        # ── Números ──────────────────────────────────────────────────
        row.addLayout(self._values_column(comparison, color))

    @staticmethod
    def _values_column(comparison, color: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(1)
        col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        antes = comparison.before
        ahora = comparison.after

        if antes is None:
            valor = QLabel(f"{ahora.activation_pct:.0f}%")
        else:
            valor = QLabel(
                f"{antes.activation_pct:.0f}%  →  {ahora.activation_pct:.0f}%"
            )
        valor.setAlignment(Qt.AlignmentFlag.AlignRight)
        valor.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 17px; font-weight: 800; "
            f"letter-spacing: -0.3px; background: transparent; border: none;"
        )
        col.addWidget(valor)

        partes = []
        delta = comparison.delta_activation
        if delta is not None:
            partes.append(f"{delta:+.0f} pts de activación")
        carga = comparison.delta_load
        if carga:
            partes.append(f"{carga:+.1f} kg".replace(".0 kg", " kg"))
        elif ahora.load_kg:
            partes.append(f"{ahora.load_kg:.1f} kg".replace(".0 kg", " kg"))

        caption = QLabel("   ·   ".join(partes) if partes else "activación")
        caption.setAlignment(Qt.AlignmentFlag.AlignRight)
        caption.setStyleSheet(
            f"color: {color if delta else TEXT_MUTED}; font-size: 11px; "
            f"font-weight: 600; background: transparent; border: none;"
        )
        col.addWidget(caption)
        return col


class ClientProgressView(QWidget):
    back_requested = Signal()

    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._client = None
        self._muscles: list = []
        self._report = None
        self._sessions: list = []
        self._build_ui()

    # ── Construcción ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        top = QHBoxLayout()
        back = BackButton("Ficha del cliente")
        back.clicked.connect(self.back_requested.emit)
        top.addWidget(back)
        top.addStretch(1)

        self.export_btn = PushButton("Exportar PDF")
        self.export_btn.setIcon(FIF.DOCUMENT)
        self.export_btn.clicked.connect(self._on_export_clicked)
        top.addWidget(self.export_btn)
        layout.addLayout(top)

        self.header_host = QVBoxLayout()
        self.header_host.setSpacing(18)
        layout.addLayout(self.header_host)

        self.content = QVBoxLayout()
        self.content.setSpacing(16)
        layout.addLayout(self.content)
        layout.addStretch(1)

        scroll.setWidget(host)
        outer.addWidget(scroll)

    # ── Carga ────────────────────────────────────────────────────────

    def load_client(self, client) -> None:
        self._client = client
        self._muscles = self.state.muscles_with_history(client.id)

        clear_layout(self.header_host)
        self.header_host.addWidget(self._build_hero(client))

        if not self._muscles:
            clear_layout(self.content)
            self.export_btn.setEnabled(False)
            self.content.addWidget(
                EmptyState(
                    "📈",
                    f"{client.full_name} todavía no tiene evaluaciones completadas.\n"
                    "Haz una para empezar a seguir su progreso.",
                )
            )
            return

        self.export_btn.setEnabled(True)
        self._render_muscle(self._muscles[0][0].id)

    def _build_hero(self, client) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(Avatar(client.full_name, size=58), alignment=Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(6)

        title = QLabel("Progreso")
        title.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 800; "
            f"letter-spacing: 0.8px; background: transparent; border: none;"
        )
        info.addWidget(title)

        name = QLabel(client.full_name)
        name.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 25px; font-weight: 800; "
            f"letter-spacing: -0.5px; background: transparent; border: none;"
        )
        info.addWidget(name)
        row.addLayout(info, stretch=1)

        if len(self._muscles) > 1:
            picker = QVBoxLayout()
            picker.setSpacing(5)
            label = QLabel("MÚSCULO")
            label.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 700; "
                f"letter-spacing: 0.3px; background: transparent; border: none;"
            )
            picker.addWidget(label)

            self.muscle_combo = ComboBox(card)
            self.muscle_combo.setMinimumWidth(210)
            for muscle, veces in self._muscles:
                self.muscle_combo.addItem(f"{muscle.name}  ({veces})")
            self.muscle_combo.currentIndexChanged.connect(self._on_muscle_changed)
            picker.addWidget(self.muscle_combo)
            row.addLayout(picker)

        card.body.addLayout(row)
        return card

    def _on_muscle_changed(self, index: int) -> None:
        if 0 <= index < len(self._muscles):
            self._render_muscle(self._muscles[index][0].id)

    def _render_muscle(self, muscle_id: int) -> None:
        clear_layout(self.content)

        resultado = self.state.progress_for_muscle(self._client.id, muscle_id)
        if resultado is None:
            self.content.addWidget(
                EmptyState("📈", "No hay evaluaciones completadas de este músculo.")
            )
            return

        report, sessions = resultado
        self._report = report
        self._sessions = sessions

        self.content.addWidget(self._build_summary_card(report))

        if report.is_first:
            self.content.addWidget(self._build_first_time_card(report))
        else:
            self.content.addWidget(self._build_comparison_card(report, sessions))

    # ── Bloques ──────────────────────────────────────────────────────

    def _build_summary_card(self, report) -> Card:
        card = Card()

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(IconBadge(FIF.CALORIES, ACCENT_TEAL, size=42))

        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(report.muscle_name)
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 19px; font-weight: 750; "
            f"background: transparent; border: none;"
        )
        titles.addWidget(title)

        if report.before is not None:
            cuando = QLabel(
                f"{format_date_es(report.before.date)}   →   "
                f"{format_date_es(report.after.date)}"
            )
        else:
            cuando = QLabel(format_date_es(report.after.date))
        cuando.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 12px; background: transparent; border: none;"
        )
        titles.addWidget(cuando)
        head.addLayout(titles, stretch=1)
        card.body.addLayout(head)

        headline = QLabel(report.headline())
        headline.setWordWrap(True)
        headline.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 600; "
            f"background: transparent; border: none;"
        )
        card.body.addWidget(headline)

        chips = QHBoxLayout()
        chips.setSpacing(8)

        # La circunferencia es el titular cuando el objetivo es crecer:
        # es la única medida directa de que el músculo creció.
        crecimiento = report.delta_circumference
        if crecimiento is not None:
            color = ACCENT_LIME if crecimiento > 0 else TEXT_SECONDARY
            chips.addWidget(
                DataChip(f"{crecimiento:+.1f} cm", "PERÍMETRO DEL MÚSCULO", color)
            )
        elif report.after.circumference_cm:
            chips.addWidget(
                DataChip(f"{report.after.circumference_cm:.1f} cm", "PERÍMETRO (1ª MEDIDA)")
            )

        balance = report.delta_balance
        if balance is not None and abs(balance) >= 1.0:
            # Negativo es bueno: menos diferencia entre canales. Por
            # debajo de un punto no se marca ni en verde ni en ámbar: un
            # "+0 pts" en color de advertencia parece un problema y lo
            # único que dice es que no pasó nada.
            color = ACCENT_TEAL if balance < 0 else ACCENT_AMBER
            chips.addWidget(DataChip(f"{balance:+.0f} pts", "DESBALANCE A/B", color))
        elif report.after.balance_gap is not None:
            chips.addWidget(
                DataChip(f"{report.after.balance_gap:.0f} pts", "DESBALANCE A/B")
            )

        if report.days_between:
            chips.addWidget(DataChip(str(report.days_between), "DÍAS ENTRE MEDIDAS"))

        chips.addStretch(1)
        if chips.count() > 1:
            card.body.addLayout(chips)

        return card

    def _build_first_time_card(self, report) -> Card:
        card = Card()
        card.add_title("Punto de partida")
        for comparison in report.comparisons:
            card.body.addWidget(_ComparisonRow(comparison, trend=[]))
        return card

    def _build_comparison_card(self, report, sessions) -> Card:
        card = Card()
        card.add_title("Ejercicio por ejercicio")
        for comparison in report.comparisons:
            historia = [valor for _, valor in trend_for(sessions, comparison.exercise_id)]
            card.body.addWidget(_ComparisonRow(comparison, trend=historia))
        return card

    # ── Exportación ──────────────────────────────────────────────────

    def _on_export_clicked(self) -> None:
        if self._client is None or self._report is None:
            return

        from myofit_pro.gui.progress_pdf import export_progress_pdf

        sugerido = (
            f"Progreso-{self._client.full_name.replace(' ', '-')}-"
            f"{self._report.muscle_name.split()[0]}.pdf"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar el informe de progreso", sugerido, "PDF (*.pdf)"
        )
        if not path:
            return

        try:
            export_progress_pdf(
                path=path,
                trainer=self.state.current_trainer,
                client=self._client,
                report=self._report,
                sessions=self._sessions,
            )
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(
                self, "No se pudo guardar el PDF", f"El archivo no se generó:\n\n{error}"
            )
            return

        QMessageBox.information(
            self, "Informe guardado", f"El informe se guardó en:\n\n{path}"
        )
