"""Ajustes del plan de energía. Cada ajuste existe en dos versiones: con batería (DC) y enchufado (AC)."""

from __future__ import annotations

from optiwin.tweaks.base import Risk, Tweak
from optiwin.tweaks.powercfg_tweak import PowerCfgSettingTweak

SUB_PROCESSOR = "SUB_PROCESSOR"
BOOST_MODE = "be337238-0d82-4146-a960-4f3749d470c7"  # oculto en la interfaz, pero editable
COOLING_POLICY = "94d3a615-a899-4ac5-ae2b-e4d8f634367f"
SUB_USB = "2a737441-1930-4402-8d77-b2bebba308a3"
USB_SELECTIVE_SUSPEND = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"
SUB_ENERGYSAVER = "de830923-a562-41af-a086-e3a2c6bad2da"
BATTERY_SAVER_THRESHOLD = "e69653ca-cf7f-4f05-aa73-cb833fa90ad4"

_SOURCE_LABEL = {"dc": ("bateria", "con batería"), "ac": ("enchufado", "enchufado")}

BOOST_LABELS = {
    0: "Deshabilitado",
    1: "Habilitado",
    2: "Agresivo",
    3: "Eficiente habilitado",
    4: "Eficiente agresivo",
    5: "Agresivo en garantizado",
    6: "Eficiente agresivo en garantizado",
}


def _pair(slug: str, name: str, description: str, benefit: str, risk: Risk, *, defaults: tuple[int, int], **kw) -> list[Tweak]:
    """Crea la versión DC y AC de un ajuste. defaults = (valor recomendado DC, valor recomendado AC)."""
    out: list[Tweak] = []
    for source, default in zip(("dc", "ac"), defaults):
        suffix, label = _SOURCE_LABEL[source]
        out.append(
            PowerCfgSettingTweak(
                id=f"energia.{slug}_{suffix}",
                name=f"{name} ({label})",
                category="energia",
                description=description,
                risk=risk,
                benefit=benefit,
                source=source,
                default_value=default,
                **kw,
            )
        )
    return out


def tweaks() -> list[Tweak]:
    t: list[Tweak] = []

    t += _pair(
        "cpu_max",
        "Estado máximo del procesador",
        "Límite de potencia de la CPU en %. Muchos planes lo dejan por debajo de 100 con batería "
        "y por eso el portátil va lento sin cargador. 100 = sin límite (más rendimiento, más "
        "consumo); 70-80 = mucha más autonomía.",
        "Con 100: rendimiento sin cargador decente. Con 70-80: autonomía notablemente mayor.",
        Risk.LOW,
        defaults=(100, 100),
        subgroup=SUB_PROCESSOR, setting="PROCTHROTTLEMAX", unit="%", min_value=5, max_value=100,
    )
    t += _pair(
        "cpu_min",
        "Estado mínimo del procesador",
        "Frecuencia mínima de la CPU en %. Más alto = el sistema responde antes (menos latencia) "
        "pero gasta más en reposo. 5 = ahorro máximo.",
        "Bajo: más autonomía en reposo. Alto (20-50): menor latencia al abrir apps o jugar.",
        Risk.LOW,
        defaults=(5, 5),
        subgroup=SUB_PROCESSOR, setting="PROCTHROTTLEMIN", unit="%", min_value=0, max_value=100,
    )
    t += _pair(
        "cpu_boost",
        "Modo de boost del procesador",
        "Controla si la CPU puede superar su frecuencia base (turbo/boost). 0 = desactivado, "
        "1 = habilitado, 2 = agresivo, 3 = eficiente habilitado, 4 = eficiente agresivo. "
        "Los modos 'eficiente' solo suben si compensa el consumo.",
        "Desactivar el boost con batería es el mayor ahorro posible de la CPU; activarlo da el máximo rendimiento.",
        Risk.LOW,
        defaults=(1, 2),
        subgroup=SUB_PROCESSOR, setting=BOOST_MODE, min_value=0, max_value=6, labels=BOOST_LABELS,
    )
    t += _pair(
        "cpu_refrigeracion",
        "Política de refrigeración",
        "0 = pasiva (reduce la CPU antes de subir el ventilador, más silencio y ahorro), "
        "1 = activa (sube el ventilador antes de reducir la CPU, más rendimiento sostenido).",
        "Activa evita que la CPU se recorte por temperatura; pasiva ahorra el consumo del ventilador.",
        Risk.LOW,
        defaults=(0, 1),
        subgroup=SUB_PROCESSOR, setting=COOLING_POLICY, min_value=0, max_value=1,
        labels={0: "Pasiva", 1: "Activa"},
    )
    t += _pair(
        "usb_suspension",
        "Suspensión selectiva de USB",
        "Permite que Windows apague puertos USB inactivos. 1 = habilitada (ahorra batería), "
        "0 = deshabilitada (evita desconexiones o retardos en ratones, mandos y auriculares).",
        "Habilitada: ahorro pequeño. Deshabilitada: evita micro-cortes en periféricos al jugar.",
        Risk.LOW,
        defaults=(1, 0),
        subgroup=SUB_USB, setting=USB_SELECTIVE_SUSPEND, min_value=0, max_value=1,
        labels={0: "Deshabilitada", 1: "Habilitada"},
    )
    t += _pair(
        "pcie_aspm",
        "Ahorro de enlace PCIe (ASPM)",
        "Permite que los dispositivos PCIe (SSD NVMe, GPU, Wi-Fi) entren en estados de bajo "
        "consumo cuando no se usan. 0 = desactivado, 1 = ahorro moderado, 2 = ahorro máximo.",
        "Ahorro de batería en reposo; en algunos SSD/drivers antiguos el máximo puede causar micro-pausas.",
        Risk.MEDIUM,
        defaults=(2, 0),
        subgroup="SUB_PCIEXPRESS", setting="ASPM", min_value=0, max_value=2,
        labels={0: "Desactivado", 1: "Moderado", 2: "Máximo"},
    )
    t += _pair(
        "disco_apagado",
        "Apagar el disco tras inactividad",
        "Segundos de inactividad antes de apagar el disco duro (0 = nunca). Con SSD/NVMe el "
        "efecto es casi nulo; con discos mecánicos ahorra batería pero retrasa el siguiente acceso.",
        "Pequeño ahorro, solo relevante con discos mecánicos.",
        Risk.LOW,
        defaults=(600, 0),
        subgroup="SUB_DISK", setting="DISKIDLE", unit=" s", min_value=0, max_value=86400,
    )
    t += _pair(
        "pantalla_apagado",
        "Apagar la pantalla tras inactividad",
        "Segundos sin tocar el equipo antes de apagar la pantalla (0 = nunca).",
        "La pantalla es el mayor consumidor de un portátil: reducirlo da autonomía real.",
        Risk.LOW,
        defaults=(180, 900),
        subgroup="SUB_VIDEO", setting="VIDEOIDLE", unit=" s", min_value=0, max_value=86400,
    )
    t += _pair(
        "brillo",
        "Brillo de pantalla",
        "Brillo en % del plan de energía. Solo afecta a pantallas internas (portátiles).",
        "Bajar el brillo del 100 % al 50 % puede dar entre un 10 y un 20 % más de autonomía.",
        Risk.LOW,
        defaults=(50, 100),
        subgroup="SUB_VIDEO", setting="VIDEONORMALLEVEL", unit="%", min_value=0, max_value=100,
    )

    t.append(
        PowerCfgSettingTweak(
            id="energia.ahorro_windows_umbral",
            name="Ahorro de batería de Windows: umbral",
            category="energia",
            description=(
                "Nivel de carga (%) por debajo del cual Windows activa solo el Ahorro de batería. "
                "Ese modo limita el rendimiento y las apps en segundo plano. 0 = nunca."
            ),
            risk=Risk.LOW,
            benefit="Un umbral bajo evita que el ahorro de Windows te ralentice antes de tiempo.",
            subgroup=SUB_ENERGYSAVER,
            setting=BATTERY_SAVER_THRESHOLD,
            source="dc",
            default_value=20,
            unit="%",
            min_value=0,
            max_value=100,
        )
    )
    return t
