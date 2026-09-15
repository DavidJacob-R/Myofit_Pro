"""Equivalente a LoginView.xaml / LoginView.xaml.cs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import LineEdit, PasswordLineEdit, PrimaryPushButton, PushButton

from myofit_pro.database import TrainerRepository, get_engine
from myofit_pro.database.models import Trainer
from myofit_pro.gui.theme import ACCENT_VIOLET, BG_MAIN, Card, IconBadge, PageHeader


class LoginView(QWidget):
    """Emite `login_success` con el Trainer autenticado."""

    login_success = Signal(object)          # Trainer
    go_to_register = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._trainer_repo = TrainerRepository(get_engine().get_session)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"background-color: {BG_MAIN};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = Card()
        card.setFixedWidth(420)
        card.body.setSpacing(12)
        card.body.setContentsMargins(32, 30, 32, 30)

        logo_row = QHBoxLayout()
        logo_row.addWidget(IconBadge(FIF.SPEED_HIGH, ACCENT_VIOLET, size=54))
        logo_row.addStretch(1)
        card.body.addLayout(logo_row)
        card.body.addSpacing(4)

        card.body.addWidget(PageHeader("MyoFit Pro", "Evaluación sEMG para entrenadores"))
        card.body.addSpacing(14)

        self.email_input = LineEdit(card)
        self.email_input.setPlaceholderText("Correo electrónico")
        self.email_input.setClearButtonEnabled(True)
        card.body.addWidget(self.email_input)

        self.password_input = PasswordLineEdit(card)
        self.password_input.setPlaceholderText("Contraseña")
        self.password_input.returnPressed.connect(self._on_login_clicked)
        card.body.addWidget(self.password_input)

        card.body.addSpacing(6)

        login_btn = PrimaryPushButton("Iniciar sesión")
        login_btn.clicked.connect(self._on_login_clicked)
        card.body.addWidget(login_btn)

        register_btn = PushButton("Crear cuenta nueva")
        register_btn.clicked.connect(self.go_to_register.emit)
        card.body.addWidget(register_btn)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)

    def _on_login_clicked(self) -> None:
        email = self.email_input.text().strip()
        password = self.password_input.text()

        if not email or not password:
            QMessageBox.warning(self, "Datos incompletos", "Ingresa tu correo y contraseña.")
            return

        trainer: Trainer | None = self._trainer_repo.authenticate(email, password)
        if trainer is None:
            QMessageBox.critical(self, "Error", "Correo o contraseña incorrectos.")
            return

        self.login_success.emit(trainer)