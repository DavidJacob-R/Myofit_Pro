"""Selector de cliente con búsqueda por texto.

Posición en el flujo
--------------------
Control reutilizable, empleado en todos los puntos donde hay que elegir
un cliente —historial, rutinas— de modo que el gesto sea el mismo en toda
la aplicación.

Motivo
------
Un desplegable resulta cómodo con cinco clientes e impracticable con
cincuenta, ya que obliga a recorrer la lista en busca de un nombre que ya
se conoce. Este control permite escribir y filtra conforme se teclea, sin
dejar de funcionar como desplegable para quien prefiera elegir de la
lista.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCompleter, QWidget
from qfluentwidgets import EditableComboBox


class ClientPicker(EditableComboBox):
    """Desplegable de clientes editable, con filtrado por texto.

    Parameters
    ----------
    parent : PySide6.QtWidgets.QWidget, optional
        Widget padre.
    placeholder : str, default="Buscar cliente..."
        Texto de sugerencia del campo.

    Attributes
    ----------
    client_changed : PySide6.QtCore.Signal
        Emite el `myofit_pro.database.models.Client` seleccionado, o
        `None` cuando el texto escrito no corresponde a ninguno. En los
        filtros, `None` equivale a no filtrar.
    """

    client_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None, placeholder: str = "Buscar cliente..."):
        super().__init__(parent)
        self._clients: list = []
        self.setPlaceholderText(placeholder)
        self.setMinimumWidth(240)
        self.currentTextChanged.connect(self._on_text_changed)

    def set_clients(self, clients: list, keep: object = None) -> None:
        """Carga la lista de clientes.

        Parameters
        ----------
        clients : list
            Clientes disponibles.
        keep : myofit_pro.database.models.Client, optional
            Cliente que debe quedar seleccionado si sigue existiendo. Si
            se omite, se conserva el que estuviera seleccionado.

        Notes
        -----
        El autocompletado se reconstruye con cada carga: uno anterior
        seguiría ofreciendo clientes que ya no figuran en la lista.
        """
        anterior = keep if keep is not None else self.current_client()
        nombres = [c.full_name for c in clients]

        self.blockSignals(True)
        self.clear()
        self._clients = list(clients)
        if nombres:
            self.addItems(nombres)

        completer = QCompleter(nombres, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(completer)

        if anterior is not None and anterior.full_name in nombres:
            self.setCurrentIndex(nombres.index(anterior.full_name))
        elif nombres:
            self.setCurrentIndex(0)
        self.blockSignals(False)

        self.client_changed.emit(self.current_client())

    def current_client(self):
        """Cliente correspondiente al texto actual.

        Returns
        -------
        myofit_pro.database.models.Client or None
            El cliente cuyo nombre coincide exactamente con lo escrito,
            o `None` si no hay coincidencia.
        """
        texto = self.currentText().strip()
        for client in self._clients:
            if client.full_name == texto:
                return client
        return None

    def select(self, client) -> None:
        """Selecciona un cliente concreto.

        Parameters
        ----------
        client : myofit_pro.database.models.Client
            Cliente a seleccionar. Si no figura en la lista, no se hace
            nada.
        """
        nombres = [c.full_name for c in self._clients]
        if client is not None and client.full_name in nombres:
            self.setCurrentIndex(nombres.index(client.full_name))

    def clear_selection(self) -> None:
        """Vacía el campo, lo que en los filtros equivale a no filtrar.

        Notes
        -----
        Se emplea ``setText`` y no ``setCurrentText``: en el desplegable
        editable de qfluentwidgets este último solo acepta texto ya
        presente en la lista, por lo que no puede vaciar el campo.
        """
        self.setText("")
        self.client_changed.emit(None)

    def _on_text_changed(self, _text: str) -> None:
        """Notifica el cambio de selección al editarse el texto."""
        self.client_changed.emit(self.current_client())
