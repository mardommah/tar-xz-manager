# Tar Xz Installer Manager

A practical tar archive installer for Linux. Tax handles extracting, installing, and managing applications distributed as `.tar.xz`, `.tar.gz`, `.tar.bz2`, and `.tar.zst` archives.

## Features

- Automatic detection of application type (AppImage, pre-built binary, source code with Makefile/CMake/Meson/configure)
- Interactive binary selection when multiple executables are found
- Desktop entry (`.desktop` file) creation with icon detection
- Install registry for tracking and cleanly uninstalling applications
- Full directory install to `/opt` for applications that require all bundled files
- Both CLI and GUI (GTK4 + libadwaita) interfaces

## Supported Archive Formats

- `.tar.xz` / `.txz`
- `.tar.gz` / `.tgz`
- `.tar.bz2` / `.tbz2`
- `.tar.zst` / `.tzst`

## Installation

Run the install script:

```bash
./install.sh
```

This will:

1. Copy the `tax` CLI tool to `/usr/local/bin/`
2. Install the GUI package to `/opt/tax-installer/`
3. Install the `tax-gui` launcher to `/usr/local/bin/`
4. Create a desktop entry for the GUI

## Usage

### CLI

```bash
tax install <archive>           # Install application from archive
tax install app.tar.xz --name myapp   # Install with a custom name
tax install app.tar.gz --bin-path bin/app --icon icon.png
tax install app.tar.xz --full  # Install full directory to /opt
tax list                        # List installed applications
tax info <name>                 # Show details about an installed app
tax uninstall <name>            # Uninstall an application
tax help                        # Show help
```

### GUI

```bash
tax-gui
```

Or launch "Tax Installer" from your application menu.

### CLI Options

| Option | Description |
|---|---|
| `--name <name>` | Override the auto-detected application name |
| `--bin-path <path>` | Specify the binary path inside the archive (relative) |
| `--icon <path>` | Specify the icon path inside the archive (relative) |
| `--no-desktop` | Skip `.desktop` file creation |
| `--system` | Install to system directories (requires sudo) |
| `--full` | Install the entire directory to `/opt/<name>` |

## How It Works

1. **Extract** -- The archive is extracted to a temporary directory.
2. **Detect** -- Tax identifies the application type by scanning for AppImages, executables, and build system files.
3. **Install** -- Binaries are copied to `/usr/local/bin/`, or the full directory is placed under `/opt/`. AppImages are installed directly.
4. **Register** -- An entry is saved to `~/.local/share/tax-installer/` so the application can be cleanly uninstalled later.
5. **Desktop Entry** -- Optionally creates a `.desktop` file with auto-detected or user-specified icon.

## Project Structure

```
tax-installer/
  __init__.py      -- Package metadata and version
  model.py         -- Data classes, enums, constants, and registry persistence
  service.py       -- Business logic: extract, detect, install, uninstall
  controller.py    -- Bridges view and service layers, handles threading
  view.py          -- GTK4 + libadwaita GUI
  tax              -- CLI tool (bash)
  tax-gui          -- GUI entry point (python)
  install.sh       -- Setup script
```

## Dependencies

### CLI

- `bash`
- `tar` (with zstd support for `.tar.zst`)
- Standard Linux utilities (`find`, `install`, `mktemp`)

### GUI

- Python 3
- GTK 4
- libadwaita
- PyGObject (`gi`)

## License

This project is provided as-is for personal use.
