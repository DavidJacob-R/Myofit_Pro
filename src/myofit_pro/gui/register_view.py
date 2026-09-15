"""Equivalente a RegisterView.xaml / RegisterView.xaml.cs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget
from qfluentwidgets import LineEdit, PasswordLineEdit, PrimaryPushButton, PushButton

from myofit_pro.database import TrainerRepository, get_engine
from myofit_pro.gui.theme import BG_MAIN, Card, PageHeader


class RegisterView(QWidget):
    register_success = Signal(object)   # Trainer
    go_to_login = Signal()

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
        card.setMaximumWidth(420)
        card.body.setSpacing(12)

        card.body.addWidget(PageHeader("Crear cuenta", "Regístrate como entrenador"))
        card.body.addSpacing(10)

        self.name_input = LineEdit(card)
        self.name_input.setPlaceholderText("Nombre completo")
        card.body.addWidget(self.name_input)

        self.email_input = LineEdit(card)
        self.email_input.setPlaceholderText("Correo electrónico")
        card.body.addWidget(self.email_input)

        self.password_input = PasswordLineEdit(card)
        self.password_input.setPlaceholderText("Contraseña")
        card.body.addWidget(self.password_input)

        self.confirm_input = PasswordLineEdit(card)
        self.confirm_input.setPlaceholderText("Confirmar contraseña")
        self.confirm_input.returnPressed.connect(self._on_register_clicked)
        card.body.addWidget(self.confirm_input)

        card.body.addSpacing(6)

        create_btn = PrimaryPushButton("Crear cuenta")
        create_btn.clicked.connect(self._on_register_clicked)
        card.body.addWidget(create_btn)

        back_btn = PushButton("Ya tengo cuenta")
        back_btn.clicked.connect(self.go_to_login.emit)
        card.body.addWidget(back_btn)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)

    def _on_register_clicked(self) -> None:
        name = self.name_input.text().strip()
        email = self.email_input.text().strip()
        password = self.password_input.text()
        confirm = self.confirm_input.text()

        if not all([name, email, password]):
            QMessageBox.warning(self, "Datos incompletos", "Completa todos los campos.")
            return
        if password != confirm:
            QMessageBox.warning(self, "Error", "Las contraseñas no coinciden.")
            return

        try:
            trainer = self._trainer_repo.register(name, email, password)
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"No se pudo crear la cuenta: {ex}")
            return

        self.register_success.emit(trainer)