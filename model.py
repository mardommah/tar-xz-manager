"""Model layer — data classes, enums, constants, and registry persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Callable


# ── Constants ──────────────────────────────────────────────────────────────────

INSTALL_DIR = Path("/usr/local/bin")
DESKTOP_DIR = Path.home() / ".local/share/applications"
ICON_DIR = Path.home() / ".local/share/icons"
REGISTRY_DIR = Path.home() / ".local/share/tax-installer"

SUPPORTED_EXTENSIONS = (
    ".tar.xz", ".txz", ".tar.gz", ".tgz",
    ".tar.bz2", ".tbz2", ".tar.zst", ".tzst",
)

ICON_GLOBS = [
    "*.png", "*.svg", "icons/*.png", "icons/*.svg",
    "share/icons/**/*.png", "data/*.png", "data/*.svg",
]


# ── Enums ──────────────────────────────────────────────────────────────────────

class AppType(Enum):
    APPIMAGE = auto()
    BINARY = auto()
    EXECUTABLE = auto()
    MAKE = auto()
    CMAKE = auto()
    CONFIGURE = auto()
    MESON = auto()
    UNKNOWN = auto()


BUILD_TYPES = {AppType.MAKE, AppType.CMAKE, AppType.CONFIGURE, AppType.MESON}

APP_TYPE_LABELS = {
    AppType.APPIMAGE: "AppImage",
    AppType.BINARY: "Pre-built binary",
    AppType.EXECUTABLE: "Executable",
    AppType.MAKE: "Source (Makefile)",
    AppType.CMAKE: "Source (CMake)",
    AppType.CONFIGURE: "Source (./configure)",
    AppType.MESON: "Source (Meson)",
    AppType.UNKNOWN: "Unknown",
}

BUILD_COMMANDS = {
    AppType.MAKE: "make && sudo make install",
    AppType.CMAKE: "mkdir build && cd build && cmake .. && make && sudo make install",
    AppType.CONFIGURE: "./configure && make && sudo make install",
    AppType.MESON: "meson setup build && ninja -C build && sudo ninja -C build install",
}


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    app_type: AppType
    path: str = ""


@dataclass
class ExtractedArchive:
    root_dir: Path
    tmp_dir: Path
    file_count: int = 0
    dir_count: int = 0


@dataclass
class RegistryEntry:
    name: str
    archive: str
    date: str
    files: list[str] = field(default_factory=list)


# Callback type: (message, fraction 0..1)
ProgressCallback = Callable[[str, float], None]


# ── Helper ─────────────────────────────────────────────────────────────────────

def is_supported_archive(path: str) -> bool:
    return any(path.endswith(ext) for ext in SUPPORTED_EXTENSIONS)


def derive_app_name(archive_path: str) -> str:
    name = Path(archive_path).name
    for ext in SUPPORTED_EXTENSIONS:
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    name = re.sub(r"[-_]v?\d+\.\d+.*", "", name)
    name = re.sub(r"[-_](linux|x86_64|x64|amd64|aarch64|arm64).*", "", name, flags=re.IGNORECASE)
    return name.lower()


# ── Registry persistence ──────────────────────────────────────────────────────

class Registry:
    """Reads and writes the .reg files in ~/.local/share/tax-installer/."""

    @staticmethod
    def save(app_name: str, archive_name: str, files: list[str]) -> None:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        reg_file = REGISTRY_DIR / f"{app_name}.reg"
        lines = [
            f"name={app_name}",
            f"archive={archive_name}",
            f"date={datetime.now().isoformat()}",
            "files=",
        ]
        for f in files:
            lines.append(f"  {f}")
        reg_file.write_text("\n".join(lines) + "\n")

    @staticmethod
    def load_all() -> list[RegistryEntry]:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        return [
            entry
            for reg in sorted(REGISTRY_DIR.glob("*.reg"))
            if (entry := Registry._parse(reg)) is not None
        ]

    @staticmethod
    def get(app_name: str) -> RegistryEntry | None:
        reg_file = REGISTRY_DIR / f"{app_name}.reg"
        return Registry._parse(reg_file) if reg_file.exists() else None

    @staticmethod
    def exists(app_name: str) -> bool:
        return (REGISTRY_DIR / f"{app_name}.reg").exists()

    @staticmethod
    def remove(app_name: str) -> None:
        reg_file = REGISTRY_DIR / f"{app_name}.reg"
        reg_file.unlink(missing_ok=True)

    @staticmethod
    def _parse(reg_file: Path) -> RegistryEntry | None:
        entry = RegistryEntry(name="", archive="", date="")
        in_files = False
        for line in reg_file.read_text().splitlines():
            if line.strip() == "files=":
                in_files = True
                continue
            if in_files:
                f = line.strip()
                if f:
                    entry.files.append(f)
            elif "=" in line:
                key, val = line.split("=", 1)
                if key == "name":
                    entry.name = val
                elif key == "archive":
                    entry.archive = val
                elif key == "date":
                    entry.date = val
        return entry if entry.name else None
