"""
Punto de entrada de MyoFit Pro.

Flujo: LoginView <-> RegisterView -> MainWindow -> (cerrar sesión) -> LoginView
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from myofit_pro.database.models import Trainer
from myofit_pro.gui.login_view import LoginView
from myofit_pro.gui.main_window import MainWindow
from myofit_pro.gui.register_view import RegisterView
from myofit_pro.gui.theme import BG_MAIN, apply_app_theme


class AuthWindow(QWidget):
    """Contenedor simple que alterna entre Login y Register."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MyoFit Pro — Acceso")
        self.resize(520, 560)
        self.setStyleSheet(f"background-color: {BG_MAIN};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack)

        self.login_view = LoginView()
        self.register_view = RegisterView()
        self.stack.addWidget(self.login_view)
        self.stack.addWidget(self.register_view)

        self.main_window: MainWindow | None = None

        self.login_view.go_to_register.connect(
            lambda: self.stack.setCurrentWidget(self.register_view)
        )
        self.register_view.go_to_login.connect(
            lambda: self.stack.setCurrentWidget(self.login_view)
        )

        self.login_view.login_success.connect(self._on_authenticated)
        self.register_view.register_success.connect(self._on_authenticated)

    def _on_authenticated(self, trainer: Trainer) -> None:
        self.main_window = MainWindow(trainer)
        self.main_window.logout_requested.connect(self._on_logout)
        self.main_window.show()
        self.hide()

    def _on_logout(self) -> None:
        """Volver a la pantalla de login tras cerrar sesión."""
        self.main_window = None
        self.login_view.password_input.clear()
        self.stack.setCurrentWidget(self.login_view)
        self.show()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MyoFit Pro")
    apply_app_theme()

    auth_window = AuthWindow()
    auth_window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())