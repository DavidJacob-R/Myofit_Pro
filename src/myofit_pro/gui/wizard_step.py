"""
Contrato que cumplen los pasos del asistente de evaluación.

Antes cada paso dibujaba su propio botón de continuar al final de su
contenido, y el de volver vivía arriba en el encabezado del contenedor.
Eso dejaba las dos acciones de navegación en extremos opuestos de la
pantalla y con estilos distintos en cada paso.

Ahora el contenedor dibuja un pie único con los dos botones juntos, y le
pregunta al paso actual qué dice su botón de continuar, si se puede
presionar y qué hacer cuando se presiona. El paso se queda solo con su
contenido.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class WizardStep(QWidget):
    """
    Un paso del asistente.

    Lo único obligatorio es emitir `continue_state_changed` cuando
    cambie el resultado de `can_continue()`, porque el botón vive fuera
    del paso y no tiene forma de enterarse solo.
    """

    continue_state_changed = Signal()

    # Texto del botón de continuar. Cada paso lo cambia por lo que de
    # verdad va a pasar al presionarlo ("Guardar y continuar" no es lo
    # mismo que "Ya coloqué los sensores").
    CONTINUE_LABEL = "Continuar  →"

    def can_continue(self) -> bool:
        """False mientras falte algo. El contenedor deshabilita el botón."""
        return True

    def blocked_reason(self) -> str:
        """Qué falta, para poder decirlo si el usuario insiste."""
        return ""

    def on_continue(self) -> bool:
        """
        Ejecuta lo que le toca al paso (guardar, crear la sesión) y
        devuelve True si el asistente debe avanzar. Devolver False deja
        al usuario en el paso, que es lo que hace falta cuando la acción
        no se pudo completar.
        """
        return True

    def on_enter(self) -> None:
        """Se llama cada vez que el paso se muestra."""
