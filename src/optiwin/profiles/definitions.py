"""Perfiles de optimización: diccionarios {id_de_ajuste: valor} sobre el catálogo de ajustes.

Un perfil no toca el sistema por sí mismo: solo dice qué ajustes aplicar y con qué valor, así que
todo hereda simulación, "Deshacer" y registro del motor. Los ajustes de la versión AC (enchufado)
y DC (batería) son independientes: el que importa en cada momento es el de la fuente actual.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    description: str
    steps: dict[str, int] = field(default_factory=dict)
    include_gpu_apps: bool = False  # añade los juegos configurados con GPU dedicada
    closes_processes: bool = False  # cierra la lista de procesos al activar A MANO


AHORRO = Profile(
    id="ahorro",
    name="Ahorro de batería",
    description="Máxima autonomía: CPU limitada a 70 %, sin boost, pantalla y disco que se apagan pronto.",
    steps={
        "energia.cpu_max_bateria": 70,
        "energia.cpu_min_bateria": 5,
        "energia.cpu_boost_bateria": 0,
        "energia.cpu_refrigeracion_bateria": 0,
        "energia.usb_suspension_bateria": 1,
        "energia.pcie_aspm_bateria": 2,
        "energia.disco_apagado_bateria": 300,
        "energia.pantalla_apagado_bateria": 120,
        "energia.brillo_bateria": 40,
        "energia.ahorro_windows_umbral": 50,
        "visual.transparencia": 0,
    },
)

RENDIMIENTO_BATERIA = Profile(
    id="rendimiento_bateria",
    name="Rendimiento sin cargador",
    description=(
        "Evita que la CPU se capee con batería: sin límite de potencia, boost activo, refrigeración activa, "
        "pero con ahorro moderado en pantalla, disco, USB y PCIe para mantener un consumo razonable."
    ),
    steps={
        "energia.cpu_max_bateria": 100,
        "energia.cpu_min_bateria": 10,
        "energia.cpu_boost_bateria": 1,
        "energia.cpu_refrigeracion_bateria": 1,
        "energia.usb_suspension_bateria": 1,
        "energia.pcie_aspm_bateria": 1,
        "energia.disco_apagado_bateria": 600,
        "energia.pantalla_apagado_bateria": 180,
        "energia.brillo_bateria": 60,
        "energia.ahorro_windows_umbral": 10,
    },
)

COLEGIO = Profile(
    id="colegio",
    name="Colegio",
    description=(
        "Equilibrado y con baja latencia: la CPU nunca baja del 20 % enchufado para responder rápido; "
        "con batería, límite al 90 % y brillo moderado. Opcionalmente cierra launchers de juegos."
    ),
    steps={
        "energia.cpu_max_enchufado": 100,
        "energia.cpu_min_enchufado": 20,
        "energia.cpu_boost_enchufado": 4,
        "energia.cpu_max_bateria": 90,
        "energia.cpu_min_bateria": 10,
        "energia.cpu_boost_bateria": 3,
        "energia.cpu_refrigeracion_bateria": 0,
        "energia.usb_suspension_bateria": 1,
        "energia.pcie_aspm_bateria": 1,
        "energia.disco_apagado_bateria": 600,
        "energia.pantalla_apagado_bateria": 300,
        "energia.brillo_bateria": 50,
        "energia.ahorro_windows_umbral": 20,
    },
    closes_processes=True,
)

JUEGOS = Profile(
    id="juegos",
    name="Juegos",
    description=(
        "Máximo rendimiento: CPU sin límites, boost agresivo, refrigeración activa, sin ahorro en USB/PCIe/disco, "
        "Modo Juego de Windows, GPU dedicada para tus juegos y cierre de procesos de fondo."
    ),
    steps={
        "energia.cpu_max_enchufado": 100,
        "energia.cpu_min_enchufado": 50,
        "energia.cpu_boost_enchufado": 2,
        "energia.cpu_refrigeracion_enchufado": 1,
        "energia.usb_suspension_enchufado": 0,
        "energia.pcie_aspm_enchufado": 0,
        "energia.disco_apagado_enchufado": 0,
        "energia.pantalla_apagado_enchufado": 1800,
        "energia.cpu_max_bateria": 100,
        "energia.cpu_min_bateria": 20,
        "energia.cpu_boost_bateria": 2,
        "energia.cpu_refrigeracion_bateria": 1,
        "energia.usb_suspension_bateria": 0,
        "energia.pcie_aspm_bateria": 1,
        "energia.ahorro_windows_umbral": 5,
        "juegos.modo_juego": 1,
    },
    include_gpu_apps=True,
    closes_processes=True,
)

PROFILES: dict[str, Profile] = {p.id: p for p in (AHORRO, RENDIMIENTO_BATERIA, COLEGIO, JUEGOS)}
