"""Contrato que cumplen los pasos del asistente de evaluación.

Posición en el flujo
--------------------
Clase base de las seis vistas ``evaluation_stepN_view``. La consume
`myofit_pro.gui.evaluation_wizard.EvaluationWizard`, que dibuja el pie de
navegación común y consulta al paso activo qué debe mostrar en él.

Reparto de responsabilidades
----------------------------
El contenedor dibuja un pie único con los botones de retroceso y avance
juntos, y pregunta al paso activo qué texto lleva el botón de continuar,
si puede pulsarse y qué debe ocurrir al hacerlo. El paso se ocupa
únicamente de su contenido.

La alternativa —que cada paso dibujara su propio botón de avance al final
de su contenido, con el de retroceso en el encabezado del contenedor—
dejaba las dos acciones de navegación en extremos opuestos de la pantalla
y con estilos distintos en cada paso.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class WizardStep(QWidget):
    """Clase base de los pasos del asistente de evaluación.

    Attributes
    ----------
    continue_state_changed : PySide6.QtCore.Signal
        Debe emitirse siempre que cambie el resultado de `can_continue`.
        Es el único requisito ineludible de la subclase: el botón reside
        fuera del paso y no puede detectar el cambio por sí mismo.
    CONTINUE_LABEL : str
        Texto del botón de avance. Cada paso lo redefine con la acción
        que realmente ejecuta, que no siempre es continuar.
    """

    continue_state_changed = Signal()

    CONTINUE_LABEL = "Continuar  →"

    def can_continue(self) -> bool:
        """Si el paso está completo.

        Returns
        -------
        bool
            Falso mientras falte algún dato, en cuyo caso el contenedor
            deshabilita el botón de avance.
        """
        return True

    def blocked_reason(self) -> str:
        """Motivo por el que el paso no puede completarse.

        Returns
        -------
        str
            Texto que el contenedor muestra si el usuario insiste en
            avanzar con el paso incompleto.
        """
        return ""

    def on_continue(self) -> bool:
        """Ejecuta la acción del paso y decide si el asistente avanza.

        Returns
        -------
        bool
            Cierto si debe pasarse al paso siguiente. Falso mantiene al
            usuario en el paso actual, que es el comportamiento
            adecuado cuando la acción no pudo completarse.
        """
        return True

    def on_enter(self) -> None:
        """Se invoca cada vez que el paso pasa a estar visible."""
