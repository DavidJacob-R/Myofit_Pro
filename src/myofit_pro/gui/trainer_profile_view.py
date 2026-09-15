"""Mi perfil — equivalente a TrainerProfileView.xaml."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, LineEdit, PasswordLineEdit, PrimaryPushButton, PushButton

from myofit_pro.gui.theme import Card, PageHeader


class TrainerProfileView(QWidget):
    logout_requested = Signal()

    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(PageHeader("Mi perfil", "Configuración de tu cuenta"))

        # ── Datos personales ──────────────────────────────────────
        data_card = Card()
        data_card.body.addWidget(BodyLabel("👤  Datos personales"))

        data_card.body.addWidget(BodyLabel("Nombre completo"))
        self.name_input = LineEdit(data_card)
        self.name_input.setText(self.state.current_trainer.full_name)
        data_card.body.addWidget(self.name_input)

        data_card.body.addWidget(BodyLabel("Correo electrónico"))
        self.email_input = LineEdit(data_card)
        self.email_input.setText(self.state.current_trainer.email)
        data_card.body.addWidget(self.email_input)

        save_btn = PrimaryPushButton("Guardar cambios")
        save_btn.clicked.connect(self._on_save_clicked)
        data_card.body.addWidget(save_btn)

        layout.addWidget(data_card)

        # ── Cambiar contraseña ────────────────────────────────────
        password_card = Card()
        password_card.body.addWidget(BodyLabel("🔒  Cambiar contraseña"))

        self.current_password_input = PasswordLineEdit(password_card)
        self.current_password_input.setPlaceholderText("Contraseña actual")
        password_card.body.addWidget(self.current_password_input)

        self.new_password_input = PasswordLineEdit(password_card)
        self.new_password_input.setPlaceholderText("Nueva contraseña")
        password_card.body.addWidget(self.new_password_input)

        self.confirm_password_input = PasswordLineEdit(password_card)
        self.confirm_password_input.setPlaceholderText("Confirmar nueva contraseña")
        password_card.body.addWidget(self.confirm_password_input)

        change_btn = PrimaryPushButton("Cambiar contraseña")
        change_btn.clicked.connect(self._on_change_password_clicked)
        password_card.body.addWidget(change_btn)

        layout.addWidget(password_card)

        # ── Sesión ────────────────────────────────────────────────
        session_card = Card()
        session_card.body.addWidget(BodyLabel("🚪  Sesión"))
        logout_btn = PushButton("Cerrar sesión")
        logout_btn.clicked.connect(self._on_logout_clicked)
        session_card.body.addWidget(logout_btn)
        layout.addWidget(session_card)

    def _on_save_clicked(self) -> None:
        name = self.name_input.text().strip()
        email = self.email_input.text().strip()
        if not name or not email:
            QMessageBox.warning(self, "Datos incompletos", "Completa nombre y correo.")
            return

        self.state.trainer_repo.update_profile(self.state.current_trainer.id, name, email)
        self.state.current_trainer.full_name = name
        self.state.current_trainer.email = email
        QMessageBox.information(self, "Guardado", "Perfil actualizado correctamente.")

    def _on_change_password_clicked(self) -> None:
        current = self.current_password_input.text()
        new = self.new_password_input.text()
        confirm = self.confirm_password_input.text()

        if not all([current, new, confirm]):
            QMessageBox.warning(self, "Datos incompletos", "Completa los tres campos.")
            return
        if new != confirm:
            QMessageBox.warning(self, "Error", "Las contraseñas nuevas no coinciden.")
            return

        ok = self.state.trainer_repo.change_password(
            self.state.current_trainer.id, current, new
        )
        if not ok:
            QMessageBox.critical(self, "Error", "La contraseña actual no es correcta.")
            return

        self.current_password_input.clear()
        self.new_password_input.clear()
        self.confirm_password_input.clear()
        QMessageBox.information(self, "Listo", "Contraseña actualizada correctamente.")

    def _on_logout_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Cerrar sesión",
            "¿Seguro que quieres cerrar sesión?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.logout_requested.emit()