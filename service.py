"""Service layer — all business logic: extract, detect, install, uninstall."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from model import (
    DESKTOP_DIR,
    ICON_DIR,
    ICON_GLOBS,
    INSTALL_DIR,
    AppType,
    DetectionResult,
    ExtractedArchive,
    ProgressCallback,
    Registry,
)


class ExtractService:
    """Handles archive extraction."""

    @staticmethod
    def extract(archive_path: str, progress_cb: ProgressCallback | None = None) -> ExtractedArchive:
        archive_path = str(Path(archive_path).resolve())
        tmp_dir = Path(tempfile.mkdtemp(prefix="tax-installer."))
        is_zst = archive_path.endswith((".tar.zst", ".tzst"))

        if is_zst:
            if progress_cb:
                progress_cb("Extracting (zstd)...", 0.1)
            result = subprocess.run(
                ["tar", "--zstd", "-xf", archive_path, "-C", str(tmp_dir)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Extraction failed: {result.stderr}")
            if progress_cb:
                progress_cb("Done", 1.0)
        else:
            with tarfile.open(archive_path) as tf:
                members = tf.getmembers()
                total = len(members)
                for i, member in enumerate(members):
                    tf.extract(member, path=tmp_dir, filter="data")
                    if progress_cb and (i % max(1, total // 50) == 0 or i == total - 1):
                        progress_cb(member.name, (i + 1) / total)

        # Unwrap single top-level directory
        items = list(tmp_dir.iterdir())
        root_dir = items[0] if len(items) == 1 and items[0].is_dir() else tmp_dir

        file_count = sum(1 for p in root_dir.rglob("*") if p.is_file())
        dir_count = sum(1 for p in root_dir.rglob("*") if p.is_dir())

        return ExtractedArchive(
            root_dir=root_dir, tmp_dir=tmp_dir,
            file_count=file_count, dir_count=dir_count,
        )

    @staticmethod
    def cleanup(tmp_dir: Path) -> None:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


class DetectService:
    """Detects what kind of application is inside an extracted archive."""

    @staticmethod
    def detect(directory: Path) -> DetectionResult:
        # AppImage
        for f in directory.rglob("*.AppImage"):
            if f.is_file():
                return DetectionResult(AppType.APPIMAGE, str(f))

        # Pre-built binaries
        for sub in ["bin", "usr/bin", "usr/local/bin", "."]:
            bin_dir = directory / sub if sub != "." else directory
            if bin_dir.is_dir():
                executables = [f for f in bin_dir.iterdir() if f.is_file() and os.access(f, os.X_OK)]
                if executables:
                    return DetectionResult(AppType.BINARY, str(bin_dir))

        # Build systems
        if (directory / "Makefile").exists() or (directory / "makefile").exists():
            return DetectionResult(AppType.MAKE, str(directory))
        if (directory / "CMakeLists.txt").exists():
            return DetectionResult(AppType.CMAKE, str(directory))
        if (directory / "configure").exists():
            return DetectionResult(AppType.CONFIGURE, str(directory))
        if (directory / "meson.build").exists():
            return DetectionResult(AppType.MESON, str(directory))

        # Any executable
        for f in directory.rglob("*"):
            if f.is_file() and os.access(f, os.X_OK):
                return DetectionResult(AppType.EXECUTABLE, str(f))

        return DetectionResult(AppType.UNKNOWN)

    @staticmethod
    def find_executables(directory: Path) -> list[Path]:
        return sorted(f for f in directory.rglob("*") if f.is_file() and os.access(f, os.X_OK))

    @staticmethod
    def find_icon(directory: Path, app_name: str) -> Path | None:
        for pattern in ICON_GLOBS:
            for f in directory.glob(pattern):
                if f.is_file():
                    return f
        for f in directory.rglob(f"{app_name}.*"):
            if f.is_file() and f.suffix in (".png", ".svg", ".xpm"):
                return f
        return None

    @staticmethod
    def find_desktop_file(directory: Path) -> Path | None:
        for f in directory.rglob("*.desktop"):
            if f.is_file():
                return f
        return None


class InstallService:
    """Handles installing binaries, directories, AppImages, and desktop entries."""

    @staticmethod
    def _run_privileged(cmd: list[str], gui: bool = True) -> subprocess.CompletedProcess:
        prefix = ["pkexec"] if gui else ["sudo"]
        return subprocess.run(prefix + cmd, capture_output=True, text=True)

    @staticmethod
    def install_binaries(
        binaries: list[Path],
        use_sudo: bool = True,
        gui: bool = True,
        progress_cb: ProgressCallback | None = None,
    ) -> list[str]:
        installed = []
        total = len(binaries)
        for i, src in enumerate(binaries):
            dest = INSTALL_DIR / src.name
            if use_sudo:
                result = InstallService._run_privileged(
                    ["install", "-Dm755", str(src), str(dest)], gui=gui,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"Failed to install {src.name}: {result.stderr}")
            else:
                shutil.copy2(src, dest)
                dest.chmod(0o755)
            installed.append(str(dest))
            if progress_cb:
                progress_cb(f"Installed {src.name}", (i + 1) / total)
        return installed

    @staticmethod
    def install_directory(
        extract_dir: Path,
        app_name: str,
        use_sudo: bool = True,
        gui: bool = True,
    ) -> list[str]:
        opt_dir = Path(f"/opt/{app_name}")
        installed = []

        if use_sudo:
            InstallService._run_privileged(["mkdir", "-p", str(opt_dir)], gui=gui)
            InstallService._run_privileged(["cp", "-a", f"{extract_dir}/.", str(opt_dir)], gui=gui)
        else:
            opt_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(extract_dir, opt_dir, dirs_exist_ok=True)

        # Symlink main executable
        main_bin = opt_dir / app_name
        if not main_bin.exists() or not os.access(main_bin, os.X_OK):
            for f in opt_dir.iterdir():
                if f.is_file() and os.access(f, os.X_OK):
                    main_bin = f
                    break

        if main_bin.exists() and os.access(main_bin, os.X_OK):
            link = INSTALL_DIR / main_bin.name
            if use_sudo:
                InstallService._run_privileged(["ln", "-sf", str(main_bin), str(link)], gui=gui)
            else:
                link.unlink(missing_ok=True)
                link.symlink_to(main_bin)
            installed.append(str(link))

        installed.append(f"dir:{opt_dir}")
        return installed

    @staticmethod
    def install_appimage(
        appimage_path: Path,
        app_name: str,
        use_sudo: bool = True,
        gui: bool = True,
    ) -> list[str]:
        dest = INSTALL_DIR / app_name
        if use_sudo:
            result = InstallService._run_privileged(
                ["install", "-Dm755", str(appimage_path), str(dest)], gui=gui,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to install AppImage: {result.stderr}")
        else:
            shutil.copy2(appimage_path, dest)
            dest.chmod(0o755)
        return [str(dest)]

    @staticmethod
    def create_desktop_entry(
        app_name: str,
        exec_path: str,
        icon_path: str | None = None,
        terminal: bool = False,
        categories: str = "Utility;",
    ) -> str:
        DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
        desktop_file = DESKTOP_DIR / f"{app_name}.desktop"
        display_name = app_name.capitalize()

        icon_entry = app_name
        if icon_path:
            ext = Path(icon_path).suffix
            ICON_DIR.mkdir(parents=True, exist_ok=True)
            icon_dest = ICON_DIR / f"{app_name}{ext}"
            shutil.copy2(icon_path, icon_dest)
            icon_entry = str(icon_dest)

        desktop_file.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={display_name}\n"
            f"Exec={exec_path}\n"
            f"Icon={icon_entry}\n"
            f"Terminal={'true' if terminal else 'false'}\n"
            f"Categories={categories}\n"
        )
        desktop_file.chmod(0o755)

        try:
            subprocess.run(["update-desktop-database", str(DESKTOP_DIR)],
                           capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return str(desktop_file)

    @staticmethod
    def install_existing_desktop(
        source: Path,
        app_name: str,
        exec_path: str | None = None,
        icon_path: str | None = None,
    ) -> str:
        DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
        dest = DESKTOP_DIR / f"{app_name}.desktop"

        # Read and patch Exec/Icon paths to match installed locations
        content = source.read_text()
        lines = []
        for line in content.splitlines():
            if exec_path and line.startswith("Exec="):
                # Preserve any arguments after the original command
                parts = line.split(None, 1)
                args = parts[1] if len(parts) > 1 and parts[1].startswith("%") else ""
                lines.append(f"Exec={exec_path} {args}".rstrip())
            elif icon_path and line.startswith("Icon="):
                ext = Path(icon_path).suffix
                ICON_DIR.mkdir(parents=True, exist_ok=True)
                icon_dest = ICON_DIR / f"{app_name}{ext}"
                shutil.copy2(icon_path, icon_dest)
                lines.append(f"Icon={icon_dest}")
            else:
                lines.append(line)
        dest.write_text("\n".join(lines) + "\n")
        dest.chmod(0o755)

        try:
            subprocess.run(["update-desktop-database", str(DESKTOP_DIR)],
                           capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return str(dest)


class UninstallService:
    """Handles uninstalling applications."""

    @staticmethod
    def uninstall(app_name: str, gui: bool = True) -> list[str]:
        entry = Registry.get(app_name)
        if not entry:
            raise ValueError(f"{app_name} is not installed via tax")

        removed = []
        for f in entry.files:
            if f.startswith("dir:"):
                d = f[4:]
                if Path(d).is_dir():
                    InstallService._run_privileged(["rm", "-rf", d], gui=gui)
                    removed.append(d)
            elif f.startswith("src:"):
                d = f[4:]
                if Path(d).is_dir():
                    shutil.rmtree(d, ignore_errors=True)
                    removed.append(d)
            elif f.startswith("source:"):
                continue
            else:
                p = Path(f)
                if p.exists():
                    if str(p).startswith(("/usr/", "/opt/")):
                        InstallService._run_privileged(["rm", "-f", str(p)], gui=gui)
                    else:
                        p.unlink(missing_ok=True)
                    removed.append(f)

        Registry.remove(app_name)
        return removed
