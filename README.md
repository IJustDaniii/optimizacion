# OptiWin

Optimizador **reversible** de energía y rendimiento para Windows 10/11 (portátil y sobremesa), en español.
Pensado para sacar más autonomía y rendimiento sin cargador, mejorar los juegos y limpiar el sistema, sin
tweaks dudosos: cada ajuste explica qué hace, su riesgo y su beneficio, guarda su valor original y se puede deshacer.

## Instalar

Descarga `OptiWin-Setup-X.Y.Z.exe` desde [Releases](https://github.com/IJustDaniii/optimizacion/releases/latest) y ejecútalo.
Se instala solo para tu usuario (sin UAC). Windows SmartScreen puede avisar porque el instalador no está firmado.

**Actualizaciones:** en *Configuración* puedes pulsar «Buscar actualizaciones ahora» o activar la búsqueda al abrir.
Hace una sola petición a la API pública de GitHub (sin enviar datos de tu equipo) y verifica el SHA-256 del instalador
antes de ejecutarlo. Al desinstalar se restauran los ajustes que OptiWin había cambiado.

## Qué hace

- **Perfiles** de un clic: Juegos, Colegio, Ahorro de batería y Rendimiento sin cargador, con **cambio automático** al
  enchufar/desenchufar el cargador (desde la bandeja del sistema).
- **Ajustes** de plan de energía (CPU, boost, USB, PCIe, disco, pantalla, brillo…), Modo Juego, GPU dedicada por juego.
- **Limpieza** con vista previa por categoría y confirmación escrita: temporales, Windows Update, papelera, miniaturas,
  informes de error y cachés de navegadores. Nunca toca documentos ni carpetas personales.
- **Seguridad:** punto de restauración antes del primer cambio, simulación, "Deshacer" por ajuste y "Restaurar todo",
  registro de todo lo aplicado, sin telemetría.

## Desarrollo

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev,gui]"
.\.venv\Scripts\python -m pytest                 # tests (la GUI se prueba sin pantalla)
.\.venv\Scripts\python -m optiwin gui            # interfaz gráfica
.\.venv\Scripts\python -m optiwin --help         # línea de comandos (info, tweaks, profile, auto, clean, log...)
```

### Línea de comandos (resumen)

```powershell
optiwin info                                   # especificaciones y estado de energía
optiwin tweaks | explain ID | apply ID [--dry-run] | revert ID | revert-all
optiwin profile list | apply ID [--dry-run] [--cerrar] | off [--reabrir] | status
optiwin auto set --activar --enchufado colegio --bateria rendimiento_bateria ; optiwin auto run
optiwin clean scan [--detalle] | run [--categorias ...]        # run pide escribir BORRAR
optiwin close add juegos Discord.exe ; optiwin gpu add "C:\ruta\juego.exe"
optiwin log -n 30
```

Los datos (estado con los valores originales, configuración y logs) están en `%LOCALAPPDATA%\OptiWin`.

### Cómo añadir un ajuste

En `src/optiwin/tweaks/` añade una instancia de `RegistryValueTweak` o `PowerCfgSettingTweak` (o una subclase de `Tweak`)
a la función `tweaks()` del módulo de su categoría. Aparece sola en CLI y GUI, con simulación, deshacer y log.

### Construir el instalador

```powershell
.\.venv\Scripts\python -m pip install -e ".[build]"
.\.venv\Scripts\python packaging\build.py       # PyInstaller + Inno Setup 6 -> dist\OptiWin-Setup-X.Y.Z.exe (+ .sha256)
```

Para publicar una versión: sube `__version__` en `src/optiwin/__init__.py`, construye, y crea la release `vX.Y.Z` adjuntando
**el instalador y su `.sha256`** (el actualizador exige ambos nombres exactos). En `packaging/ci/` hay dos flujos de GitHub
Actions (tests y release automática); para activarlos cópialos a `.github/workflows/` con un token que tenga el permiso `workflow`.

## Estructura

```
src/optiwin/core/      detección, energía, motor (engine), estado, logs, punto de restauración, actualizador
src/optiwin/tweaks/    ajustes por categoría + tipos genéricos (registro, powercfg)
src/optiwin/profiles/  perfiles y gestor de activación
src/optiwin/cleanup/   categorías de limpieza, barreras de seguridad y orquestador
src/optiwin/gui/       interfaz PySide6
packaging/             PyInstaller, Inno Setup, script de build, CI
tests/
```
