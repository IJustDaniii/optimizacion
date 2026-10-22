"""Interfaz de línea de comandos (Fase 1). La GUI usará exactamente las mismas funciones."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

from optiwin import __version__
from optiwin.cleanup.catalog import build_categories
from optiwin.cleanup.cleaner import Cleaner, Plan, format_size
from optiwin.core import process_closer
from optiwin.core.autoswitch import AutoSwitcher
from optiwin.core.config import Config
from optiwin.core.detection import SystemInfo, detect_system
from optiwin.core.elevation import relaunch_elevated
from optiwin.core.engine import Engine, Result
from optiwin.core.logger import read_log_tail, setup_logging
from optiwin.core.paths import app_home
from optiwin.core.power_status import KNOWN_SCHEMES, read_power_status
from optiwin.core.restore_point import create_restore_point
from optiwin.core.state import StateStore
from optiwin.core.winutil import is_admin
from optiwin.profiles.definitions import PROFILES
from optiwin.profiles.manager import ActivationReport, ProfileManager
from optiwin.tweaks import build_catalog


def _fmt_time(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    h, m = divmod(seconds // 60, 60)
    return f"{h} h {m:02d} min"


def _print_info(s: SystemInfo) -> None:
    tipo = "PORTÁTIL" if s.is_laptop else "SOBREMESA"
    print(f"Equipo      : {s.manufacturer} {s.model}")
    print(f"Tipo        : {tipo}  ({s.laptop_reason})")
    print(f"Windows     : {s.windows}")
    if s.cpu:
        print(f"CPU         : {s.cpu.name}  [{s.cpu.cores} núcleos / {s.cpu.threads} hilos, {s.cpu.max_mhz} MHz máx]")
    for g in s.gpus:
        vram = f", {g.vram_gb} GB" if g.vram_gb else ""
        print(f"GPU         : {g.name}  [{g.kind}{vram}, driver {g.driver}]")
    speed = f" a {s.ram_speed_mhz} MHz" if s.ram_speed_mhz else ""
    print(f"RAM         : {s.ram_gb} GB{speed}")
    for d in s.disks:
        print(f"Disco       : {d.name}  [{d.kind}, {d.size_gb} GB]")
    if s.battery:
        b = s.battery
        health = f"{b.health_percent}%" if b.health_percent is not None else "no disponible"
        print(f"Batería     : salud {health}  (diseño {b.design_mwh} mWh, actual {b.full_mwh} mWh, ciclos {b.cycles})")
    _print_power(s)
    print(f"Administrador: {'sí' if is_admin() else 'no'}")


def _print_power(s: SystemInfo) -> None:
    p = s.power
    if p:
        extra = ""
        if p.has_battery:
            extra = f" · batería {p.battery_percent}%"
            extra += " (cargando)" if p.charging else ""
            if p.plugged_in is False:
                extra += f" · quedan {_fmt_time(p.seconds_left)}"
            if p.battery_saver_on:
                extra += " · ahorro de batería ACTIVO"
        print(f"Alimentación: {p.source}{extra}")
    if s.power_scheme:
        guid, name = s.power_scheme
        std = KNOWN_SCHEMES.get(guid)
        tag = f" [estándar: {std}]" if std else " [personalizado]"
        print(f"Plan energía: {name}{tag}  {guid}")


def cmd_info(args: argparse.Namespace) -> int:
    s = detect_system()
    if args.json:
        print(json.dumps(s.to_dict(), indent=2, ensure_ascii=False, default=str))
    else:
        _print_info(s)
    return 0


def cmd_power(args: argparse.Namespace) -> int:
    _print_power(detect_system())
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Muestra en tiempo real los cambios entre corriente y batería (Ctrl+C para salir)."""
    print("Vigilando alimentación... (Ctrl+C para salir)")
    last = None
    try:
        while True:
            p = read_power_status()
            key = (p.plugged_in, p.battery_saver_on)
            if key != last:
                stamp = time.strftime("%H:%M:%S")
                pct = f" · {p.battery_percent}%" if p.has_battery else ""
                print(f"[{stamp}] Fuente: {p.source}{pct}")
                last = key
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nFin.")
    return 0


# --- Fase 2: ajustes reversibles ------------------------------------------------

_LABELS = {"applied": "[APLICADO]", "dry_run": "[SIMULACIÓN]", "reverted": "[DESHECHO]", "skipped": "[SIN CAMBIOS]", "error": "[ERROR]"}


def _context() -> tuple[Engine, Config, ProfileManager]:
    home = app_home()
    config = Config(home / "config.json")
    engine = Engine(build_catalog(config.gpu_apps), StateStore(home / "state.json"), setup_logging(home))
    return engine, config, ProfileManager(engine, config)


def _engine() -> Engine:
    return _context()[0]


def _print_result(r: Result) -> None:
    ident = f" {r.tweak_id}" if r.tweak_id != "-" else ""
    print(f"{_LABELS[r.status]}{ident} {r.message}")


def _parse_value(text: str | None):
    if text is None:
        return None
    return int(text) if text.lstrip("-").isdigit() else text


def _elevate_if_requested(args: argparse.Namespace, argv: list[str], reason: str) -> bool:
    """Si se pidió --elevar y no somos admin, relanza con UAC. True = ya está gestionado."""
    if not getattr(args, "elevar", False) or is_admin():
        return False
    print(f"Se va a pedir permiso de administrador. Motivo: {reason}")
    if not relaunch_elevated([a for a in argv if a != "--elevar"]):
        print("[ERROR] Permiso de administrador denegado; no se ha cambiado nada.")
        return True
    print("Continúa en la ventana de administrador que se ha abierto.")
    return True


def cmd_tweaks(args: argparse.Namespace) -> int:
    rows = _engine().status()
    if args.category:
        rows = [r for r in rows if r.tweak.category == args.category]
    print(f"{'ID':<36} {'ESTADO':<10} {'ACTUAL':<52} RIESGO  ADMIN")
    for r in rows:
        t = r.tweak
        estado = "aplicado" if r.applied else ("no disp." if not r.available else "—")
        print(f"{t.id:<36} {estado:<10} {r.current:<52} {t.risk.value:<7} {'sí' if t.requires_admin else 'no'}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    t = _engine().catalog.get(args.id)
    if t is None:
        print(f"[ERROR] No existe el ajuste '{args.id}'. Usa 'optiwin tweaks' para ver la lista.")
        return 1
    print(f"{t.name}  ({t.id})")
    print(f"  Qué hace   : {t.description}")
    print(f"  Beneficio  : {t.benefit}")
    print(f"  Riesgo     : {t.risk.value}")
    print(f"  Valor por defecto al aplicar: {t.default_value}")
    print(f"  Administrador: {'sí — ' + t.admin_reason if t.requires_admin else 'no'}")
    print(f"  Reinicio   : {'sí' if t.reboot_required else 'no'}")
    return 0


def cmd_apply(args: argparse.Namespace, argv: list[str]) -> int:
    if not args.dry_run and _elevate_if_requested(
        args, argv, "crear el punto de restauración previo y/o escribir ajustes de sistema"
    ):
        return 0
    engine = _engine()
    r = engine.apply(
        args.id, _parse_value(args.value), dry_run=args.dry_run, skip_restore_point=args.sin_punto_restauracion
    )
    _print_result(r)
    if args.dry_run and r.status == "dry_run" and engine.store.restore_point is None:
        print("  · Antes de aplicar se creará un punto de restauración (requiere administrador).")
    return 0 if r.ok else 1


def cmd_revert(args: argparse.Namespace, argv: list[str]) -> int:
    if _elevate_if_requested(args, argv, "deshacer ajustes de sistema"):
        return 0
    r = _engine().revert(args.id)
    _print_result(r)
    return 0 if r.ok else 1


def cmd_revert_all(args: argparse.Namespace, argv: list[str]) -> int:
    if _elevate_if_requested(args, argv, "deshacer ajustes de sistema"):
        return 0
    engine, _, manager = _context()
    results = engine.revert_all()
    if manager.current() and not engine.store.applied:
        engine.store.set_active_profile(None)
    if not results:
        print("No hay ajustes aplicados por OptiWin.")
    for r in results:
        _print_result(r)
    return 0 if all(r.ok for r in results) else 1


def cmd_restore_point(args: argparse.Namespace, argv: list[str]) -> int:
    if _elevate_if_requested(args, argv, "Windows solo permite crear puntos de restauración como administrador"):
        return 0
    if not is_admin():
        print("[ERROR] Hace falta administrador. Repite con --elevar.")
        return 1
    home = app_home()
    log, store = setup_logging(home), StateStore(home / "state.json")
    res = create_restore_point()
    log.info("PUNTO DE RESTAURACION (manual) | ok=%s creado=%s | %s", res.ok, res.created, res.message)
    if res.ok:
        store.set_restore_point({"created": res.created, "detail": res.message})
    print(("[OK] " if res.ok else "[ERROR] ") + res.message)
    return 0 if res.ok else 1


# --- Fase 3: perfiles, cambio automático, lista de procesos y GPU --------------------

def _print_report(report: ActivationReport, verbose: bool) -> None:
    counts: dict[str, int] = {}
    for r in report.results:
        counts[r.status] = counts.get(r.status, 0) + 1
        if verbose or r.status in ("error", "dry_run"):
            _print_result(r)
    for note in report.notes:
        print(f"  · {note}")
    summary = ", ".join(f"{n} {_LABELS[s].strip('[]').lower()}" for s, n in counts.items())
    print(f"Perfil '{report.profile_id}': {summary or 'sin cambios'}.")


def cmd_profile_list(args: argparse.Namespace) -> int:
    _, _, manager = _context()
    current = manager.current()
    for p in PROFILES.values():
        mark = " (ACTIVO)" if current and current["id"] == p.id else ""
        print(f"{p.id:<20} {p.name}{mark}\n{'':<20} {p.description}")
    return 0


def cmd_profile_apply(args: argparse.Namespace, argv: list[str]) -> int:
    if not args.dry_run and _elevate_if_requested(
        args, argv, "crear el punto de restauración previo y/o escribir ajustes de sistema"
    ):
        return 0
    _, _, manager = _context()
    report = manager.activate(
        args.id, dry_run=args.dry_run, close=args.cerrar, skip_restore_point=args.sin_punto_restauracion
    )
    _print_report(report, args.verbose)
    if report.needs_admin:
        print("Algunos pasos necesitan administrador: repite con --elevar.")
    return 0 if report.ok else 1


def cmd_profile_off(args: argparse.Namespace) -> int:
    _, _, manager = _context()
    report = manager.deactivate(dry_run=args.dry_run, reopen=args.reabrir)
    _print_report(report, args.verbose)
    return 0 if report.ok else 1


def cmd_profile_status(args: argparse.Namespace) -> int:
    engine, config, manager = _context()
    cur = manager.current()
    if not cur:
        print("Ningún perfil activo.")
    else:
        print(f"Perfil activo: {cur['id']} desde {cur['activated_at']} ({len(cur['owned'])} ajustes)")
    a = config.auto_switch
    print(f"Cambio automático: {'ACTIVADO' if a['enabled'] else 'desactivado'} · enchufado → {a['on_ac']} · batería → {a['on_battery']}")
    return 0


def cmd_auto_set(args: argparse.Namespace) -> int:
    _, config, _ = _context()
    for pid in (args.enchufado, args.bateria):
        if pid and pid not in PROFILES:
            print(f"[ERROR] El perfil '{pid}' no existe. Disponibles: {', '.join(PROFILES)}")
            return 1
    if args.enchufado:
        config.auto_switch["on_ac"] = args.enchufado
    if args.bateria:
        config.auto_switch["on_battery"] = args.bateria
    if args.activar:
        config.auto_switch["enabled"] = True
    if args.desactivar:
        config.auto_switch["enabled"] = False
    config.save()
    return cmd_profile_status(args)


def cmd_auto_run(args: argparse.Namespace) -> int:
    engine, config, manager = _context()
    a = config.auto_switch
    if not a["enabled"]:
        print("El cambio automático está desactivado. Actívalo con: optiwin auto set --activar")
        return 1
    if engine.store.restore_point is None:
        print("[ERROR] Aún no hay punto de restauración. Crea uno primero: optiwin restore-point --elevar")
        return 1

    def on_change(source: str) -> None:
        profile = a["on_ac"] if source == "ac" else a["on_battery"]
        label = "enchufado" if source == "ac" else "con batería"
        print(f"[{time.strftime('%H:%M:%S')}] {label} → perfil '{profile}'")
        engine.log.info("AUTO | fuente=%s perfil=%s", source, profile)
        # El cambio automático NUNCA cierra procesos.
        _print_report(manager.activate(profile, close=False), verbose=False)

    print("Cambio automático en marcha (Ctrl+C para salir)...")
    switcher = AutoSwitcher(on_change, interval=args.interval)
    stop = threading.Event()
    try:
        switcher.run(stop)
    except KeyboardInterrupt:
        stop.set()
        print("\nFin.")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    _, config, _ = _context()
    if args.profile not in PROFILES or not PROFILES[args.profile].closes_processes:
        valid = [p.id for p in PROFILES.values() if p.closes_processes]
        print(f"[ERROR] Ese perfil no cierra procesos. Perfiles con lista: {', '.join(valid)}")
        return 1
    names = config.close_list(args.profile)
    if args.action in ("add", "remove"):
        if not args.name:
            print("[ERROR] Indica el nombre del proceso, p. ej. Discord.exe")
            return 1
        try:
            name = process_closer.normalize_name(args.name)
        except process_closer.InvalidProcessName as exc:
            print(f"[ERROR] {exc}")
            return 1
        lower = [n.lower() for n in names]
        if args.action == "add" and name.lower() not in lower:
            names.append(name)
        if args.action == "remove" and name.lower() in lower:
            names.pop(lower.index(name.lower()))
        config.save()
    print(f"Lista de cierre del perfil '{args.profile}': {', '.join(names) or '(vacía)'}")
    return 0


def cmd_gpu(args: argparse.Namespace) -> int:
    _, config, _ = _context()
    apps = config.gpu_apps
    if args.action in ("add", "remove"):
        if not args.path:
            print("[ERROR] Indica la ruta completa del .exe del juego.")
            return 1
        path = os.path.normpath(args.path)
        if args.action == "add":
            if not path.lower().endswith(".exe") or not os.path.isfile(path):
                print("[ERROR] La ruta debe ser un .exe existente.")
                return 1
            if path.lower() not in [a.lower() for a in apps]:
                apps.append(path)
        else:
            apps[:] = [a for a in apps if a.lower() != path.lower()]
        config.save()
        print("Se aplicará con el perfil 'juegos' (optiwin profile apply juegos).")
    print("Juegos con GPU dedicada:" + ("".join(f"\n  {a}" for a in apps) or " (ninguno)"))
    return 0


# --- Fase 4: limpieza con vista previa ----------------------------------------------------

def _cleaner() -> Cleaner:
    home = app_home()
    return Cleaner(build_categories(), home, setup_logging(home))


def _parse_ids(text: str | None) -> list[str] | None:
    return [t.strip() for t in text.split(",") if t.strip()] if text else None


def _print_preview(cleaner: Cleaner, plan: Plan, detail: bool) -> None:
    print(f"{'ID':<20} {'CATEGORÍA':<46} {'ARCHIVOS':>9} {'TAMAÑO':>10}  ESTADO")
    for cid, scan in plan.scans.items():
        cat = cleaner.categories[cid]
        estado = (plan.blocked[cid] + " (usa --elevar)") if cid in plan.blocked else ("riesgo medio" if cat.risk.value == "medio" else "")
        print(f"{cid:<20} {cat.name[:46]:<46} {scan.item_count:>9} {format_size(scan.total_bytes):>10}  {estado}")
        for note in scan.notes + ([f"AVISO: {plan.warnings[cid]}"] if cid in plan.warnings else []):
            print(f"{'':<20} · {note}")
        if detail:
            print(f"{'':<20}   {cat.description}")
            for name, size in scan.breakdown(6):
                print(f"{'':<20}   {format_size(size):>9}  [carpeta] {name}")
            for path, size in scan.largest(5):
                print(f"{'':<20}   {format_size(size):>9}  {path}")
    print(f"{'TOTAL':<20} {'':<46} {sum(s.item_count for s in plan.scans.values()):>9} {format_size(plan.total_bytes):>10}")


def cmd_clean_scan(args: argparse.Namespace) -> int:
    cleaner = _cleaner()
    try:
        plan = cleaner.scan(_parse_ids(args.categorias), progress=lambda n: print(f"Analizando {n}...", file=sys.stderr))
    except KeyError as exc:
        print(f"[ERROR] {exc.args[0]}")
        return 1
    _print_preview(cleaner, plan, args.detalle)
    print("\nVista previa: no se ha borrado nada. Para limpiar: optiwin clean run")
    return 0


def cmd_clean_run(args: argparse.Namespace, argv: list[str]) -> int:
    if _elevate_if_requested(args, argv, "limpiar carpetas del sistema (C:\\Windows\\Temp, Windows Update, registros)"):
        return 0
    cleaner = _cleaner()
    try:
        plan = cleaner.scan(_parse_ids(args.categorias), progress=lambda n: print(f"Analizando {n}...", file=sys.stderr))
    except KeyError as exc:
        print(f"[ERROR] {exc.args[0]}")
        return 1
    _print_preview(cleaner, plan, detail=False)

    selected = [c for c, s in plan.scans.items() if c not in plan.blocked and s.item_count > 0]
    skipped = [c for c in plan.scans if c in plan.blocked]
    if skipped:
        print(f"\nSe omitirán por falta de permisos: {', '.join(skipped)} (repite con --elevar para incluirlas).")
    if not selected:
        print("\nNo hay nada que limpiar.")
        return 0

    total = sum(plan.scans[c].total_bytes for c in selected)
    print(f"\nSe van a borrar DEFINITIVAMENTE (no van a la papelera) {format_size(total)} de: {', '.join(selected)}")
    print("Esta acción NO se puede deshacer. No se tocará ningún documento ni carpeta personal.")
    if not sys.stdin.isatty():
        print("[ERROR] Hace falta una consola interactiva para confirmar. No se ha borrado nada.")
        return 1
    try:
        answer = input("Escribe BORRAR para continuar (cualquier otra cosa cancela): ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer != "BORRAR":
        print("\nCancelado. No se ha borrado nada.")
        return 0

    reports = cleaner.clean(plan, selected, confirmed=True)
    for r in reports:
        extra = f" · {'; '.join(r.notes)}" if r.notes else ""
        print(f"[LIMPIO] {r.category_id}: {r.deleted_files} archivos, {format_size(r.freed_bytes)} liberados{extra}")
    print(f"Total liberado: {format_size(sum(r.freed_bytes for r in reports))}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from optiwin.gui.app import main as gui_main
    except ImportError:
        print("[ERROR] Falta la interfaz gráfica. Instálala con: pip install \"optiwin[gui]\"")
        return 1
    return gui_main(["--tray"] if args.tray else [])


def cmd_log(args: argparse.Namespace) -> int:
    lines = read_log_tail(app_home(), args.n)
    print("\n".join(lines) if lines else "El registro está vacío.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="optiwin", description="OptiWin — optimizador reversible para Windows")
    parser.add_argument("--version", action="version", version=f"optiwin {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def elevar(p: argparse.ArgumentParser) -> None:
        p.add_argument("--elevar", action="store_true", help="Relanza pidiendo permisos de administrador (UAC)")

    p_tw = sub.add_parser("tweaks", help="Lista los ajustes disponibles y su estado")
    p_tw.add_argument("--category", help="Filtra por categoría (energia, juegos, visual...)")
    p_tw.set_defaults(func=cmd_tweaks)

    p_ex = sub.add_parser("explain", help="Explica un ajuste: qué hace, riesgo y beneficio")
    p_ex.add_argument("id")
    p_ex.set_defaults(func=cmd_explain)

    p_ap = sub.add_parser("apply", help="Aplica un ajuste (guardando el original)")
    p_ap.add_argument("id")
    p_ap.add_argument("--value", help="Valor a aplicar (por defecto, el recomendado del ajuste)")
    p_ap.add_argument("--dry-run", action="store_true", help="Simulación: muestra qué cambiaría sin aplicar nada")
    p_ap.add_argument("--sin-punto-restauracion", action="store_true", help="Omite el punto de restauración (no recomendado)")
    elevar(p_ap)
    p_ap.set_defaults(func=cmd_apply, needs_argv=True)

    p_rv = sub.add_parser("revert", help="Deshace un ajuste")
    p_rv.add_argument("id")
    elevar(p_rv)
    p_rv.set_defaults(func=cmd_revert, needs_argv=True)

    p_ra = sub.add_parser("revert-all", help="Restaura todo lo aplicado por OptiWin")
    elevar(p_ra)
    p_ra.set_defaults(func=cmd_revert_all, needs_argv=True)

    p_rp = sub.add_parser("restore-point", help="Crea un punto de restauración de Windows ahora")
    elevar(p_rp)
    p_rp.set_defaults(func=cmd_restore_point, needs_argv=True)

    p_prof = sub.add_parser("profile", help="Perfiles de optimización de un clic")
    prof_sub = p_prof.add_subparsers(dest="pcmd", required=True)
    prof_sub.add_parser("list", help="Lista los perfiles").set_defaults(func=cmd_profile_list)
    prof_sub.add_parser("status", help="Perfil activo y cambio automático").set_defaults(func=cmd_profile_status)
    pp_ap = prof_sub.add_parser("apply", help="Activa un perfil")
    pp_ap.add_argument("id", choices=list(PROFILES))
    pp_ap.add_argument("--dry-run", action="store_true", help="Simulación")
    pp_ap.add_argument("--cerrar", action="store_true", help="Cierra los procesos de la lista del perfil")
    pp_ap.add_argument("--sin-punto-restauracion", action="store_true")
    pp_ap.add_argument("-v", "--verbose", action="store_true", help="Muestra todos los pasos")
    elevar(pp_ap)
    pp_ap.set_defaults(func=cmd_profile_apply, needs_argv=True)
    pp_off = prof_sub.add_parser("off", help="Desactiva el perfil y devuelve los originales")
    pp_off.add_argument("--dry-run", action="store_true")
    pp_off.add_argument("--reabrir", action="store_true", help="Reabre los programas que se cerraron")
    pp_off.add_argument("-v", "--verbose", action="store_true")
    pp_off.set_defaults(func=cmd_profile_off)

    p_auto = sub.add_parser("auto", help="Cambio automático de perfil al enchufar/desenchufar")
    auto_sub = p_auto.add_subparsers(dest="acmd", required=True)
    a_set = auto_sub.add_parser("set", help="Configura el cambio automático")
    a_set.add_argument("--activar", action="store_true")
    a_set.add_argument("--desactivar", action="store_true")
    a_set.add_argument("--enchufado", help="Perfil con el cargador conectado")
    a_set.add_argument("--bateria", help="Perfil con batería")
    a_set.set_defaults(func=cmd_auto_set)
    a_run = auto_sub.add_parser("run", help="Ejecuta el vigilante en esta ventana")
    a_run.add_argument("--interval", type=float, default=2.0)
    a_run.set_defaults(func=cmd_auto_run)

    p_close = sub.add_parser("close", help="Edita la lista de procesos que cierra un perfil")
    p_close.add_argument("action", choices=["list", "add", "remove"])
    p_close.add_argument("profile", help="juegos | colegio")
    p_close.add_argument("name", nargs="?", help="Nombre del proceso, p. ej. Discord.exe")
    p_close.set_defaults(func=cmd_close)

    p_gpu = sub.add_parser("gpu", help="Juegos que deben usar la GPU dedicada")
    p_gpu.add_argument("action", choices=["list", "add", "remove"])
    p_gpu.add_argument("path", nargs="?", help="Ruta completa del .exe")
    p_gpu.set_defaults(func=cmd_gpu)

    p_clean = sub.add_parser("clean", help="Limpieza con vista previa y confirmación")
    clean_sub = p_clean.add_subparsers(dest="ccmd", required=True)
    c_scan = clean_sub.add_parser("scan", help="Vista previa por categoría (no borra nada)")
    c_scan.add_argument("--categorias", help="Lista separada por comas (ver columna ID)")
    c_scan.add_argument("--detalle", action="store_true", help="Explica cada categoría y muestra los archivos más grandes")
    c_scan.set_defaults(func=cmd_clean_scan)
    c_run = clean_sub.add_parser("run", help="Analiza, muestra la vista previa y pide confirmación antes de borrar")
    c_run.add_argument("--categorias", help="Lista separada por comas (ver columna ID)")
    elevar(c_run)
    c_run.set_defaults(func=cmd_clean_run, needs_argv=True)

    p_gui = sub.add_parser("gui", help="Abre la interfaz gráfica")
    p_gui.add_argument("--tray", action="store_true", help="Arranca minimizado en la bandeja")
    p_gui.set_defaults(func=cmd_gui)

    p_log = sub.add_parser("log", help="Muestra el registro de cambios")
    p_log.add_argument("-n", type=int, default=30, help="Número de líneas")
    p_log.set_defaults(func=cmd_log)

    p_info = sub.add_parser("info", help="Detecta el equipo y muestra especificaciones")
    p_info.add_argument("--json", action="store_true", help="Salida en JSON")
    p_info.set_defaults(func=cmd_info)

    p_power = sub.add_parser("power", help="Muestra fuente de energía y plan activo")
    p_power.set_defaults(func=cmd_power)

    p_watch = sub.add_parser("watch", help="Detecta en tiempo real enchufar/desenchufar")
    p_watch.add_argument("--interval", type=float, default=1.0, help="Segundos entre comprobaciones")
    p_watch.set_defaults(func=cmd_watch)

    args = parser.parse_args(argv)
    if getattr(args, "needs_argv", False):
        return args.func(args, argv)
    return args.func(args)
