from __future__ import annotations

from optiwin.tweaks.base import Risk, Tweak
from optiwin.tweaks.registry_tweak import RegistryValueTweak


def tweaks() -> list[Tweak]:
    return [
        RegistryValueTweak(
            id="visual.transparencia",
            name="Efectos de transparencia",
            category="visual",
            description=(
                "Desactiva la transparencia (efecto acrílico/Mica) de la barra de tareas, menús "
                "y ventanas. Se aplica al instante, sin reiniciar."
            ),
            risk=Risk.LOW,
            benefit="Pequeño ahorro de GPU y batería; más notable en gráficos integrados.",
            hive="HKCU",
            key=r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            value_name="EnableTransparency",
            default_value=0,
        ),
    ]
