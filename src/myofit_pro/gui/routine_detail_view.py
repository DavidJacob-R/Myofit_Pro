"""
Una rutina concreta: la semana completa, de dónde salió y su edición.

QUÉ ENSEÑA
==========

La semana como se entrena de verdad: lunes empuje, martes tirón,
miércoles pierna, jueves descanso. Cada día con sus cinco o seis
ejercicios, los compuestos primero, y cada ejercicio con lo que le toca
(series, repeticiones, porcentaje del PR).

Cada ejercicio dice de dónde salió, y son tres cosas distintas:

  · medido        se midió en este cliente y esta es su activación
  · complemento   su músculo sí se midió, este ejercicio en concreto no
  · sin lecturas  ese músculo no se ha evaluado

LA EDICIÓN
==========

El generador propone; el entrenador decide. Con "Editar" se pueden
cambiar series y repeticiones, quitar ejercicios y agregar otros del
catálogo. La app no sustituye al entrenador, le ahorra el trabajo de
partir de cero.

Se dibuja desde lo guardado en la base y no regenerando el plan: la
ficha del cliente pudo cambiar, y esta rutina es la que el cliente tuvo
en la mano.
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
from qfluentwidgets import ComboBox, PushButton, SpinBox, ToolButton
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_LIME,
    ACCENT_RED,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    BG_ELEVATED,
    BORDER,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Avatar,
    BackButton,
    Card,
    DataChip,
    EmptyState,
    IconBadge,
    ListRow,
    MeterBar,
    Pill,
    clear_layout,
    goal_color,
)
from myofit_pro.routine_engine import (
    SPLITS,
    VOLUME_TARGETS,
    ExerciseSource,
    format_rest,
    rest_days,
    session_minutes,
    weekly_volume_ratio,
)

_DAY_ACCENTS = (ACCENT_VIOLET, ACCENT_TEAL, ACCENT_BLUE, ACCENT_LIME, ACCENT_AMBER)

#: Cómo se le explica al entrenador de dónde salió cada ejercicio.
SOURCE_PILLS = {
    ExerciseSource.COMPLEMENT.value: ("Complemento", ACCENT_BLUE),
    ExerciseSource.UNMEASURED.value: ("Sin lecturas", ACCENT_AMBER),
}

#: El hueco que salió del sorteo. Se marca para que el entrenador sepa
#: que ese no lo eligió el ranking, y pueda cambiarlo si no le convence.
ROTATION_PILL = ("Variación", ACCENT_VIOLET)



class RoutineDetailView(QWidget):
    back_requested = Signal()
    routine_changed = Signal()

    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._client = None
        self._routine = None
        self._bloques: dict[int, list] = {}
        self._fuentes: list = []
        self._editing = False
        # Estado de la edición: {día: [dict con los campos de la fila]}
        self._draft: dict[int, list[dict]] = {}
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
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        top = QHBoxLayout()
        top.setSpacing(9)
        self.back_button = BackButton("Rutinas")
        self.back_button.clicked.connect(self._on_back_clicked)
        top.addWidget(self.back_button)
        top.addStretch(1)

        self.edit_btn = PushButton("Editar")
        self.edit_btn.setIcon(FIF.EDIT)
        self.edit_btn.clicked.connect(self._toggle_edit)
        top.addWidget(self.edit_btn)

        self.cancel_btn = PushButton("Descartar")
        self.cancel_btn.clicked.connect(self._cancel_edit)
        self.cancel_btn.setVisible(False)
        top.addWidget(self.cancel_btn)

        self.export_btn = PushButton("Descargar PDF")
        self.export_btn.setIcon(FIF.DOWNLOAD)
        self.export_btn.clicked.connect(self._on_export_clicked)
        top.addWidget(self.export_btn)
        layout.addLayout(top)

        self.content = QVBoxLayout()
        self.content.setSpacing(16)
        layout.addLayout(self.content)
        layout.addStretch(1)

        scroll.setWidget(host)
        outer.addWidget(scroll)

    # ── Carga ────────────────────────────────────────────────────────

    def load_routine(self, routine_id: int) -> None:
        self._editing = False
        routine = self.state.routine_repo.get(routine_id)
        if routine is None or not routine.exercises:
            self._show_empty("No se encontró esa rutina.")
            return

        client = self.state.client_repo.get(routine.client_id)
        if client is None:
            self._show_empty("El cliente de esta rutina ya no existe.")
            return

        self._routine = routine
        self._client = client
        self._bloques = self._group_by_day(routine)
        self._fuentes = self._source_sessions(routine)
        self._render()

    def _show_empty(self, mensaje: str) -> None:
        clear_layout(self.content)
        for boton in (self.export_btn, self.edit_btn):
            boton.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.content.addWidget(EmptyState("🗒️", mensaje))

    def _group_by_day(self, routine) -> dict[int, list]:
        """{día: [(nombre, músculo, RoutineExercise)]}, en orden de ejecución."""
        bloques: dict[int, list] = {}
        for item in sorted(routine.exercises, key=lambda x: x.order_index):
            exercise = self.state.exercise_repo.get(item.exercise_id)
            nombre = exercise.name if exercise else f"Ejercicio #{item.exercise_id}"
            muscle = self.state.muscle_repo.get(exercise.muscle_id) if exercise else None
            bloques.setdefault(item.day_index or 1, []).append(
                (nombre, muscle.name if muscle else "—", item)
            )
        return bloques

    def _source_sessions(self, routine) -> list:
        """[(fecha, músculo)] de las evaluaciones que originaron la rutina."""
        fuentes = []
        for parte in (routine.source_session_ids or "").split(","):
            parte = parte.strip()
            if not parte.isdigit():
                continue
            sesion = self.state.evaluation_repo.get_with_results(int(parte))
            if sesion is None:
                continue
            muscle = self.state.muscle_repo.get(sesion.muscle_id)
            fuentes.append((sesion.started_at, muscle.name if muscle else "—"))
        fuentes.sort(key=lambda f: f[0], reverse=True)
        return fuentes

    def _split_day(self, dia: int):
        """La plantilla del día, para saber su nombre y qué bloque es."""
        split = SPLITS.get(self._routine.days_per_week or len(self._bloques))
        if split and 1 <= dia <= len(split):
            return split[dia - 1]
        return None

    # ── Render ───────────────────────────────────────────────────────

    def _render(self) -> None:
        clear_layout(self.content)
        self.export_btn.setEnabled(not self._editing)
        self.edit_btn.setEnabled(True)
        self.edit_btn.setText("Guardar cambios" if self._editing else "Editar")
        self.cancel_btn.setVisible(self._editing)

        self.content.addWidget(self._build_hero())
        if not self._editing:
            comparativa = self._build_comparison_card()
            if comparativa is not None:
                self.content.addWidget(comparativa)

        split = SPLITS.get(self._routine.days_per_week or 0)
        libres = rest_days(split) if split else ()

        for dia in sorted(self._bloques):
            self.content.addWidget(self._build_day_card(dia))

        if libres and not self._editing:
            self.content.addWidget(self._build_rest_card(libres))

        if not self._editing:
            self.content.addWidget(self._build_volume_card())
            avisos = [line for line in (self._routine.notes or "").splitlines() if line.strip()]
            if avisos:
                self.content.addWidget(self._build_warnings_card(avisos))

    def _build_hero(self) -> Card:
        routine, client = self._routine, self._client

        card = Card()
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(Avatar(client.full_name, size=58), alignment=Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(7)

        eyebrow = QLabel(f"RUTINA DEL {routine.created_at.strftime('%d/%m/%Y')}")
        eyebrow.setStyleSheet(
            f"color: {ACCENT_TEAL}; font-size: 11px; font-weight: 800; "
            f"letter-spacing: 0.8px; background: transparent; border: none;"
        )
        info.addWidget(eyebrow)

        name = QLabel(client.full_name)
        name.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 25px; font-weight: 800; "
            f"letter-spacing: -0.5px; background: transparent; border: none;"
        )
        info.addWidget(name)

        pills = QHBoxLayout()
        pills.setSpacing(7)
        goal = routine.goal or client.goal
        pills.addWidget(Pill(goal, goal_color(goal)))
        if routine.experience_level:
            pills.addWidget(Pill(routine.experience_level, ACCENT_BLUE))
        if self._editing:
            pills.addWidget(Pill("Editando", ACCENT_AMBER))
        pills.addStretch(1)
        info.addLayout(pills)

        distintos = {r.exercise_id for items in self._bloques.values() for _, _, r in items}
        series = sum(r.sets for items in self._bloques.values() for _, _, r in items)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addWidget(DataChip(str(len(self._bloques)), "DÍAS DE ENTRENO"))
        chips.addWidget(DataChip(str(len(distintos)), "EJERCICIOS"))
        chips.addWidget(DataChip(str(series), "SERIES / SEMANA", ACCENT_TEAL))
        chips.addStretch(1)
        info.addLayout(chips)

        info.addStretch(1)
        row.addLayout(info, stretch=1)
        card.body.addLayout(row)
        return card

    def _build_comparison_card(self) -> Card | None:
        """
        La medición anterior contra la actual, ejercicio por ejercicio.

        Es a propósito una tabla sencilla y sin veredictos: el entrenador
        quiere ver los dos números y sacar su propia conclusión, no que
        la app se la dé. La lectura con criterio (qué significa que la
        activación baje a mismo peso) vive en la pantalla de progreso del
        cliente, que es donde se entra a estudiarla.

        Devuelve None si no hay nada que comparar todavía.
        """
        filas = self._comparison_rows()
        if not filas:
            return None

        card = Card()
        card.add_title(
            "Comparado con la evaluación anterior",
            self._comparison_subtitle(),
        )

        for nombre, muscle, antes, ahora in filas:
            fila = QHBoxLayout()
            fila.setSpacing(12)

            etiqueta = QLabel(f"{nombre}   ·   {muscle}")
            etiqueta.setStyleSheet(
                f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600; "
                f"background: transparent; border: none;"
            )
            fila.addWidget(etiqueta, stretch=1)

            if antes is None:
                valores = QLabel(f"{ahora:.0f}%")
                delta_text, color = "primera vez", TEXT_MUTED
            else:
                valores = QLabel(f"{antes:.0f}%  →  {ahora:.0f}%")
                diferencia = ahora - antes
                delta_text = f"{diferencia:+.0f}"
                color = (
                    ACCENT_LIME if diferencia > 0
                    else ACCENT_AMBER if diferencia < 0
                    else TEXT_MUTED
                )
            valores.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 13px; font-weight: 700; "
                f"background: transparent; border: none;"
            )
            fila.addWidget(valores)

            delta = QLabel(delta_text)
            delta.setFixedWidth(88)
            delta.setAlignment(Qt.AlignmentFlag.AlignRight)
            delta.setStyleSheet(
                f"color: {color}; font-size: 13px; font-weight: 800; "
                f"background: transparent; border: none;"
            )
            fila.addWidget(delta)
            card.body.addLayout(fila)

        return card

    def _comparison_subtitle(self) -> str:
        if len(self._fuentes) == 1:
            return f"Lectura del {self._fuentes[0][0]:%d/%m/%Y}"
        if self._fuentes:
            fechas = sorted({f"{f:%d/%m/%Y}" for f, _ in self._fuentes})
            return "Lecturas del " + ", ".join(fechas)
        return ""

    def _comparison_rows(self) -> list[tuple[str, str, float | None, float]]:
        """
        (ejercicio, músculo, activación anterior, activación actual) de los
        ejercicios de la rutina que tienen medición.

        Los dos valores salen de las EVALUACIONES, no de la rutina: la
        rutina guarda el promedio de todas las mediciones del ejercicio
        —que es lo correcto para elegirlo, porque promediar lo hace más
        confiable— y comparar ese promedio contra una sesión suelta daba
        diferencias de un punto que no significan nada.

        Aquí se compara la última evaluación de cada músculo contra la
        anterior, que es lo que el entrenador quiere ver.
        """
        en_rutina = {
            r.exercise_id
            for items in self._bloques.values()
            for _, _, r in items
        }

        filas: list[tuple[str, str, float | None, float]] = []
        for muscle_id in self._muscle_ids():
            snapshots = self.state.session_snapshots(self._routine.client_id, muscle_id)
            if not snapshots:
                continue

            # `session_snapshots` viene de la más reciente a la más vieja.
            actual = snapshots[0]
            previa = snapshots[1] if len(snapshots) > 1 else None
            anteriores = (
                {e.exercise_id: e.activation_pct for e in previa.exercises}
                if previa
                else {}
            )

            for ejercicio in actual.exercises:
                if ejercicio.exercise_id not in en_rutina:
                    continue
                filas.append(
                    (
                        ejercicio.name,
                        actual.muscle_name,
                        anteriores.get(ejercicio.exercise_id),
                        ejercicio.activation_pct,
                    )
                )

        filas.sort(key=lambda f: (f[1], f[0]))
        return filas

    def _muscle_ids(self) -> set[int]:
        ids = set()
        for items in self._bloques.values():
            for _, _, r in items:
                exercise = self.state.exercise_repo.get(r.exercise_id)
                if exercise is not None:
                    ids.add(exercise.muscle_id)
        return ids

    def _build_day_card(self, dia: int) -> Card:
        items = self._bloques[dia]
        accent = _DAY_ACCENTS[(dia - 1) % len(_DAY_ACCENTS)]
        plantilla = self._split_day(dia)

        musculos = []
        for _, muscle, _ in items:
            if muscle not in musculos:
                musculos.append(muscle)

        card = Card()
        head = QHBoxLayout()
        head.setSpacing(13)
        head.addWidget(IconBadge(str(dia), accent, size=42))

        titles = QVBoxLayout()
        titles.setSpacing(2)
        encabezado = plantilla.weekday if plantilla else f"Día {dia}"
        if plantilla:
            encabezado += f"  ·  {plantilla.label}"
        title = QLabel(encabezado)
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 17px; font-weight: 750; "
            f"background: transparent; border: none;"
        )
        titles.addWidget(title)

        minutos = session_minutes((r.sets, r.rest_sec or 60) for _, _, r in items)
        caption = QLabel(
            f"{'  ·  '.join(musculos)}   —   {len(items)} ejercicios  ·  "
            f"{sum(r.sets for _, _, r in items)} series  ·  unos {minutos} min"
        )
        caption.setWordWrap(True)
        caption.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 12px; background: transparent; border: none;"
        )
        titles.addWidget(caption)
        head.addLayout(titles, stretch=1)
        card.body.addLayout(head)

        if self._editing:
            for posicion, fila in enumerate(self._draft.get(dia, [])):
                card.body.addWidget(self._build_editable_row(dia, posicion, fila, accent))
            card.body.addWidget(self._build_add_row(dia))
        else:
            for posicion, (nombre, _, r) in enumerate(items, start=1):
                card.body.addWidget(self._build_readonly_row(posicion, nombre, r, accent))
        return card

    def _build_readonly_row(self, posicion: int, nombre: str, r, accent: str) -> ListRow:
        reps = f"{r.reps}-{r.reps_max}" if r.reps_max and r.reps_max != r.reps else str(r.reps)
        detalle = f"{r.sets} × {reps}"
        if r.load_pct_min:
            detalle += f"   al {_load_text(r.load_pct_min, r.load_pct_max)}"
        detalle += f"   ·   {format_rest(r.rest_sec)} de descanso"

        medido = r.activation_pct is not None
        if getattr(r, "is_rotation", False):
            pill = ROTATION_PILL
        elif medido:
            pill = None
        else:
            pill = SOURCE_PILLS.get(r.source or "")

        return ListRow(
            title=nombre,
            subtitle=detalle,
            value=f"{r.activation_pct:.0f}%" if medido else "",
            value_caption="activación" if medido else "",
            value_color=ACCENT_LIME,
            leading=IconBadge(str(posicion), accent, size=34),
            pill=pill,
            clickable=False,
        )

    def _build_editable_row(self, dia: int, posicion: int, fila: dict, accent: str) -> QWidget:
        """Fila con controles: series, repeticiones y quitar."""
        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        host.setObjectName("editRow")
        host.setStyleSheet(
            f"QWidget#editRow {{ background-color: {BG_ELEVATED}; "
            f"border: 1px solid {BORDER}; border-radius: 12px; }}"
        )

        row = QHBoxLayout(host)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(10)
        row.addWidget(IconBadge(str(posicion + 1), accent, size=30))

        nombre = QLabel(fila["name"])
        nombre.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 650; "
            f"background: transparent; border: none;"
        )
        row.addWidget(nombre, stretch=1)

        row.addWidget(_mini_label("SERIES"))
        sets_spin = SpinBox(host)
        sets_spin.setRange(1, 10)
        sets_spin.setValue(fila["sets"])
        sets_spin.setFixedWidth(104)
        sets_spin.valueChanged.connect(lambda v, f=fila: f.update(sets=v))
        row.addWidget(sets_spin)

        row.addWidget(_mini_label("REPS"))
        reps_spin = SpinBox(host)
        reps_spin.setRange(1, 40)
        reps_spin.setValue(fila["reps"])
        reps_spin.setFixedWidth(104)
        reps_spin.valueChanged.connect(lambda v, f=fila: f.update(reps=v))
        row.addWidget(reps_spin)

        row.addWidget(_mini_label("A"))
        reps_max_spin = SpinBox(host)
        reps_max_spin.setRange(1, 40)
        reps_max_spin.setValue(fila["reps_max"] or fila["reps"])
        reps_max_spin.setFixedWidth(104)
        reps_max_spin.valueChanged.connect(lambda v, f=fila: f.update(reps_max=v))
        row.addWidget(reps_max_spin)

        quitar = ToolButton(FIF.DELETE)
        quitar.setFixedSize(30, 30)
        quitar.setToolTip("Quitar de la rutina")
        quitar.setStyleSheet(
            f"ToolButton {{ background-color: transparent; border: 1px solid {BORDER}; "
            f"border-radius: 9px; }}"
            f"ToolButton:hover {{ background-color: {ACCENT_RED}; border-color: {ACCENT_RED}; }}"
        )
        quitar.clicked.connect(lambda _=False, d=dia, p=posicion: self._remove_row(d, p))
        row.addWidget(quitar)
        return host

    def _build_add_row(self, dia: int) -> QWidget:
        """Selector de ejercicio para agregar uno más a este día."""
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(9)

        combo = ComboBox(host)
        combo.setMinimumWidth(280)
        opciones = self._catalog_options(dia)
        if opciones:
            combo.addItems([f"{n}  ·  {m}" for _, n, m in opciones])
        else:
            combo.addItem("No queda nada por agregar")
            combo.setEnabled(False)
        row.addWidget(combo, stretch=1)

        boton = PushButton("Agregar")
        boton.setIcon(FIF.ADD)
        boton.setEnabled(bool(opciones))
        boton.clicked.connect(
            lambda _=False, d=dia, c=combo, o=opciones: self._add_row(d, c.currentIndex(), o)
        )
        row.addWidget(boton)
        return host

    def _catalog_options(self, dia: int) -> list[tuple[int, str, str]]:
        """(exercise_id, nombre, músculo) de lo que se puede agregar al día."""
        ya = {f["exercise_id"] for f in self._draft.get(dia, [])}
        opciones = []
        for muscle in self.state.muscle_repo.list_muscles():
            for exercise in self.state.exercise_repo.list_for_muscle(muscle.id):
                if exercise.id not in ya:
                    opciones.append((exercise.id, exercise.name, muscle.name))
        opciones.sort(key=lambda o: (o[2], o[1]))
        return opciones

    def _build_rest_card(self, libres: tuple[str, ...]) -> Card:
        card = Card()
        card.add_title("Descanso")
        row = QHBoxLayout()
        row.setSpacing(8)
        for dia in libres:
            row.addWidget(DataChip(dia, "SIN ENTRENO", TEXT_MUTED))
        row.addStretch(1)
        card.body.addLayout(row)
        return card

    def _build_volume_card(self) -> Card:
        weekly: dict[str, int] = {}
        for items in self._bloques.values():
            for _, muscle, r in items:
                weekly[muscle] = weekly.get(muscle, 0) + r.sets

        target = VOLUME_TARGETS.get(self._routine.goal or "", (10, 20))
        low, high = target

        card = Card()
        card.add_title(
            "Volumen semanal por músculo", f"Rango recomendable: {low} a {high} series"
        )

        for muscle, sets in sorted(weekly.items(), key=lambda kv: -kv[1]):
            if sets < low:
                color, verdict = ACCENT_AMBER, "por debajo del rango"
            elif sets > high:
                color, verdict = ACCENT_AMBER, "por encima del rango"
            else:
                color, verdict = ACCENT_TEAL, "dentro del rango"

            col = QVBoxLayout()
            col.setSpacing(6)
            head = QHBoxLayout()
            label = QLabel(muscle)
            label.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 700; "
                f"background: transparent; border: none;"
            )
            head.addWidget(label)
            head.addStretch(1)
            amount = QLabel(f"{sets} series  ·  {verdict}")
            amount.setStyleSheet(
                f"color: {color}; font-size: 12px; font-weight: 700; "
                f"background: transparent; border: none;"
            )
            head.addWidget(amount)
            col.addLayout(head)
            col.addWidget(MeterBar(weekly_volume_ratio(sets, target), color))
            card.body.addLayout(col)
        return card

    def _build_warnings_card(self, avisos: list[str]) -> Card:
        """
        Los avisos van en filas de texto ajustado y no en `ListRow`: el
        título de una ListRow no hace salto de línea, así que un aviso
        largo empujaba el ancho de la pantalla y aparecía barra
        horizontal.
        """
        card = Card()
        card.add_title("Qué revisar de esta rutina")
        for mensaje in avisos:
            fila = QHBoxLayout()
            fila.setSpacing(11)
            fila.addWidget(
                IconBadge(FIF.INFO, ACCENT_AMBER, size=30),
                alignment=Qt.AlignmentFlag.AlignTop,
            )
            texto = QLabel(mensaje)
            texto.setWordWrap(True)
            texto.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 12px; "
                f"background: transparent; border: none;"
            )
            fila.addWidget(texto, stretch=1)
            card.body.addLayout(fila)
        return card

    # ── Edición ──────────────────────────────────────────────────────

    def _toggle_edit(self) -> None:
        if self._editing:
            self._save_edit()
            return

        # Se copia a un borrador: mientras no se guarde, la rutina en la
        # base no se toca y "Descartar" es un simple tirar el borrador.
        self._draft = {
            dia: [
                {
                    "exercise_id": r.exercise_id, "name": nombre,
                    "sets": r.sets, "reps": r.reps, "reps_max": r.reps_max or r.reps,
                    "rest_sec": r.rest_sec, "rir": r.rir,
                    "load_pct_min": r.load_pct_min, "load_pct_max": r.load_pct_max,
                    "day_index": dia, "activation_pct": r.activation_pct,
                    "source": r.source,
                    "is_rotation": bool(getattr(r, "is_rotation", False)),
                }
                for nombre, _, r in items
            ]
            for dia, items in self._bloques.items()
        }
        self._editing = True
        self._render()

    def _cancel_edit(self) -> None:
        self._editing = False
        self._draft = {}
        self._render()

    def _remove_row(self, dia: int, posicion: int) -> None:
        filas = self._draft.get(dia, [])
        if 0 <= posicion < len(filas):
            filas.pop(posicion)
        self._render()

    def _add_row(self, dia: int, indice: int, opciones: list[tuple[int, str, str]]) -> None:
        if not (0 <= indice < len(opciones)):
            return
        exercise_id, nombre, _ = opciones[indice]
        base = self._routine.exercises[0]
        self._draft.setdefault(dia, []).append(
            {
                "exercise_id": exercise_id, "name": nombre,
                "sets": base.sets, "reps": base.reps,
                "reps_max": base.reps_max or base.reps,
                "rest_sec": base.rest_sec, "rir": base.rir,
                "load_pct_min": base.load_pct_min, "load_pct_max": base.load_pct_max,
                "day_index": dia,
                # Se agrega a mano, así que no tiene medición detrás. El
                # entrenador sabe por qué lo puso; la app no lo inventa.
                "activation_pct": None,
                "source": ExerciseSource.COMPLEMENT.value,
                # Lo puso el entrenador a mano, así que no es rotación:
                # esa marca existe para saber qué eligió el sorteo.
                "is_rotation": False,
            }
        )
        self._render()

    def _save_edit(self) -> None:
        items = []
        for dia in sorted(self._draft):
            for fila in self._draft[dia]:
                guardar = {k: v for k, v in fila.items() if k != "name"}
                if guardar["reps_max"] and guardar["reps_max"] < guardar["reps"]:
                    guardar["reps_max"] = guardar["reps"]
                items.append(guardar)

        if not items:
            QMessageBox.warning(
                self, "Rutina vacía",
                "Una rutina necesita al menos un ejercicio. Agrega uno o descarta los cambios.",
            )
            return

        self.state.routine_repo.replace_exercises(self._routine.id, items)
        self._editing = False
        self._draft = {}
        self.load_routine(self._routine.id)
        self.routine_changed.emit()

    def _on_back_clicked(self) -> None:
        if self._editing:
            confirm = QMessageBox.question(
                self, "Salir sin guardar",
                "Tienes cambios sin guardar en esta rutina. ¿Salir de todas formas?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            self._editing = False
            self._draft = {}
        self.back_requested.emit()

    # ── Exportación ──────────────────────────────────────────────────

    def _on_export_clicked(self) -> None:
        if self._routine is None or self._client is None:
            return

        from myofit_pro.gui.routine_pdf import export_routine_pdf

        sugerido = (
            f"Rutina-{self._client.full_name.replace(' ', '-')}-"
            f"{self._routine.created_at.strftime('%Y-%m-%d')}.pdf"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Descargar la rutina", sugerido, "PDF (*.pdf)"
        )
        if not path:
            return

        try:
            export_routine_pdf(
                path=path, trainer=self.state.current_trainer, client=self._client,
                routine=self._routine, bloques=self._bloques, fuentes=self._fuentes,
                split=SPLITS.get(self._routine.days_per_week or 0),
                comparacion=self._comparison_rows(),
            )
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(
                self, "No se pudo guardar el PDF", f"El archivo no se generó:\n\n{error}"
            )
            return

        QMessageBox.information(self, "Rutina descargada", f"Se guardó en:\n\n{path}")


def _mini_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 700; "
        f"letter-spacing: 0.3px; background: transparent; border: none;"
    )
    return label


def _load_text(low: int | None, high: int | None) -> str:
    if not low:
        return "—"
    if not high or high == low:
        return f"{low}% de tu PR"
    return f"{low}-{high}% de tu PR"
