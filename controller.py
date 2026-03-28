"""Controller layer — bridges View ↔ Service, handles threading."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import GLib

from model import (
    APP_TYPE_LABELS,
    BUILD_COMMANDS,
    BUILD_TYPES,
    AppType,
    DetectionResult,
    ExtractedArchive,
    Registry,
    derive_app_name,
    is_supported_archive,
)
from service import (
    DetectService,
    ExtractService,
    InstallService,
    UninstallService,
)

if TYPE_CHECKING:
    from view import MainWindow


class InstallController:
    """Manages the install workflow: load → extract → detect → install."""

    def __init__(self, view: MainWindow):
        self._view = view
        self._extracted: ExtractedArchive | None = None
        self._detection: DetectionResult | None = None
        self._archive_path: str = ""
        self._app_name: str = ""

    @property
    def app_name(self) -> str:
        return self._app_name

    @app_name.setter
    def app_name(self, value: str):
        self._app_name = value

    @property
    def extracted(self) -> ExtractedArchive | None:
        return self._extracted

    @property
    def detection(self) -> DetectionResult | None:
        return self._detection

    def validate_archive(self, path: str) -> bool:
        return is_supported_archive(path)

    def load_archive(self, path: str):
        self._archive_path = path
        self._app_name = derive_app_name(path)
        self._view.show_detail_page(Path(path).name, self._app_name)
        self._extract_async()

    def _extract_async(self):
        def worker():
            try:
                extracted = ExtractService.extract(
                    self._archive_path,
                    progress_cb=lambda msg, frac: GLib.idle_add(
                        self._view.update_extract_progress, frac,
                    ),
                )
                detection = DetectService.detect(extracted.root_dir)
                GLib.idle_add(self._on_extraction_done, extracted, detection)
            except Exception as e:
                GLib.idle_add(self._view.show_toast, f"Extraction failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_extraction_done(self, extracted: ExtractedArchive, detection: DetectionResult):
        self._extracted = extracted
        self._detection = detection

        is_build = detection.app_type in BUILD_TYPES
        executables = DetectService.find_executables(extracted.root_dir)

        self._view.populate_details(
            type_label=APP_TYPE_LABELS.get(detection.app_type, "Unknown"),
            file_count=extracted.file_count,
            dir_count=extracted.dir_count,
            is_build_type=is_build,
            build_command=BUILD_COMMANDS.get(detection.app_type, ""),
            executables=executables,
            root_dir=extracted.root_dir,
        )

    def copy_build_command(self):
        if self._detection and self._extracted:
            cmd = BUILD_COMMANDS.get(self._detection.app_type, "")
            return f"cd {self._extracted.root_dir} && {cmd}" if cmd else ""
        return ""

    def install(self, app_name: str, selected_bins: list[Path],
                create_desktop: bool, full_install: bool):
        self._app_name = app_name

        if Registry.exists(app_name):
            self._view.confirm_reinstall(app_name)
            return

        self._do_install(app_name, selected_bins, create_desktop, full_install)

    def force_reinstall(self, app_name: str, selected_bins: list[Path],
                        create_desktop: bool, full_install: bool):
        try:
            UninstallService.uninstall(app_name)
        except Exception:
            pass
        self._do_install(app_name, selected_bins, create_desktop, full_install)

    def _do_install(self, app_name: str, selected_bins: list[Path],
                    create_desktop: bool, full_install: bool):
        self._view.set_installing(True)
        extracted = self._extracted
        detection = self._detection
        archive_path = self._archive_path

        def worker():
            try:
                installed_files: list[str] = []

                if detection.app_type == AppType.APPIMAGE:
                    GLib.idle_add(self._view.update_install_status, "Installing AppImage...", 0.3)
                    installed_files.extend(
                        InstallService.install_appimage(Path(detection.path), app_name)
                    )

                elif full_install:
                    GLib.idle_add(self._view.update_install_status, "Installing to /opt...", 0.3)
                    installed_files.extend(
                        InstallService.install_directory(extracted.root_dir, app_name)
                    )

                elif selected_bins:
                    installed_files.extend(
                        InstallService.install_binaries(
                            selected_bins,
                            progress_cb=lambda msg, frac: GLib.idle_add(
                                self._view.update_install_status, msg, 0.2 + frac * 0.5,
                            ),
                        )
                    )
                else:
                    GLib.idle_add(self._view.show_toast, "No executables selected")
                    GLib.idle_add(self._view.set_installing, False)
                    return

                # Desktop entry
                if create_desktop and installed_files:
                    GLib.idle_add(self._view.update_install_status, "Creating desktop entry...", 0.8)
                    exec_path = next(
                        (f for f in installed_files if not f.startswith(("dir:", "src:"))),
                        None,
                    )
                    icon = DetectService.find_icon(extracted.root_dir, app_name)
                    icon_str = str(icon) if icon else None

                    existing = DetectService.find_desktop_file(extracted.root_dir)
                    if existing:
                        installed_files.append(
                            InstallService.install_existing_desktop(
                                existing, app_name,
                                exec_path=exec_path,
                                icon_path=icon_str,
                            )
                        )
                    elif exec_path:
                        installed_files.append(
                            InstallService.create_desktop_entry(
                                app_name, exec_path, icon_str,
                            )
                        )

                # Registry
                GLib.idle_add(self._view.update_install_status, "Saving registry...", 0.95)
                Registry.save(app_name, Path(archive_path).name, installed_files)

                GLib.idle_add(self._on_install_complete, app_name)

            except Exception as e:
                GLib.idle_add(self._on_install_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_install_complete(self, app_name: str):
        if self._extracted:
            ExtractService.cleanup(self._extracted.tmp_dir)
            self._extracted = None
        self._view.on_install_complete(app_name)

    def _on_install_error(self, error: str):
        self._view.set_installing(False)
        self._view.show_toast(f"Install failed: {error}")


class InstalledController:
    """Manages the installed apps list and uninstall workflow."""

    def __init__(self, view: MainWindow):
        self._view = view

    def load_entries(self):
        return Registry.load_all()

    def uninstall(self, app_name: str):
        def worker():
            try:
                UninstallService.uninstall(app_name)
                GLib.idle_add(self._view.on_uninstall_complete, app_name)
            except Exception as e:
                GLib.idle_add(self._view.show_toast, f"Uninstall failed: {e}")

        threading.Thread(target=worker, daemon=True).start()
