"""View layer — GTK4 + libadwaita GUI. Pure presentation, delegates to controllers."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from __init__ import __version__
from model import SUPPORTED_EXTENSIONS


# ── Application ────────────────────────────────────────────────────────────────

class TaxInstallerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.tax_installer",
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )

    def do_activate(self):
        win = self.props.active_window or MainWindow(application=self)
        win.present()

    def do_open(self, files, n_files, hint):
        self.do_activate()
        win = self.props.active_window
        if files:
            win.install_ctrl.load_archive(files[0].get_path())


# ── Main Window ────────────────────────────────────────────────────────────────

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs, default_width=700, default_height=600)
        self.set_title("Tax Installer")

        # Import controllers here to avoid circular imports
        from controller import InstallController, InstalledController

        self.install_ctrl = InstallController(self)
        self.installed_ctrl = InstalledController(self)

        # Toast overlay wraps everything
        self._toast_overlay = Adw.ToastOverlay()

        # ── View stack ─────────────────────────────────────────────────────
        self._stack = Adw.ViewStack()
        self._stack.add_titled(self._build_install_page(), "install", "Install")
        self._stack.add_titled(self._build_installed_page(), "installed", "Installed")
        self._stack.connect("notify::visible-child", self._on_page_changed)

        # ── Header ─────────────────────────────────────────────────────────
        header = Adw.HeaderBar()
        switcher_title = Adw.ViewSwitcherTitle(stack=self._stack, title="Tax Installer")
        header.set_title_widget(switcher_title)

        switcher_bar = Adw.ViewSwitcherBar(stack=self._stack)
        switcher_bar.set_reveal(True)
        switcher_title.connect(
            "notify::title-visible",
            lambda s, _: switcher_bar.set_reveal(s.get_title_visible()),
        )

        about_btn = Gtk.Button(icon_name="help-about-symbolic", tooltip_text="About")
        about_btn.connect("clicked", self._on_about)
        header.pack_end(about_btn)

        # ── Assemble ───────────────────────────────────────────────────────
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header)
        box.append(self._stack)
        box.append(switcher_bar)

        self._toast_overlay.set_child(box)
        self.set_content(self._toast_overlay)

    # ══════════════════════════════════════════════════════════════════════
    # Install page
    # ══════════════════════════════════════════════════════════════════════

    def _build_install_page(self) -> Gtk.Widget:
        self._install_nav = Adw.NavigationView()

        status = Adw.StatusPage(
            icon_name="package-x-generic-symbolic",
            title="Install Application",
            description=(
                "Drag & drop a .tar.xz / .tar.gz archive here,\n"
                "or click the button below to select one."
            ),
        )

        btn = Gtk.Button(label="Select Archive",
                         css_classes=["suggested-action", "pill"],
                         halign=Gtk.Align.CENTER, margin_bottom=24)
        btn.connect("clicked", self._on_select_archive)
        status.set_child(btn)

        # Drag-and-drop
        drop = Gtk.DropTarget(actions=Gdk.DragAction.COPY)
        drop.set_gtypes([Gio.File])
        drop.connect("drop", self._on_drop)
        status.add_controller(drop)

        self._install_nav.push(Adw.NavigationPage(title="Install", child=status))
        return self._install_nav

    def _build_detail_widgets(self) -> Adw.NavigationPage:
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp(maximum_size=600)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=24, margin_bottom=24, margin_start=16, margin_end=16,
        )

        # ── Info group ─────────────────────────────────────────────────────
        info_group = Adw.PreferencesGroup(title="Archive Info")

        self._row_archive = Adw.ActionRow(title="Archive")
        info_group.add(self._row_archive)

        self._row_name = Adw.ActionRow(title="App Name")
        self._name_entry = Gtk.Entry(valign=Gtk.Align.CENTER, placeholder_text="app-name")
        self._row_name.add_suffix(self._name_entry)
        info_group.add(self._row_name)

        self._row_type = Adw.ActionRow(title="Detected Type")
        info_group.add(self._row_type)

        self._row_contents = Adw.ActionRow(title="Contents")
        info_group.add(self._row_contents)

        content.append(info_group)

        # ── Build warning banner ───────────────────────────────────────────
        self._build_banner = Adw.Banner(
            title="Source code detected — build from terminal recommended",
        )
        self._build_banner.set_button_label("Copy Command")
        self._build_banner.connect("button-clicked", self._on_copy_build_cmd)
        content.append(self._build_banner)

        # ── Executables ────────────────────────────────────────────────────
        self._exec_group = Adw.PreferencesGroup(title="Executables to Install")
        self._exec_checks: list[tuple[Gtk.CheckButton, Path]] = []
        content.append(self._exec_group)

        # ── Options ────────────────────────────────────────────────────────
        opts = Adw.PreferencesGroup(title="Options")

        self._switch_desktop = Adw.SwitchRow(
            title="Create Desktop Entry", subtitle="Add to application menu",
        )
        self._switch_desktop.set_active(True)
        opts.add(self._switch_desktop)

        self._switch_full = Adw.SwitchRow(
            title="Full Directory Install", subtitle="Copy everything to /opt/<name>",
        )
        opts.add(self._switch_full)

        content.append(opts)

        # ── Progress ───────────────────────────────────────────────────────
        self._install_progress = Gtk.ProgressBar(visible=False, margin_top=8)
        self._install_label = Gtk.Label(
            label="", visible=False, css_classes=["dim-label"],
            halign=Gtk.Align.START, margin_top=4,
        )
        content.append(self._install_progress)
        content.append(self._install_label)

        # ── Install button ─────────────────────────────────────────────────
        self._install_btn = Gtk.Button(
            label="Install", css_classes=["suggested-action", "pill"],
            halign=Gtk.Align.CENTER, margin_top=12,
        )
        self._install_btn.connect("clicked", self._on_install_clicked)
        content.append(self._install_btn)

        clamp.set_child(content)
        scroll.set_child(clamp)
        page_box.append(scroll)
        return Adw.NavigationPage(title="Details", child=page_box)

    # ══════════════════════════════════════════════════════════════════════
    # Installed page
    # ══════════════════════════════════════════════════════════════════════

    def _build_installed_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp(maximum_size=600)

        self._installed_content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=24, margin_bottom=24, margin_start=16, margin_end=16,
        )
        self._installed_group = Adw.PreferencesGroup(title="Installed Applications")
        self._installed_content.append(self._installed_group)

        clamp.set_child(self._installed_content)
        scroll.set_child(clamp)

        self._installed_empty = Adw.StatusPage(
            icon_name="checkbox-checked-symbolic",
            title="No Applications",
            description="Applications installed via tax will appear here.",
        )

        self._installed_stack = Gtk.Stack()
        self._installed_stack.add_named(scroll, "list")
        self._installed_stack.add_named(self._installed_empty, "empty")

        box.append(self._installed_stack)
        return box

    def _refresh_installed_list(self):
        self._installed_content.remove(self._installed_group)
        self._installed_group = Adw.PreferencesGroup(title="Installed Applications")
        self._installed_content.prepend(self._installed_group)

        entries = self.installed_ctrl.load_entries()

        if not entries:
            self._installed_stack.set_visible_child_name("empty")
            return

        self._installed_stack.set_visible_child_name("list")

        for entry in entries:
            row = Adw.ActionRow(
                title=entry.name,
                subtitle=f"{entry.archive}  •  {entry.date[:10] if entry.date else 'unknown'}",
            )
            btn = Gtk.Button(
                icon_name="user-trash-symbolic",
                css_classes=["destructive-action", "flat"],
                valign=Gtk.Align.CENTER, tooltip_text="Uninstall",
            )
            btn.connect("clicked", self._on_uninstall_clicked, entry.name)
            row.add_suffix(btn)
            row.set_activatable_widget(btn)
            self._installed_group.add(row)

    # ══════════════════════════════════════════════════════════════════════
    # View callbacks (called by controllers via GLib.idle_add)
    # ══════════════════════════════════════════════════════════════════════

    def show_toast(self, message: str):
        self._toast_overlay.add_toast(Adw.Toast(title=message, timeout=3))

    def show_detail_page(self, archive_name: str, app_name: str):
        detail_page = self._build_detail_widgets()
        self._install_nav.push(detail_page)

        self._row_archive.set_subtitle(archive_name)
        self._name_entry.set_text(app_name)
        self._row_type.set_subtitle("Extracting...")
        self._row_contents.set_subtitle("...")
        self._build_banner.set_revealed(False)
        self._install_btn.set_sensitive(False)

    def update_extract_progress(self, fraction: float):
        self._row_type.set_subtitle(f"Extracting... {int(fraction * 100)}%")

    def populate_details(
        self, type_label: str, file_count: int, dir_count: int,
        is_build_type: bool, build_command: str,
        executables: list[Path], root_dir: Path,
    ):
        self._row_type.set_subtitle(type_label)
        self._row_contents.set_subtitle(f"{file_count} files, {dir_count} directories")
        self._build_banner.set_revealed(is_build_type)

        if is_build_type:
            self._build_banner.set_title(f"Source code detected — run: {build_command}")
            self._install_btn.set_sensitive(False)
        else:
            self._install_btn.set_sensitive(True)

        self._exec_checks.clear()
        if not executables:
            self._exec_group.set_description("No executables found")
        else:
            for exe in executables[:20]:
                rel = str(exe.relative_to(root_dir))
                size = exe.stat().st_size
                size_str = f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / (1024*1024):.1f} MB"

                check = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER)
                row = Adw.ActionRow(title=rel, subtitle=size_str)
                row.add_prefix(check)
                row.set_activatable_widget(check)
                self._exec_group.add(row)
                self._exec_checks.append((check, exe))

            if len(executables) > 20:
                self._exec_group.set_description(f"Showing 20 of {len(executables)} executables")

    def update_install_status(self, message: str, fraction: float):
        self._install_progress.set_fraction(fraction)
        self._install_label.set_label(message)

    def set_installing(self, active: bool):
        self._install_btn.set_sensitive(not active)
        self._install_progress.set_visible(active)
        self._install_label.set_visible(active)
        if active:
            self._install_progress.set_fraction(0)
            self._install_label.set_label("Installing...")

    def on_install_complete(self, app_name: str):
        self._install_progress.set_fraction(1.0)
        self._install_label.set_label("Done!")
        self.show_toast(f"{app_name} installed successfully!")
        GLib.timeout_add(1500, self._pop_detail_page)

    def _pop_detail_page(self):
        self._install_nav.pop()
        self.set_installing(False)
        return False

    def confirm_reinstall(self, app_name: str):
        dialog = Adw.AlertDialog(
            heading=f"'{app_name}' is already installed",
            body="Do you want to reinstall it?",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reinstall", "Reinstall")
        dialog.set_response_appearance("reinstall", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_reinstall_response, app_name)
        dialog.present(self)

    def on_uninstall_complete(self, app_name: str):
        self.show_toast(f"{app_name} uninstalled")
        self._refresh_installed_list()

    # ══════════════════════════════════════════════════════════════════════
    # Event handlers (user interaction → controller)
    # ══════════════════════════════════════════════════════════════════════

    def _on_page_changed(self, stack, _param):
        if stack.get_visible_child_name() == "installed":
            self._refresh_installed_list()

    def _on_select_archive(self, _btn):
        dialog = Gtk.FileDialog()
        ff = Gtk.FileFilter()
        ff.set_name("Archives (tar.xz, tar.gz, tar.bz2, tar.zst)")
        for ext in SUPPORTED_EXTENSIONS:
            ff.add_pattern(f"*{ext}")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(ff)
        dialog.set_filters(filters)
        dialog.set_default_filter(ff)
        dialog.open(self, None, self._on_file_selected)

    def _on_file_selected(self, dialog, result):
        try:
            f = dialog.open_finish(result)
            if f:
                self.install_ctrl.load_archive(f.get_path())
        except GLib.Error:
            pass

    def _on_drop(self, _target, value, _x, _y):
        if isinstance(value, Gio.File):
            path = value.get_path()
            if path and self.install_ctrl.validate_archive(path):
                self.install_ctrl.load_archive(path)
                return True
        return False

    def _on_install_clicked(self, _btn):
        name = self._name_entry.get_text().strip() or self.install_ctrl.app_name
        selected = [path for check, path in self._exec_checks if check.get_active()]
        self.install_ctrl.install(
            app_name=name,
            selected_bins=selected,
            create_desktop=self._switch_desktop.get_active(),
            full_install=self._switch_full.get_active(),
        )

    def _on_reinstall_response(self, dialog, response, app_name):
        if response == "reinstall":
            selected = [path for check, path in self._exec_checks if check.get_active()]
            self.install_ctrl.force_reinstall(
                app_name=app_name,
                selected_bins=selected,
                create_desktop=self._switch_desktop.get_active(),
                full_install=self._switch_full.get_active(),
            )

    def _on_uninstall_clicked(self, _btn, app_name: str):
        dialog = Adw.AlertDialog(
            heading=f"Uninstall '{app_name}'?",
            body="This will remove all files installed by tax for this application.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("uninstall", "Uninstall")
        dialog.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_uninstall_confirmed, app_name)
        dialog.present(self)

    def _on_uninstall_confirmed(self, dialog, response, app_name):
        if response == "uninstall":
            self.installed_ctrl.uninstall(app_name)

    def _on_copy_build_cmd(self, _banner):
        cmd = self.install_ctrl.copy_build_command()
        if cmd:
            Gdk.Display.get_default().get_clipboard().set(cmd)
            self.show_toast("Build command copied to clipboard")

    def _on_about(self, _btn):
        Adw.AboutDialog(
            application_name="Tax Installer",
            application_icon="package-x-generic-symbolic",
            version=__version__,
            developer_name="tax-installer",
            comments="Practical tar.xz/gz installer for Linux",
            license_type=Gtk.License.MIT_X11,
        ).present(self)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = TaxInstallerApp()
    app.run(sys.argv)
