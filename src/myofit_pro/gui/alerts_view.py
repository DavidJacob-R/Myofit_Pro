"""
Alertas — equivalente a AlertsView.xaml. Dos tipos de alerta, ambas
calculadas de datos reales (no simuladas):

  1. Batería baja de algún sensor conectado (< 2.6V)
  2. Calibraciones MVC vencidas: la última calibración de un cliente
     para un músculo tiene más de 30 días -- se recomienda recalibrar
     antes de la próxima evaluación de ese músculo, porque la
     colocación de electrodos pudo haber cambiado.
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets.common.icon import FluentIconBase

from myofit_pro.gui.theme import ACCENT_AMBER, ACCENT_RED, EmptyState, PageHeader, StatCard

_Alert = tuple[FluentIconBase, str, str, str]

_RECALIBRATION_DAYS = 30
_LOW_BATTERY_VOLTS = 2.6


class AlertsView(QWidget):
    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 20, 24, 24)
        self._layout.setSpacing(14)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.refresh()

        self._timer = QTimer(self)
        self._timer.setInterval(10000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def refresh(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        alerts = self._collect_battery_alerts() + self._collect_recalibration_alerts()

        self._layout.addWidget(
            PageHeader(
                "Alertas",
                f"{len(alerts)} alerta(s) activa(s)" if alerts else "Todo en orden",
            )
        )

        if not alerts:
            self._layout.addWidget(
                EmptyState("", "Sin alertas por el momento.\nTodo funciona correctamente.")
            )
            return

        for icon, color, title, detail in alerts:
            self._layout.addWidget(StatCard(icon, color, title, detail))

        self._layout.addStretch(1)

    def _collect_battery_alerts(self) -> list[_Alert]:
        alerts: list[_Alert] = []
        if not self.state.sensors.is_connected:
            return alerts
        for i, label in ((0, "A"), (1, "B")):
            volts = self.state.sensors.channels[i].battery_volts
            if 0 < volts < _LOW_BATTERY_VOLTS:
                alerts.append((
                    FIF.POWER_BUTTON, ACCENT_RED, f"Batería baja — Sensor {label}",
                    f"{volts:.2f} V · cárgalo antes de la próxima evaluación",
                ))
        return alerts

    def _collect_recalibration_alerts(self) -> list[_Alert]:
        alerts: list[_Alert] = []
        clients = self.state.client_repo.list_for_trainer(self.state.current_trainer.id)
        cutoff = dt.datetime.now() - dt.timedelta(days=_RECALIBRATION_DAYS)

        for client in clients:
            calibrations = self.state.calibration_repo.list_for_client(client.id)
            seen_muscles: set[int] = set()
            for calib in calibrations:  # ya viene ordenado por más reciente primero
                if calib.muscle_id in seen_muscles:
                    continue
                seen_muscles.add(calib.muscle_id)
                if calib.recorded_at < cutoff:
                    muscle = self.state.muscle_repo.get(calib.muscle_id)
                    days_ago = (dt.datetime.now() - calib.recorded_at).days
                    alerts.append((
                        FIF.DATE_TIME, ACCENT_AMBER,
                        f"Recalibrar {muscle.name if muscle else '—'} — {client.full_name}",
                        f"Última calibración hace {days_ago} días",
                    ))
        return alerts