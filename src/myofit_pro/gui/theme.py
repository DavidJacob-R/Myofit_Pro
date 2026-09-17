"""
Sistema de diseño de MyoFit Pro — "Deep Ink".

Estética: fondo tinta casi negro con superficies elevadas, bordes
hairline, esquinas muy redondeadas, badges con degradado y acentos
eléctricos. Todo el "chrome" de la app sale de aquí; ninguna vista
debería definir colores a mano.

Los colores de Sensor A (teal) y Sensor B (azul) son semánticos y se
mantienen consistentes en toda la app (SensorsView, wizard, gráficas).

Regla de oro de este archivo: **nada de tablas**. Para listas de datos
se usa `ListRow`, no QTableWidget — una tabla se ve como hoja de
cálculo, no como producto.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentWindow, Theme, setTheme, setThemeColor
from qfluentwidgets.common.icon import FluentIconBase

# ── Tokens: superficies ──────────────────────────────────────────────

BG_MAIN = "#0B0E14"          # fondo de la ventana (tinta)
BG_SIDEBAR = "#0F131C"       # barra de navegación
BG_CARD = "#141926"          # superficie base de tarjetas
BG_CARD_HOVER = "#1A2132"    # tarjeta bajo el cursor
BG_ELEVATED = "#1C2434"      # superficie sobre una tarjeta (inputs, chips)

BORDER = "#212A3B"           # hairline estándar
BORDER_STRONG = "#2F3A50"    # hairline de énfasis

# ── Tokens: acentos ──────────────────────────────────────────────────

ACCENT_VIOLET = "#7C5CFF"    # primario de marca
ACCENT_VIOLET_DEEP = "#5B3FD9"
ACCENT_TEAL = "#2DD4BF"      # Sensor A / éxito
ACCENT_BLUE = "#60A5FA"      # Sensor B / información
ACCENT_AMBER = "#FBBF24"     # advertencia
ACCENT_RED = "#FB7185"       # error / crítico
ACCENT_LIME = "#A3E635"      # score alto
ACCENT_PINK = "#F472B6"      # acento decorativo

# ── Tokens: tipografía ───────────────────────────────────────────────

TEXT_PRIMARY = "#F1F5F9"
TEXT_SECONDARY = "#94A3B8"
TEXT_MUTED = "#64748B"

FONT_STACK = ["Inter", "SF Pro Display", "SF Pro Text", "Segoe UI", "Helvetica Neue"]

# ── Tokens: forma ────────────────────────────────────────────────────

RADIUS_CARD = 18
RADIUS_BADGE = 14
RADIUS_PILL = 13
RADIUS_INPUT = 10


def gradient(start: str, end: str, diagonal: bool = True) -> str:
    """Degradado lineal listo para meter en una hoja de estilo Qt."""
    coords = "x1:0, y1:0, x2:1, y2:1" if diagonal else "x1:0, y1:0, x2:0, y2:1"
    return f"qlineargradient({coords}, stop:0 {start}, stop:1 {end})"


def _alpha(color: str, value: int) -> QColor:
    c = QColor(color)
    c.setAlpha(value)
    return c


def _shadow(widget: QWidget, color: str, blur: int = 28, alpha: int = 90, dy: int = 6) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(_alpha(color, alpha))
    widget.setGraphicsEffect(effect)


# Color fijo por objetivo: el mismo objetivo debe verse igual en toda
# la app (si se derivara del nombre del cliente, "Hipertrofia" saldría
# de un color distinto en cada tarjeta).
GOAL_COLORS = {
    "Hipertrofia": ACCENT_VIOLET,
    "Definición": ACCENT_PINK,
    "Fuerza": ACCENT_BLUE,
    "Rehabilitación": ACCENT_TEAL,
    "Resistencia": ACCENT_AMBER,
    "Postura": ACCENT_LIME,
}


def goal_color(goal: str) -> str:
    return GOAL_COLORS.get(goal, ACCENT_VIOLET)


# `strftime("%B")` depende del locale del sistema y sale en inglés en una
# instalación por defecto, así que los nombres van escritos aquí.
MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
WEEKDAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def format_date_es(when, with_time: bool = False) -> str:
    text = f"{when.day} de {MONTHS_ES[when.month - 1]} de {when.year}"
    if with_time:
        text += f"  ·  {when:%H:%M}"
    return text


def score_color(score: float | None) -> str:
    """Color semántico de un score 0-100 (mismo criterio en toda la app)."""
    if score is None:
        return TEXT_SECONDARY
    if score >= 85:
        return ACCENT_LIME
    if score >= 70:
        return ACCENT_TEAL
    if score >= 50:
        return ACCENT_AMBER
    return ACCENT_RED


def clear_layout(layout: QLayout) -> None:
    """
    Vacía un layout y quita de la pantalla lo que contenía.

    El `setParent(None)` es la parte importante y no es opcional:
    `deleteLater()` solo agenda el borrado para cuando el bucle de
    eventos vuelva a tener el control, así que sacar el widget del
    layout no basta. Mientras tanto el widget sigue siendo hijo de su
    contenedor y sigue dibujándose en la última posición que tuvo, ya
    sin layout que lo acomode. Al reconstruir una lista en el mismo
    turno (por ejemplo el historial de un cliente al abrir su perfil),
    eso hace que las filas viejas queden encimadas sobre las nuevas.
    Quitarle el padre lo saca de la pantalla en ese instante.
    """
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
            continue
        child = item.layout()
        if child is not None:
            clear_layout(child)
            child.deleteLater()


# ── Hoja de estilo global ────────────────────────────────────────────

_GLOBAL_QSS = f"""
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT_VIOLET};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px 4px 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG};
    border-radius: 4px;
    min-width: 32px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
    width: 0px;
}}
QToolTip {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 6px 10px;
}}
QDialog {{
    background-color: {BG_MAIN};
}}
QMessageBox {{
    background-color: {BG_CARD};
}}
QMessageBox QLabel {{
    color: {TEXT_PRIMARY};
}}
"""


def apply_app_theme() -> None:
    """
    Tema global de la aplicación. Se llama UNA vez al arrancar, antes de
    construir cualquier ventana — si solo se aplicara dentro de
    MainWindow, el Login y el Registro saldrían en tema claro y con el
    acento turquesa por defecto de qfluentwidgets.
    """
    setTheme(Theme.DARK)
    setThemeColor(QColor(ACCENT_VIOLET))

    app = QApplication.instance()
    if app is None:
        return

    font = QFont()
    font.setFamilies(FONT_STACK)
    app.setFont(font)

    # El QSS global va en la QApplication, NO en la ventana: qfluentwidgets
    # aplica su propia hoja de estilo a la FluentWindow con setStyleSheet(),
    # y ponerle otra encima la reemplaza — la barra lateral y la barra de
    # título se quedarían en tema claro sobre el contenido oscuro.
    app.setStyleSheet(_GLOBAL_QSS)


def apply_dark_theme(window: FluentWindow) -> None:
    """Llamar una vez, justo después de FluentWindow.__init__()."""
    apply_app_theme()
    window.setCustomBackgroundColor(QColor(BG_MAIN), QColor(BG_MAIN))


# ── Piezas básicas ───────────────────────────────────────────────────

class Card(QFrame):
    """
    Superficie redondeada con hairline. Contenedor genérico de sección.

    El layout interno se expone como `self.body` (NO `self.layout`):
    QWidget.layout() ya es un método de Qt y sombrearlo confunde al
    type-checker en cada `card.body.addWidget(...)`.
    """

    def __init__(self, parent: QWidget | None = None, padded: bool = True):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(
            f"""
            QFrame#card {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_CARD}px;
            }}
            """
        )
        self.body = QVBoxLayout(self)
        pad = (22, 20, 22, 20) if padded else (0, 0, 0, 0)
        self.body.setContentsMargins(*pad)
        self.body.setSpacing(12)

    def add_title(self, text: str, caption: str = "") -> None:
        """Encabezado interno de la tarjeta, con el tratamiento estándar."""
        self.body.addWidget(SectionTitle(text, caption))


class SectionTitle(QWidget):
    """Título de bloque dentro de una tarjeta o página."""

    def __init__(self, title: str, caption: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(self.title_label)

        self.caption_label = QLabel(caption)
        self.caption_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 12px; background: transparent; border: none;"
        )
        self.caption_label.setVisible(bool(caption))
        layout.addWidget(self.caption_label)

    def set_caption(self, caption: str) -> None:
        self.caption_label.setText(caption)
        self.caption_label.setVisible(bool(caption))


class PageHeader(QWidget):
    """Encabezado de página: título grande + subtítulo."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 27px; font-weight: 800; "
            f"letter-spacing: -0.5px; background: transparent; border: none;"
        )
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent; border: none;"
        )
        self.subtitle_label.setVisible(bool(subtitle))
        layout.addWidget(self.subtitle_label)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))


class Pill(QLabel):
    """Chip de estado: texto corto sobre un fondo teñido del color dado."""

    def __init__(self, text: str, color: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        tint = QColor(color)
        tint.setAlpha(38)
        self.setStyleSheet(
            f"background-color: rgba({tint.red()}, {tint.green()}, {tint.blue()}, 0.16); "
            f"color: {color}; font-size: 11px; font-weight: 700; "
            f"border: 1px solid rgba({tint.red()}, {tint.green()}, {tint.blue()}, 0.35); "
            f"border-radius: {RADIUS_PILL}px; padding: 3px 11px;"
        )


class IconBadge(QLabel):
    """
    Cuadro redondeado con degradado y un icono dentro.

    Acepta un FluentIcon (se dibuja monocromo en blanco, que es lo que
    se ve limpio sobre el degradado) o un emoji suelto como respaldo.
    """

    def __init__(
        self,
        icon: str | FluentIconBase,
        color: str,
        size: int = 46,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        deep = QColor(color).darker(140).name()
        self.setStyleSheet(
            f"background: {gradient(color, deep)}; color: white; "
            f"border-radius: {RADIUS_BADGE}px; border: none; "
            f"font-size: {int(size * 0.42)}px; font-weight: 800;"
        )

        if isinstance(icon, str):
            self.setText(icon)
        else:
            glyph = int(size * 0.5)
            self.setPixmap(icon.icon(color=QColor("#FFFFFF")).pixmap(glyph, glyph))


class Avatar(QLabel):
    """Círculo con las iniciales de una persona, coloreado de forma estable."""

    _PALETTE = (ACCENT_VIOLET, ACCENT_TEAL, ACCENT_BLUE, ACCENT_PINK, ACCENT_AMBER)

    def __init__(self, full_name: str, size: int = 44, parent: QWidget | None = None):
        super().__init__(self.initials(full_name), parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color = self.color_for(full_name)
        deep = QColor(color).darker(150).name()
        self.setStyleSheet(
            f"background: {gradient(color, deep)}; color: white; "
            f"border-radius: {size // 2}px; border: none; "
            f"font-size: {int(size * 0.34)}px; font-weight: 800;"
        )

    @classmethod
    def color_for(cls, full_name: str) -> str:
        return cls._PALETTE[sum(ord(c) for c in full_name) % len(cls._PALETTE)]

    @staticmethod
    def initials(full_name: str) -> str:
        parts = [p for p in full_name.strip().split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()


# ── Tarjetas de dato ─────────────────────────────────────────────────

class StatCard(QFrame):
    """Métrica destacada: badge con degradado + etiqueta + valor grande."""

    def __init__(
        self,
        icon: str | FluentIconBase,
        accent_color: str,
        title: str,
        value: str = "—",
        caption: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("statCard")
        self._accent = accent_color
        self.setStyleSheet(
            f"""
            QFrame#statCard {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_CARD}px;
            }}
            QFrame#statCard:hover {{
                background-color: {BG_CARD_HOVER};
                border: 1px solid {BORDER_STRONG};
            }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        layout.addWidget(IconBadge(icon, accent_color))

        text_col = QVBoxLayout()
        text_col.setSpacing(1)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 700; "
            f"letter-spacing: 0.4px; text-transform: uppercase; "
            f"background: transparent; border: none;"
        )
        text_col.addWidget(self.title_label)

        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 26px; font-weight: 800; "
            f"letter-spacing: -0.5px; background: transparent; border: none;"
        )
        text_col.addWidget(self.value_label)

        self.caption_label = QLabel(caption)
        self.caption_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; background: transparent; border: none;"
        )
        self.caption_label.setVisible(bool(caption))
        text_col.addWidget(self.caption_label)

        layout.addLayout(text_col)
        layout.addStretch(1)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_caption(self, caption: str) -> None:
        self.caption_label.setText(caption)
        self.caption_label.setVisible(bool(caption))

    def set_value_color(self, color: str) -> None:
        self.value_label.setStyleSheet(
            f"color: {color}; font-size: 26px; font-weight: 800; "
            f"letter-spacing: -0.5px; background: transparent; border: none;"
        )


class ListRow(QFrame):
    """
    Fila de lista — el reemplazo de las tablas en toda la app.

    Estructura: [avatar/badge] título + subtítulo … [valor + leyenda] [›]
    Es clickeable (señal `clicked`) y se resalta bajo el cursor, así que
    una lista de estas se lee como una bandeja de entrada moderna y no
    como una hoja de cálculo.
    """

    clicked = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        value: str = "",
        value_caption: str = "",
        value_color: str = TEXT_PRIMARY,
        leading: QWidget | None = None,
        pill: tuple[str, str] | None = None,
        clickable: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("listRow")
        self._clickable = clickable
        self._apply_style(hover=False)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 16, 11)
        layout.setSpacing(13)

        if leading is not None:
            layout.addWidget(leading)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 650; "
            f"background: transparent; border: none;"
        )
        title_row.addWidget(title_label)
        if pill is not None:
            title_row.addWidget(Pill(pill[0], pill[1]))
        title_row.addStretch(1)
        text_col.addLayout(title_row)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 12px; "
                f"background: transparent; border: none;"
            )
            text_col.addWidget(subtitle_label)

        layout.addLayout(text_col, stretch=1)

        if value:
            value_col = QVBoxLayout()
            value_col.setSpacing(0)
            value_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            value_label = QLabel(value)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            value_label.setStyleSheet(
                f"color: {value_color}; font-size: 19px; font-weight: 800; "
                f"letter-spacing: -0.3px; background: transparent; border: none;"
            )
            value_col.addWidget(value_label)

            if value_caption:
                caption_label = QLabel(value_caption)
                caption_label.setAlignment(Qt.AlignmentFlag.AlignRight)
                caption_label.setStyleSheet(
                    f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 600; "
                    f"letter-spacing: 0.3px; background: transparent; border: none;"
                )
                value_col.addWidget(caption_label)

            layout.addLayout(value_col)

        self._chevron: QLabel | None = None
        if clickable:
            self._chevron = QLabel("›")
            self._chevron.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 20px; font-weight: 700; "
                f"background: transparent; border: none;"
            )
            layout.addWidget(self._chevron)

    def add_trailing(self, widget: QWidget) -> None:
        """
        Agrega un control a la derecha (botones de acción de la fila).

        Va ANTES del chevron, no al final: el chevron indica "esta fila
        te lleva a otro lado" y tiene que quedar pegado al borde, que es
        donde el ojo lo busca. Un botón después de él rompe esa lectura.
        """
        layout = self.layout()
        if not isinstance(layout, QHBoxLayout):
            return
        if self._chevron is not None:
            layout.insertWidget(layout.indexOf(self._chevron), widget)
        else:
            layout.addWidget(widget)

    def _apply_style(self, hover: bool) -> None:
        bg = BG_CARD_HOVER if hover else BG_CARD
        border = BORDER_STRONG if hover else BORDER
        self.setStyleSheet(
            f"QFrame#listRow {{ background-color: {bg}; border: 1px solid {border}; "
            f"border-radius: {RADIUS_CARD - 4}px; }}"
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        if self._clickable:
            self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._clickable:
            self._apply_style(hover=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SelectableCard(QFrame):
    """
    Opción seleccionable con forma de tarjeta — reemplaza a ListWidget
    donde el usuario elige una cosa (un cliente, un músculo). Una lista
    de texto plano no comunica que se puede hacer clic; esto sí.
    """

    clicked = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        leading: QWidget | None = None,
        accent: str = ACCENT_VIOLET,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("selectableCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accent = accent
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 16, 11)
        layout.setSpacing(12)

        if leading is not None:
            layout.addWidget(leading)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 650; "
            f"background: transparent; border: none;"
        )
        text_col.addWidget(self._title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 12px; "
                f"background: transparent; border: none;"
            )
            text_col.addWidget(subtitle_label)

        layout.addLayout(text_col, stretch=1)

        self._check = QLabel("")
        self._check.setFixedSize(22, 22)
        self._check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._check)

        self._apply_style()

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def _apply_style(self, hover: bool = False) -> None:
        if self._selected:
            bg, border = BG_CARD_HOVER, self._accent
            self._check.setText("✓")
            self._check.setStyleSheet(
                f"background-color: {self._accent}; color: white; border-radius: 11px; "
                f"font-size: 13px; font-weight: 800; border: none;"
            )
        else:
            bg = BG_CARD_HOVER if hover else BG_ELEVATED
            border = BORDER_STRONG if hover else BORDER
            self._check.setText("")
            self._check.setStyleSheet(
                f"background: transparent; border: 1px solid {BORDER_STRONG}; "
                f"border-radius: 11px;"
            )

        self.setStyleSheet(
            f"QFrame#selectableCard {{ background-color: {bg}; "
            f"border: 1px solid {border}; border-radius: {RADIUS_CARD - 4}px; }}"
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        if not self._selected:
            self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._selected:
            self._apply_style(hover=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ClientCard(QFrame):
    """Tarjeta de cliente para la cuadrícula de "Mis clientes"."""

    clicked = Signal()

    def __init__(
        self,
        full_name: str,
        goal: str,
        evaluations_count: int,
        last_score: str,
        last_activity: str,
        score_value: float | None = None,
        profile_note: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("clientCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accent = Avatar.color_for(full_name)
        self._apply_style(hover=False)
        _shadow(self, "#000000", blur=24, alpha=110, dy=5)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Avatar(full_name, size=46))

        name_col = QVBoxLayout()
        name_col.setSpacing(3)
        name_label = QLabel(full_name)
        name_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        name_col.addWidget(name_label)

        goal_row = QHBoxLayout()
        goal_row.setSpacing(6)
        goal_row.addWidget(Pill(goal, goal_color(goal)))
        goal_row.addStretch(1)
        name_col.addLayout(goal_row)

        head.addLayout(name_col)
        head.addStretch(1)
        layout.addLayout(head)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {BORDER}; border: none;")
        layout.addWidget(divider)

        metrics = QHBoxLayout()
        metrics.setSpacing(24)
        metrics.addLayout(self._metric(str(evaluations_count), "evaluaciones", TEXT_PRIMARY))
        metrics.addLayout(self._metric(last_score, "último score", score_color(score_value)))
        metrics.addStretch(1)
        layout.addLayout(metrics)

        footer = QHBoxLayout()
        footer.setSpacing(8)

        activity_label = QLabel(last_activity)
        activity_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; background: transparent; border: none;"
        )
        footer.addWidget(activity_label)
        footer.addStretch(1)

        # Una ficha sin datos físicos limita lo que el generador de
        # rutinas puede calcular, así que se avisa aquí y no solo al
        # abrir el perfil.
        if profile_note:
            footer.addWidget(Pill(profile_note, ACCENT_AMBER))

        layout.addLayout(footer)

    @staticmethod
    def _metric(value: str, caption: str, color: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(0)
        value_label = QLabel(value)
        value_label.setStyleSheet(
            f"color: {color}; font-size: 20px; font-weight: 800; "
            f"letter-spacing: -0.3px; background: transparent; border: none;"
        )
        caption_label = QLabel(caption)
        caption_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 600; "
            f"letter-spacing: 0.3px; background: transparent; border: none;"
        )
        col.addWidget(value_label)
        col.addWidget(caption_label)
        return col

    def _apply_style(self, hover: bool) -> None:
        bg = BG_CARD_HOVER if hover else BG_CARD
        border = self._accent if hover else BORDER
        self.setStyleSheet(
            f"QFrame#clientCard {{ background-color: {bg}; border-radius: {RADIUS_CARD}px; "
            f"border: 1px solid {border}; }}"
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._apply_style(hover=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# ── Estados vacíos ───────────────────────────────────────────────────

class EmptyState(QWidget):
    """Mensaje centrado para listas sin datos, con emoji grande y guía."""

    def __init__(self, emoji: str, message: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 34, 20, 34)

        emoji_label = QLabel(emoji)
        emoji_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emoji_label.setFixedHeight(76)
        emoji_label.setStyleSheet(
            f"font-size: 46px; background-color: {BG_CARD}; "
            f"border: 1px solid {BORDER}; border-radius: 38px; "
        )
        emoji_label.setFixedWidth(76)

        emoji_row = QHBoxLayout()
        emoji_row.addStretch(1)
        emoji_row.addWidget(emoji_label)
        emoji_row.addStretch(1)
        layout.addLayout(emoji_row)

        self.message_label = QLabel(message)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; line-height: 20px; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(self.message_label)

    def set_message(self, message: str) -> None:
        self.message_label.setText(message)


# ── Visualizaciones ──────────────────────────────────────────────────

class Sparkline(QWidget):
    """
    Mini-gráfica de la envolvente EMG: área con degradado + trazo
    encima. Indicador visual, no interactivo.
    """

    def __init__(self, values: list[float], color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._values = values
        self._color = color
        self.setMinimumHeight(38)
        self.setMaximumHeight(38)

    def set_values(self, values: list[float]) -> None:
        self._values = values
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        if len(self._values) < 2:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        lo = min(self._values)
        hi = max(self._values)
        span = (hi - lo) or 1.0

        points = [
            QPointF(
                i / (len(self._values) - 1) * w,
                h - 3 - ((v - lo) / span) * (h - 8),
            )
            for i, v in enumerate(self._values)
        ]

        area = QPolygonF([QPointF(0.0, h), *points, QPointF(w, h)])
        fill = QLinearGradient(0.0, 0.0, 0.0, h)
        fill.setColorAt(0.0, _alpha(self._color, 110))
        fill.setColorAt(1.0, _alpha(self._color, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill))
        painter.drawPolygon(area)

        pen = QPen(QColor(self._color))
        pen.setWidthF(1.9)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))
        painter.end()


class ScoreRing(QWidget):
    """
    Anillo de progreso con el score al centro. Es la pieza "hero" de
    los reportes: comunica el resultado de un vistazo, sin leer cifras.
    """

    def __init__(
        self,
        value: float | None = None,
        size: int = 140,
        caption: str = "score",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._value = value
        self._caption = caption
        self.setFixedSize(size, size)

    def set_value(self, value: float | None) -> None:
        self._value = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        thickness = max(8.0, self.width() * 0.075)
        inset = thickness / 2 + 2
        rect = QRectF(inset, inset, self.width() - inset * 2, self.height() - inset * 2)

        track = QPen(QColor(BORDER))
        track.setWidthF(thickness)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)

        color = score_color(self._value)
        if self._value is not None:
            arc = QPen(QColor(color))
            arc.setWidthF(thickness)
            arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc)
            span = int(max(0.0, min(100.0, self._value)) / 100 * 360 * 16)
            painter.drawArc(rect, 90 * 16, -span)

        painter.setPen(QColor(TEXT_PRIMARY if self._value is not None else TEXT_SECONDARY))
        value_font = QFont()
        value_font.setFamilies(FONT_STACK)
        value_font.setPixelSize(int(self.width() * 0.26))
        value_font.setWeight(QFont.Weight.ExtraBold)
        painter.setFont(value_font)

        text = f"{self._value:.0f}%" if self._value is not None else "—"
        value_rect = QRectF(0, self.height() * 0.28, self.width(), self.height() * 0.30)
        painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, text)

        painter.setPen(QColor(TEXT_MUTED))
        caption_font = QFont()
        caption_font.setFamilies(FONT_STACK)
        caption_font.setPixelSize(int(self.width() * 0.085))
        caption_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(caption_font)
        caption_rect = QRectF(0, self.height() * 0.56, self.width(), self.height() * 0.16)
        painter.drawText(caption_rect, Qt.AlignmentFlag.AlignCenter, self._caption)
        painter.end()


class MeterBar(QWidget):
    """
    Barra horizontal 0-100% con relleno degradado. Para comparar
    activación entre canales sin recurrir a una gráfica completa.
    """

    def __init__(
        self,
        value: float = 0.0,
        color: str = ACCENT_TEAL,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._value = value
        self._color = color
        self.setFixedHeight(10)

    def set_value(self, value: float) -> None:
        self._value = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        h = float(self.height())
        radius = h / 2

        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, float(self.width()), h), radius, radius)
        painter.fillPath(track, QColor(BG_ELEVATED))

        pct = max(0.0, min(100.0, self._value)) / 100.0
        if pct > 0:
            width = max(h, self.width() * pct)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(QRectF(0, 0, width, h), radius, radius)
            grad = QLinearGradient(0.0, 0.0, width, 0.0)
            grad.setColorAt(0.0, QColor(self._color).darker(130))
            grad.setColorAt(1.0, QColor(self._color))
            painter.fillPath(fill_path, QBrush(grad))
        painter.end()


class StepProgressBar(QWidget):
    """
    Stepper del wizard: círculos numerados sobre una pista continua que
    se rellena conforme se avanza. `set_current(0)` = nada iniciado.
    """

    def __init__(self, total_steps: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.total_steps = total_steps
        self._dots: list[QLabel] = []
        self._lines: list[QFrame] = []
        self._build_ui()
        self.set_current(0)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for i in range(self.total_steps):
            dot = QLabel(str(i + 1))
            dot.setFixedSize(26, 26)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(dot)
            self._dots.append(dot)

            if i < self.total_steps - 1:
                line = QFrame()
                line.setFixedHeight(3)
                line.setMinimumWidth(18)
                layout.addWidget(line, stretch=1)
                self._lines.append(line)

    def set_current(self, step: int) -> None:
        """`step` es 1-indexado (Paso 1..N). 0 = todavía no se elige nada."""
        for i, dot in enumerate(self._dots):
            idx = i + 1
            if idx < step:
                dot.setStyleSheet(
                    f"background: {gradient(ACCENT_TEAL, QColor(ACCENT_TEAL).darker(140).name())}; "
                    f"color: {BG_MAIN}; border-radius: 13px; "
                    f"font-weight: 800; font-size: 12px; border: none;"
                )
            elif idx == step:
                dot.setStyleSheet(
                    f"background: {gradient(ACCENT_VIOLET, ACCENT_VIOLET_DEEP)}; "
                    f"color: white; border-radius: 13px; "
                    f"font-weight: 800; font-size: 12px; "
                    f"border: 2px solid {ACCENT_VIOLET};"
                )
            else:
                dot.setStyleSheet(
                    f"background-color: {BG_ELEVATED}; color: {TEXT_MUTED}; "
                    f"border-radius: 13px; font-weight: 700; font-size: 12px; "
                    f"border: 1px solid {BORDER};"
                )

        for i, line in enumerate(self._lines):
            color = ACCENT_TEAL if (i + 1) < step else BORDER
            line.setStyleSheet(f"background-color: {color}; border: none; border-radius: 1px;")


# ── Navegación ───────────────────────────────────────────────────────

class BackButton(QFrame):
    """
    Botón de volver estándar de la app.

    Hasta ahora ninguna pantalla tenía uno propio. La única forma de
    retroceder era la flecha que FluentWindow pone arriba del menú
    lateral, que se quitó porque no correspondía a la navegación real:
    esa flecha solo deshacía cambios de sección, no pasos dentro de una
    pantalla. Este botón vive dentro del contenido y lo controla la
    vista que lo coloca, así que sí retrocede a donde el usuario espera.
    """

    clicked = Signal()

    def __init__(
        self,
        text: str = "Volver",
        accent: str = ACCENT_VIOLET,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("backButton")
        self._accent = accent
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 15, 5)
        layout.setSpacing(9)

        self._chevron = QLabel("←")
        self._chevron.setFixedSize(28, 28)
        self._chevron.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._chevron)

        self._label = QLabel(text)
        layout.addWidget(self._label)

        self._apply_style(hover=False)

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def _apply_style(self, hover: bool) -> None:
        bg = BG_CARD_HOVER if hover else BG_CARD
        border = self._accent if hover else BORDER
        self.setStyleSheet(
            f"QFrame#backButton {{ background-color: {bg}; "
            f"border: 1px solid {border}; border-radius: 19px; }}"
        )
        self._chevron.setStyleSheet(
            f"background-color: {self._accent if hover else BG_ELEVATED}; "
            f"color: {'white' if hover else TEXT_SECONDARY}; "
            f"border-radius: 14px; font-size: 15px; font-weight: 700; border: none;"
        )
        self._label.setStyleSheet(
            f"color: {TEXT_PRIMARY if hover else TEXT_SECONDARY}; font-size: 13px; "
            f"font-weight: 600; background: transparent; border: none;"
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._apply_style(hover=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ActionTile(QFrame):
    """
    Acción principal con forma de tarjeta grande: ícono, título y una
    línea que explica qué pasa al tocarla.

    Es para las cosas que el entrenador hace todos los días. Un botón
    normal del tamaño del texto se pierde entre el resto de la pantalla,
    y la acción más frecuente de la app no debería costar trabajo
    encontrarla.
    """

    clicked = Signal()

    def __init__(
        self,
        icon,
        title: str,
        caption: str,
        accent: str = ACCENT_VIOLET,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("actionTile")
        self._accent = accent
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(13)
        layout.addWidget(IconBadge(icon, accent, size=42))

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        text_col.addWidget(title_label)

        caption_label = QLabel(caption)
        caption_label.setWordWrap(True)
        caption_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; "
            f"background: transparent; border: none;"
        )
        text_col.addWidget(caption_label)

        layout.addLayout(text_col, stretch=1)

        self._chevron = QLabel("›")
        self._chevron.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 20px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(self._chevron)

        self._apply_style(hover=False)

    def _apply_style(self, hover: bool) -> None:
        bg = BG_CARD_HOVER if hover else BG_CARD
        border = self._accent if hover else BORDER
        self.setStyleSheet(
            f"QFrame#actionTile {{ background-color: {bg}; "
            f"border: 1px solid {border}; border-radius: {RADIUS_CARD}px; }}"
        )
        self._chevron.setStyleSheet(
            f"color: {self._accent if hover else TEXT_MUTED}; font-size: 20px; "
            f"font-weight: 700; background: transparent; border: none;"
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._apply_style(hover=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DataChip(QFrame):
    """
    Dato suelto de ficha: valor arriba, etiqueta abajo.

    Se usa para los datos físicos del cliente (edad, sexo, estatura,
    peso, IMC), donde hay varios valores cortos que conviene leer de un
    golpe y que no ameritan una StatCard completa cada uno.
    """

    def __init__(
        self,
        value: str,
        caption: str,
        color: str = TEXT_PRIMARY,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("dataChip")
        self.setStyleSheet(
            f"QFrame#dataChip {{ background-color: {BG_ELEVATED}; "
            f"border: 1px solid {BORDER}; border-radius: 12px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 9, 13, 9)
        layout.setSpacing(1)

        self._value_label = QLabel(value)
        self._value_label.setStyleSheet(
            f"color: {color}; font-size: 17px; font-weight: 800; "
            f"letter-spacing: -0.3px; background: transparent; border: none;"
        )
        layout.addWidget(self._value_label)

        caption_label = QLabel(caption)
        caption_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 600; "
            f"letter-spacing: 0.3px; background: transparent; border: none;"
        )
        layout.addWidget(caption_label)

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)


# ── Visualización de actividad ───────────────────────────────────────

class ActivityChart(QWidget):
    """
    Barras de actividad por periodo (por ejemplo evaluaciones por
    semana). Cada barra lleva su valor arriba y su etiqueta abajo.

    No usa PyQtGraph a propósito: esto no es una señal que se recorra ni
    se haga zoom, son seis u ocho números. Dibujarlo a mano evita cargar
    un motor de gráficas completo para algo que no se va a explorar, y
    deja el resultado alineado con el resto del diseño.
    """

    def __init__(
        self,
        values: list[float] | None = None,
        labels: list[str] | None = None,
        color: str = ACCENT_VIOLET,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._values = list(values or [])
        self._labels = list(labels or [])
        self._color = color
        self.setMinimumHeight(150)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_data(self, values: list[float], labels: list[str]) -> None:
        self._values = list(values)
        self._labels = list(labels)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        if not self._values:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        label_height = 18
        value_height = 16
        width = self.width()
        height = self.height()
        plot_top = value_height
        plot_bottom = height - label_height
        plot_height = max(1, plot_bottom - plot_top)

        count = len(self._values)
        slot = width / count
        bar_width = min(38.0, slot * 0.58)
        # Si todo está en cero, `peak` evita dividir entre cero y deja
        # las barras al mínimo visible en vez de desaparecer.
        peak = max(self._values) or 1.0

        # Línea base
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawLine(0, plot_bottom, width, plot_bottom)

        for index, value in enumerate(self._values):
            center = slot * (index + 0.5)
            bar_height = max(3.0, (value / peak) * plot_height)
            rect = QRectF(
                center - bar_width / 2,
                plot_bottom - bar_height,
                bar_width,
                bar_height,
            )

            is_last = index == count - 1
            base = QColor(self._color) if is_last else QColor(BORDER_STRONG)

            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            fill.setColorAt(0.0, base)
            fill.setColorAt(1.0, _alpha(base.name(), 70))

            path = QPainterPath()
            path.addRoundedRect(rect, 7, 7)
            painter.fillPath(path, QBrush(fill))

            # Valor encima de la barra (solo si hay algo que contar)
            if value > 0:
                painter.setPen(QPen(QColor(TEXT_PRIMARY if is_last else TEXT_SECONDARY)))
                font = painter.font()
                font.setPixelSize(11)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(
                    QRectF(center - slot / 2, plot_bottom - bar_height - value_height,
                           slot, value_height),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{value:.0f}",
                )

            if index < len(self._labels):
                painter.setPen(QPen(QColor(TEXT_PRIMARY if is_last else TEXT_MUTED)))
                font = painter.font()
                font.setPixelSize(10)
                font.setBold(is_last)
                painter.setFont(font)
                painter.drawText(
                    QRectF(center - slot / 2, plot_bottom + 2, slot, label_height),
                    Qt.AlignmentFlag.AlignCenter,
                    self._labels[index],
                )

        painter.end()
