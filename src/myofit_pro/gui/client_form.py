"""
Alta y edición de un cliente, en tres pasos.

Se separó del resto de "Mis clientes" porque creció: un formulario de
una sola pantalla con doce campos se abandona a la mitad, y estos datos
son los que después alimentan la predicción de rutina, así que conviene
que se llenen completos.

El reparto de los pasos sigue lo que cada dato necesita del anterior:

  1. Quién es       nombre, apellido, sexo y edad
  2. Medidas        estatura y peso (de ahí sale el IMC), y el
                    porcentaje de grasa, que necesita sexo y edad del
                    paso anterior para poder estimarse
  3. Entrenamiento  objetivo, experiencia, días por semana y notas

El mismo formulario sirve para dar de alta y para editar. Si el alta
pidiera un dato que la edición no ofrece, ese dato quedaría imposible de
corregir después.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    DoubleSpinBox,
    FluentIcon as FIF,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    TextEdit,
)

from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_LIME,
    ACCENT_PINK,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    BG_ELEVATED,
    BORDER,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    BackButton,
    Card,
    IconBadge,
    SelectableCard,
    StepProgressBar,
    clear_layout,
)
from myofit_pro.body_composition import (
    EXPERIENCE_LEVELS,
    GOALS,
    PRIMARY_GOAL_NAMES,
    SECONDARY_GOAL_NAMES,
    SEX_FEMALE,
    SEX_MALE,
    BodyFatSource,
    bmi,
    bmi_category,
    body_fat_category,
    resolve_body_fat,
)

# Presentación de los tres objetivos principales: icono, color y la
# frase con la que el cliente los reconoce. Los nombres vienen del
# dominio (`body_composition`), aquí solo se les pone cara.
_GOAL_LOOKS = {
    "Fuerza": (FIF.SPEED_HIGH, ACCENT_BLUE, "Levantar más peso en menos repeticiones"),
    "Hipertrofia": (FIF.CALORIES, ACCENT_VIOLET, "Ganar masa muscular y volumen"),
    "Definición": (FIF.HEART, ACCENT_PINK, "Perder grasa conservando músculo"),
}
PRIMARY_GOALS = tuple(
    (name, *_GOAL_LOOKS[name]) for name in PRIMARY_GOAL_NAMES
)
SECONDARY_GOALS = SECONDARY_GOAL_NAMES

SEX_OPTIONS = ["Sin especificar", SEX_MALE, SEX_FEMALE]

# Cómo se le pregunta al usuario el nivel de experiencia. La pregunta va
# en lenguaje de gimnasio y lo que se guarda es la etiqueta corta.
EXPERIENCE_CHOICES = (
    ("Nunca he pisado un gimnasio", "Principiante"),
    ("Llevo unos meses entrenando", "Intermedio"),
    ("Llevo más de 2 años entrenando constante", "Avanzado"),
)

DAYS_CHOICES = (
    ("3 días a la semana", 3),
    ("4 días a la semana", 4),
    ("5 días o más", 5),
)

_NO_SECONDARY = "Otro objetivo..."

# Valor con el que un control numérico significa "no me lo dijeron".
# Se guarda como None y no como cero: un cliente sin peso registrado no
# pesa cero kilos, simplemente no se midió, y la diferencia arruinaría
# cualquier promedio que se calcule después.
_UNSET = 0

_STEP_TITLES = ("Datos personales", "Medidas corporales", "Objetivo y plan")
_STEP_CAPTIONS = (
    "Lo mínimo para identificar al cliente",
    "De aquí salen el IMC y el porcentaje de grasa",
    "Qué busca y cuánto puede entrenar",
)


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 700; "
        f"letter-spacing: 0.3px; background: transparent; border: none;"
    )
    return label


def _field(text: str, widget: QWidget) -> QVBoxLayout:
    """Etiqueta encima del control, que es como se leen los formularios."""
    column = QVBoxLayout()
    column.setSpacing(5)
    column.addWidget(_field_label(text))
    column.addWidget(widget)
    return column


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"color: {TEXT_MUTED}; font-size: 11px; background: transparent; border: none;"
    )
    return label


class ClientFormDialog(QDialog):
    """Asistente de alta y edición de cliente."""

    def __init__(self, parent: QWidget | None = None, client=None):
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("Editar cliente" if client else "Nuevo cliente")
        self.setMinimumSize(620, 700)

        self._step = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(16)

        outer.addWidget(self._build_header())

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._build_step_personal())
        self.stack.addWidget(self._build_step_body())
        self.stack.addWidget(self._build_step_training())
        outer.addWidget(self.stack, stretch=1)

        outer.addLayout(self._build_footer())

        if client is not None:
            self._load(client)

        self._refresh_body_readout()
        self._show_step(0)

    # ── Estructura ───────────────────────────────────────────────────

    def _build_header(self) -> Card:
        card = Card()

        row = QHBoxLayout()
        row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)

        self.step_title = QLabel(_STEP_TITLES[0])
        self.step_title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: 750; "
            f"letter-spacing: -0.3px; background: transparent; border: none;"
        )
        title_col.addWidget(self.step_title)

        self.step_caption = QLabel(_STEP_CAPTIONS[0])
        self.step_caption.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; "
            f"background: transparent; border: none;"
        )
        title_col.addWidget(self.step_caption)

        row.addLayout(title_col, stretch=1)

        self.progress = StepProgressBar(total_steps=3)
        self.progress.setMaximumWidth(150)
        row.addWidget(self.progress, alignment=Qt.AlignmentFlag.AlignVCenter)

        card.body.addLayout(row)
        return card

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.back_btn = BackButton("Atrás")
        self.back_btn.clicked.connect(self._on_back_clicked)
        row.addWidget(self.back_btn)

        self.next_btn = PrimaryPushButton("Continuar  →")
        self.next_btn.clicked.connect(self._on_next_clicked)
        row.addWidget(self.next_btn, stretch=1)

        cancel_btn = PushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)
        return row

    @staticmethod
    def _page() -> tuple[QWidget, QVBoxLayout]:
        """Página desplazable, por si la ventana queda corta de alto."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(host)
        return scroll, layout

    # ── Paso 1: datos personales ─────────────────────────────────────

    def _build_step_personal(self) -> QWidget:
        page, layout = self._page()

        card = Card()
        names = QHBoxLayout()
        names.setSpacing(12)
        self.first_name_input = LineEdit()
        self.first_name_input.setPlaceholderText("María")
        self.last_name_input = LineEdit()
        self.last_name_input.setPlaceholderText("González Ruiz")
        names.addLayout(_field("NOMBRE", self.first_name_input), stretch=1)
        names.addLayout(_field("APELLIDO", self.last_name_input), stretch=1)
        card.body.addLayout(names)

        details = QHBoxLayout()
        details.setSpacing(12)

        self.sex_input = ComboBox()
        self.sex_input.addItems(SEX_OPTIONS)
        self.sex_input.currentIndexChanged.connect(self._refresh_body_readout)
        details.addLayout(_field("SEXO", self.sex_input), stretch=1)

        self.age_input = SpinBox()
        self.age_input.setRange(_UNSET, 100)
        self.age_input.setValue(_UNSET)
        self.age_input.setSpecialValueText("Sin especificar")
        self.age_input.setSuffix(" años")
        self.age_input.valueChanged.connect(self._refresh_body_readout)
        details.addLayout(_field("EDAD", self.age_input), stretch=1)

        card.body.addLayout(details)
        card.body.addWidget(
            _hint(
                "El sexo y la edad no son burocracia: entran en las fórmulas de "
                "composición corporal del siguiente paso y en cuánta recuperación "
                "hay que darle entre sesiones."
            )
        )
        layout.addWidget(card)
        return page

    # ── Paso 2: medidas ──────────────────────────────────────────────

    def _build_step_body(self) -> QWidget:
        page, layout = self._page()

        basics = Card()
        basics.add_title("Estatura y peso")

        row = QHBoxLayout()
        row.setSpacing(12)

        self.height_input = DoubleSpinBox()
        self.height_input.setRange(_UNSET, 250)
        self.height_input.setDecimals(0)
        self.height_input.setValue(_UNSET)
        self.height_input.setSpecialValueText("Sin especificar")
        self.height_input.setSuffix(" cm")
        self.height_input.valueChanged.connect(self._refresh_body_readout)
        row.addLayout(_field("ESTATURA", self.height_input), stretch=1)

        self.weight_input = DoubleSpinBox()
        self.weight_input.setRange(_UNSET, 300)
        self.weight_input.setDecimals(1)
        self.weight_input.setSingleStep(0.5)
        self.weight_input.setValue(_UNSET)
        self.weight_input.setSpecialValueText("Sin especificar")
        self.weight_input.setSuffix(" kg")
        self.weight_input.valueChanged.connect(self._refresh_body_readout)
        row.addLayout(_field("PESO", self.weight_input), stretch=1)

        basics.body.addLayout(row)
        layout.addWidget(basics)

        # Circunferencias: opcionales, pero son la diferencia entre un
        # dato real y una estimación. Ver el comentario de _build_readout.
        girths = Card()
        girths.add_title(
            "Circunferencias",
            "Opcionales, solo cinta métrica. Convierten la grasa estimada en medida.",
        )

        girth_row = QHBoxLayout()
        girth_row.setSpacing(12)

        self.neck_input = self._girth_spin("Cuello")
        self.waist_input = self._girth_spin("Cintura")
        self.hip_input = self._girth_spin("Cadera")
        girth_row.addLayout(_field("CUELLO", self.neck_input), stretch=1)
        girth_row.addLayout(_field("CINTURA", self.waist_input), stretch=1)
        girth_row.addLayout(_field("CADERA", self.hip_input), stretch=1)
        girths.body.addLayout(girth_row)

        self.hip_hint = _hint("")
        girths.body.addWidget(self.hip_hint)
        layout.addWidget(girths)

        manual = Card()
        manual.add_title(
            "¿Ya tienes el porcentaje de grasa?",
            "De báscula de bioimpedancia o plicómetro. Si lo capturas, manda sobre todo lo demás.",
        )
        self.body_fat_input = DoubleSpinBox()
        self.body_fat_input.setRange(_UNSET, 65)
        self.body_fat_input.setDecimals(1)
        self.body_fat_input.setSingleStep(0.5)
        self.body_fat_input.setValue(_UNSET)
        self.body_fat_input.setSpecialValueText("No lo tengo")
        self.body_fat_input.setSuffix(" %")
        self.body_fat_input.valueChanged.connect(self._refresh_body_readout)
        manual.body.addLayout(_field("GRASA CORPORAL MEDIDA", self.body_fat_input))
        layout.addWidget(manual)

        layout.addWidget(self._build_readout())
        return page

    @staticmethod
    def _girth_spin(name: str) -> DoubleSpinBox:
        spin = DoubleSpinBox()
        spin.setRange(_UNSET, 200)
        spin.setDecimals(1)
        spin.setSingleStep(0.5)
        spin.setValue(_UNSET)
        spin.setSpecialValueText("—")
        spin.setSuffix(" cm")
        spin.setToolTip(f"{name} en centímetros")
        return spin

    def _build_readout(self) -> Card:
        """Resultado en vivo: IMC y grasa, con la fuente del número."""
        card = Card()
        card.add_title("Resultado")

        row = QHBoxLayout()
        row.setSpacing(14)

        self.bmi_badge = IconBadge(FIF.PIE_SINGLE, ACCENT_TEAL, size=40)
        row.addWidget(self.bmi_badge)

        bmi_col = QVBoxLayout()
        bmi_col.setSpacing(0)
        self.bmi_value = QLabel("—")
        self.bmi_value.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 20px; font-weight: 800; "
            f"background: transparent; border: none;"
        )
        bmi_col.addWidget(self.bmi_value)
        bmi_col.addWidget(_field_label("IMC"))
        row.addLayout(bmi_col)

        row.addSpacing(18)

        self.fat_badge = IconBadge(FIF.CERTIFICATE, ACCENT_AMBER, size=40)
        row.addWidget(self.fat_badge)

        fat_col = QVBoxLayout()
        fat_col.setSpacing(0)
        self.fat_value = QLabel("—")
        self.fat_value.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 20px; font-weight: 800; "
            f"background: transparent; border: none;"
        )
        fat_col.addWidget(self.fat_value)
        fat_col.addWidget(_field_label("GRASA CORPORAL"))
        row.addLayout(fat_col)

        row.addStretch(1)
        card.body.addLayout(row)

        self.source_note = _hint("")
        card.body.addWidget(self.source_note)
        return card

    # ── Paso 3: entrenamiento ────────────────────────────────────────

    def _build_step_training(self) -> QWidget:
        page, layout = self._page()

        goal_card = Card()
        goal_card.add_title("Objetivo", "El que manda sobre cómo se arma la rutina")

        self._goal_cards: list[SelectableCard] = []
        self._selected_goal = PRIMARY_GOALS[1][0]   # Hipertrofia por defecto

        for index, (name, icon, accent, detail) in enumerate(PRIMARY_GOALS):
            card = SelectableCard(
                title=name,
                subtitle=detail,
                leading=IconBadge(icon, accent, size=40),
                accent=accent,
            )
            card.clicked.connect(lambda i=index: self._select_goal_card(i))
            self._goal_cards.append(card)
            goal_card.body.addWidget(card)

        self.secondary_goal = ComboBox()
        self.secondary_goal.addItems([_NO_SECONDARY] + list(SECONDARY_GOALS))
        self.secondary_goal.currentIndexChanged.connect(self._on_secondary_goal_changed)
        goal_card.body.addLayout(
            _field("OTROS OBJETIVOS", self.secondary_goal)
        )
        layout.addWidget(goal_card)

        context = Card()
        context.add_title("Contexto de entrenamiento")

        self.experience_input = ComboBox()
        self.experience_input.addItems([label for label, _ in EXPERIENCE_CHOICES])
        context.body.addLayout(_field("NIVEL DE EXPERIENCIA", self.experience_input))

        self.days_input = ComboBox()
        self.days_input.addItems([label for label, _ in DAYS_CHOICES])
        context.body.addLayout(_field("DISPONIBILIDAD", self.days_input))

        context.body.addWidget(
            _hint(
                "La experiencia define cuánto volumen tolera el cliente y los días "
                "definen cómo se reparte ese volumen en la semana."
            )
        )
        layout.addWidget(context)

        notes_card = Card()
        notes_card.add_title("Notas")
        self.notes_input = TextEdit()
        self.notes_input.setPlaceholderText(
            "Lesiones, limitaciones, experiencia previa, lo que convenga recordar."
        )
        self.notes_input.setMaximumHeight(84)
        notes_card.body.addWidget(self.notes_input)
        layout.addWidget(notes_card)

        self._select_goal_card(1)
        return page

    def _select_goal_card(self, index: int) -> None:
        for i, card in enumerate(self._goal_cards):
            card.set_selected(i == index)
        self._selected_goal = PRIMARY_GOALS[index][0]

        self.secondary_goal.blockSignals(True)
        self.secondary_goal.setCurrentIndex(0)
        self.secondary_goal.blockSignals(False)

    def _on_secondary_goal_changed(self, index: int) -> None:
        if index <= 0:
            return
        # Elegir un objetivo secundario deselecciona las tarjetas: el
        # objetivo es uno solo y dos cosas marcadas a la vez no dirían
        # cuál gana.
        for card in self._goal_cards:
            card.set_selected(False)
        self._selected_goal = self.secondary_goal.currentText()

    # ── Navegación ───────────────────────────────────────────────────

    def _show_step(self, step: int) -> None:
        self._step = step
        self.stack.setCurrentIndex(step)
        self.step_title.setText(_STEP_TITLES[step])
        self.step_caption.setText(_STEP_CAPTIONS[step])
        self.progress.set_current(step + 1)
        self.back_btn.setVisible(step > 0)

        last = step == len(_STEP_TITLES) - 1
        self.next_btn.setText("Guardar cliente" if last else "Continuar  →")

    def _on_back_clicked(self) -> None:
        if self._step > 0:
            self._show_step(self._step - 1)

    def _on_next_clicked(self) -> None:
        if not self._validate_step(self._step):
            return
        if self._step < len(_STEP_TITLES) - 1:
            self._show_step(self._step + 1)
        else:
            self.accept()

    def _validate_step(self, step: int) -> bool:
        if step != 0:
            return True

        if not self.first_name_input.text().strip():
            QMessageBox.warning(self, "Falta el nombre", "El nombre es obligatorio.")
            self.first_name_input.setFocus()
            return False
        if not self.last_name_input.text().strip():
            QMessageBox.warning(self, "Falta el apellido", "El apellido es obligatorio.")
            self.last_name_input.setFocus()
            return False
        return True

    # ── Cálculo en vivo ──────────────────────────────────────────────

    def _current_sex(self) -> str | None:
        sex = self.sex_input.currentText()
        return sex if sex != SEX_OPTIONS[0] else None

    @staticmethod
    def _or_none(value: float) -> float | None:
        return float(value) if value > _UNSET else None

    def _refresh_body_readout(self) -> None:
        sex = self._current_sex()
        age = int(self.age_input.value()) or None
        height = self._or_none(self.height_input.value())
        weight = self._or_none(self.weight_input.value())

        bmi_value = bmi(height, weight)
        if bmi_value is None:
            self.bmi_value.setText("—")
        else:
            self.bmi_value.setText(f"{bmi_value:.1f}  ·  {bmi_category(bmi_value)}")

        pct, source = resolve_body_fat(
            manual_pct=self._or_none(self.body_fat_input.value()),
            sex=sex,
            age_years=age,
            height_cm=height,
            weight_kg=weight,
            neck_cm=self._or_none(self.neck_input.value()),
            waist_cm=self._or_none(self.waist_input.value()),
            hip_cm=self._or_none(self.hip_input.value()),
        )

        if pct is None:
            self.fat_value.setText("—")
            self.source_note.setText(
                "Captura sexo, edad, estatura y peso para estimar el porcentaje de grasa."
            )
        else:
            self.fat_value.setText(f"{pct:.1f}%  ·  {body_fat_category(pct, sex)}")
            self.source_note.setText(self._source_explanation(source))

        # La cadera solo entra en la fórmula femenina, así que la pista
        # cambia según el sexo en vez de pedir siempre las tres medidas.
        if sex == SEX_FEMALE:
            self.hip_hint.setText(
                "En mujeres la fórmula usa cuello, cintura y cadera. Las tres hacen falta."
            )
        elif sex == SEX_MALE:
            self.hip_hint.setText(
                "En hombres la fórmula usa cuello y cintura. La cadera no hace falta."
            )
        else:
            self.hip_hint.setText(
                "Elige el sexo en el paso anterior para saber qué medidas hacen falta."
            )

    @staticmethod
    def _source_explanation(source: str | None) -> str:
        if source == BodyFatSource.MEASURED.value:
            return "Dato medido. Es el mejor de los tres y se guarda tal cual."
        if source == BodyFatSource.NAVY.value:
            return (
                "Calculado de las circunferencias. Cuenta como dato medido, porque la "
                "cintura y el cuello dicen algo del cuerpo que la estatura y el peso no."
            )
        return (
            "Estimación de Deurenberg a partir de IMC, edad y sexo. Sirve como "
            "referencia, pero no es información nueva: dos personas con el mismo IMC, "
            "edad y sexo reciben el mismo número. Toma las circunferencias de arriba "
            "si quieres un dato que distinga entre clientes."
        )

    # ── Carga y guardado ─────────────────────────────────────────────

    def _load(self, client) -> None:
        # Las fichas dadas de alta antes de que existieran estos campos
        # solo tienen `full_name`. La migración ya partió el nombre, pero
        # si alguna quedó sin partir se reconstruye aquí.
        first, last = client.first_name, client.last_name
        if not first and not last:
            parts = (client.full_name or "").split(" ", 1)
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""

        self.first_name_input.setText(first or "")
        self.last_name_input.setText(last or "")

        if client.sex in SEX_OPTIONS:
            self.sex_input.setCurrentText(client.sex)
        for spin, value in (
            (self.age_input, client.age_years),
            (self.height_input, client.height_cm),
            (self.weight_input, client.weight_kg),
            (self.neck_input, client.neck_cm),
            (self.waist_input, client.waist_cm),
            (self.hip_input, client.hip_cm),
        ):
            if value:
                spin.setValue(value)

        # Solo se recupera el porcentaje si fue medido. Si era una
        # estimación, se vuelve a calcular sola y meterla en el campo
        # manual la convertiría en un dato "medido" que nadie midió.
        if client.body_fat_pct and client.body_fat_source == BodyFatSource.MEASURED.value:
            self.body_fat_input.setValue(client.body_fat_pct)

        primary = [name for name, _, _, _ in PRIMARY_GOALS]
        if client.goal in primary:
            self._select_goal_card(primary.index(client.goal))
        elif client.goal in SECONDARY_GOALS:
            self.secondary_goal.setCurrentText(client.goal)

        if client.experience_level in EXPERIENCE_LEVELS:
            index = EXPERIENCE_LEVELS.index(client.experience_level)
            self.experience_input.setCurrentIndex(index)

        for index, (_, days) in enumerate(DAYS_CHOICES):
            if client.days_per_week == days:
                self.days_input.setCurrentIndex(index)

        self.notes_input.setPlainText(client.notes or "")

    def values(self) -> dict:
        """
        Lo que se guarda.

        Los campos numéricos en su valor "sin especificar" se guardan
        como None y no como cero, y el porcentaje de grasa se guarda
        junto con su procedencia, porque de eso depende si más adelante
        sirve como variable de entrada al modelo.
        """
        first = self.first_name_input.text().strip()
        last = self.last_name_input.text().strip()
        sex = self._current_sex()
        age = int(self.age_input.value()) or None
        height = self._or_none(self.height_input.value())
        weight = self._or_none(self.weight_input.value())
        neck = self._or_none(self.neck_input.value())
        waist = self._or_none(self.waist_input.value())
        hip = self._or_none(self.hip_input.value())

        body_fat, source = resolve_body_fat(
            manual_pct=self._or_none(self.body_fat_input.value()),
            sex=sex, age_years=age, height_cm=height, weight_kg=weight,
            neck_cm=neck, waist_cm=waist, hip_cm=hip,
        )

        _, experience = EXPERIENCE_CHOICES[max(0, self.experience_input.currentIndex())]
        _, days = DAYS_CHOICES[max(0, self.days_input.currentIndex())]

        return {
            "full_name": f"{first} {last}".strip(),
            "first_name": first,
            "last_name": last,
            "goal": self._selected_goal,
            "sex": sex,
            "age_years": age,
            "height_cm": height,
            "weight_kg": weight,
            "neck_cm": neck,
            "waist_cm": waist,
            "hip_cm": hip,
            "body_fat_pct": body_fat,
            "body_fat_source": source,
            "experience_level": experience,
            "days_per_week": days,
            "notes": self.notes_input.toPlainText().strip() or None,
        }
