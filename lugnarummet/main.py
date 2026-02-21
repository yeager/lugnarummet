"""Lugna Rummet — Sensory Regulation app."""

import gettext
import json
import locale
import math
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from lugnarummet import __version__
from lugnarummet.accessibility import apply_large_text
from lugnarummet.music import MusicPlayer

# i18n
try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass

LOCALE_DIR = None
for d in [
    Path(__file__).parent.parent / "po",
    Path("/usr/share/locale"),
    Path("/usr/local/share/locale"),
]:
    if d.is_dir():
        LOCALE_DIR = d
        break

locale.bindtextdomain("lugnarummet", str(LOCALE_DIR) if LOCALE_DIR else None)
gettext.bindtextdomain("lugnarummet", str(LOCALE_DIR) if LOCALE_DIR else None)
gettext.textdomain("lugnarummet")
_ = gettext.gettext

APP_ID = "se.danielnylander.lugnarummet"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lugnarummet"


def _load_settings():
    path = CONFIG_DIR / "settings.json"
    defaults = {
        "breathe_in": 4,
        "breathe_hold": 4,
        "breathe_out": 6,
        "favorite_strategy": "",
    }
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                defaults.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def _save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_DIR / "settings.json", "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def _speak(text):
    """TTS: Piper first, espeak-ng fallback."""
    def _do():
        if shutil.which("piper"):
            try:
                p = subprocess.Popen(
                    ["piper", "--model", "sv_SE-nst-medium", "--output-raw"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
                raw, _ = p.communicate(text.encode(), timeout=10)
                if raw and shutil.which("aplay"):
                    a = subprocess.Popen(
                        ["aplay", "-r", "22050", "-f", "S16_LE", "-q"],
                        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
                    )
                    a.communicate(raw, timeout=10)
                    return
            except Exception:
                pass
        if shutil.which("espeak-ng"):
            try:
                subprocess.run(["espeak-ng", "-v", "sv", text], timeout=10, capture_output=True)
            except Exception:
                pass
    threading.Thread(target=_do, daemon=True).start()


class BreathingWidget(Gtk.DrawingArea):
    """Animated breathing circle."""

    def __init__(self):
        super().__init__()
        self.set_content_width(250)
        self.set_content_height(250)
        self.set_draw_func(self._draw)
        self.phase = "idle"  # idle, in, hold, out
        self.progress = 0.0  # 0-1
        self.running = False
        self._tick_id = None

    def _draw(self, area, cr, width, height):
        cx, cy = width / 2, height / 2
        max_r = min(width, height) / 2 - 15
        min_r = max_r * 0.3

        # Calculate current radius based on phase
        if self.phase == "in":
            r = min_r + (max_r - min_r) * self.progress
        elif self.phase == "hold":
            r = max_r
        elif self.phase == "out":
            r = max_r - (max_r - min_r) * self.progress
        else:
            r = min_r

        # Outer glow
        cr.set_source_rgba(0.4, 0.7, 0.9, 0.1)
        cr.arc(cx, cy, r + 10, 0, 2 * math.pi)
        cr.fill()

        # Main circle
        cr.set_source_rgba(0.4, 0.7, 0.9, 0.4)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()

        # Inner circle
        cr.set_source_rgba(0.5, 0.8, 1.0, 0.6)
        cr.arc(cx, cy, r * 0.6, 0, 2 * math.pi)
        cr.fill()

        # Phase text
        labels = {
            "idle": _("Tap to start"),
            "in": _("Breathe in…"),
            "hold": _("Hold…"),
            "out": _("Breathe out…"),
        }
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_font_size(18)
        text = labels.get(self.phase, "")
        extents = cr.text_extents(text)
        cr.move_to(cx - extents.width / 2, cy + extents.height / 2)
        cr.show_text(text)

    def start_cycle(self, breathe_in=4, hold=4, breathe_out=6):
        self.breathe_in = breathe_in
        self.hold = hold
        self.breathe_out = breathe_out
        self.running = True
        self._run_phase("in", breathe_in)

    def _run_phase(self, phase, duration):
        if not self.running:
            return
        self.phase = phase
        self.progress = 0.0
        self._phase_start = time.monotonic()
        self._phase_duration = duration
        if self._tick_id:
            GLib.source_remove(self._tick_id)
        self._tick_id = GLib.timeout_add(30, self._tick)

    def _tick(self):
        if not self.running:
            return False
        elapsed = time.monotonic() - self._phase_start
        self.progress = min(1.0, elapsed / self._phase_duration)
        self.queue_draw()
        if self.progress >= 1.0:
            # Next phase
            if self.phase == "in":
                self._run_phase("hold", self.hold)
            elif self.phase == "hold":
                self._run_phase("out", self.breathe_out)
            elif self.phase == "out":
                self._run_phase("in", self.breathe_in)
            return False
        return True

    def stop(self):
        self.running = False
        self.phase = "idle"
        self.progress = 0
        self.queue_draw()


# Calming strategies
STRATEGIES = [
    {"icon": "🫁", "name_key": "Deep breathing", "desc_key": "Slow, deep breaths to calm your nervous system"},
    {"icon": "🧊", "name_key": "Hold ice", "desc_key": "Hold an ice cube — the cold sensation helps ground you"},
    {"icon": "5️⃣", "name_key": "5-4-3-2-1 grounding", "desc_key": "5 things you see, 4 you hear, 3 you touch, 2 you smell, 1 you taste"},
    {"icon": "🎧", "name_key": "Listen to music", "desc_key": "Put on calming music or white noise"},
    {"icon": "🤗", "name_key": "Pressure", "desc_key": "Hug yourself tight, use a weighted blanket, or squeeze a stress ball"},
    {"icon": "🚶", "name_key": "Walk away", "desc_key": "Leave the situation. Go somewhere quiet for a few minutes"},
    {"icon": "💧", "name_key": "Cold water", "desc_key": "Splash cold water on your face or wrists"},
    {"icon": "🧶", "name_key": "Fidget", "desc_key": "Use a fidget toy, rubber band, or squeeze something"},
]


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Calming Room"))
        self.set_default_size(450, 650)
        self.settings = _load_settings()
        self.sessions = self._load_sessions()

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        main_box.append(header)

        from lugnarummet.export import show_export_dialog
        self._show_export_dialog = show_export_dialog

        export_btn = Gtk.Button(icon_name="document-save-symbolic",
                                tooltip_text=_("Export sessions (Ctrl+E)"))
        export_btn.connect("clicked", self._on_export)
        header.pack_end(export_btn)

        menu = Gio.Menu()
        menu.append(_("Export Sessions"), "win.export")
        menu.append(_("Preferences"), "app.preferences")
        menu.append(_("About Calming Room"), "app.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_btn)

        export_action = Gio.SimpleAction.new("export", None)
        export_action.connect("activate", self._on_export)
        self.add_action(export_action)

        # Ctrl+E shortcut
        ctrl = Gtk.EventControllerKey()
        ctrl.connect("key-pressed", self._on_key)
        self.add_controller(ctrl)

        # Music player
        self.music_player = MusicPlayer("lugnarummet")

        # View stack
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcherBar()
        switcher.set_stack(self.stack)
        switcher.set_reveal(True)

        # Breathing page
        breathe_page = self._build_breathe_page()
        self.stack.add_titled(breathe_page, "breathe", _("Breathe"))
        self.stack.get_page(breathe_page).set_icon_name("weather-clear-symbolic")

        # Strategies page
        strategies_page = self._build_strategies_page()
        self.stack.add_titled(strategies_page, "strategies", _("Strategies"))
        self.stack.get_page(strategies_page).set_icon_name("view-list-symbolic")

        # Feeling page
        feeling_page = self._build_feeling_page()
        self.stack.add_titled(feeling_page, "feeling", _("How do I feel?"))
        self.stack.get_page(feeling_page).set_icon_name("face-smile-symbolic")

        # Music page
        music_page = self._build_music_page()
        self.stack.add_titled(music_page, "music", _("Music"))
        self.stack.get_page(music_page).set_icon_name("audio-x-generic-symbolic")

        main_box.append(self.stack)
        main_box.append(switcher)


    def _build_music_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page.set_margin_top(20)
        page.set_margin_bottom(20)
        page.set_margin_start(20)
        page.set_margin_end(20)
        page.set_valign(Gtk.Align.CENTER)

        # Title
        title = Gtk.Label(label=_("Background Music"))
        title.add_css_class("title-1")
        page.append(title)

        subtitle = Gtk.Label(label=_("Calming classical music for relaxation"))
        subtitle.add_css_class("dim-label")
        page.append(subtitle)

        # Now playing label
        self.music_now_playing = Gtk.Label(label="")
        self.music_now_playing.add_css_class("dim-label")
        self.music_now_playing.set_margin_top(12)
        page.append(self.music_now_playing)

        # Play/Pause button
        self.music_play_btn = Gtk.Button()
        self.music_play_btn.set_icon_name("media-playback-start-symbolic")
        self.music_play_btn.add_css_class("circular")
        self.music_play_btn.add_css_class("suggested-action")
        self.music_play_btn.set_halign(Gtk.Align.CENTER)
        self.music_play_btn.set_size_request(64, 64)
        self.music_play_btn.set_tooltip_text(_("Play / Pause"))
        self.music_play_btn.connect("clicked", self._on_music_toggle)
        page.append(self.music_play_btn)

        # Volume control
        vol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vol_box.set_halign(Gtk.Align.CENTER)
        vol_box.set_margin_top(12)

        vol_icon = Gtk.Image.new_from_icon_name("audio-volume-medium-symbolic")
        vol_box.append(vol_icon)

        self.music_volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.music_volume.set_value(30)
        self.music_volume.set_size_request(200, -1)
        self.music_volume.set_draw_value(False)
        self.music_volume.connect("value-changed", self._on_music_volume)
        vol_box.append(self.music_volume)

        page.append(vol_box)

        # Track list
        tracks = self.music_player.get_available_tracks()
        if tracks:
            track_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            track_list.set_margin_top(16)
            for t in tracks:
                label = f"🎵 {t['composer']} — {t['title']}" if t['composer'] else f"🎵 {t['title']}"
                row = Gtk.Label(label=label)
                row.add_css_class("dim-label")
                track_list.append(row)
            page.append(track_list)
        else:
            no_music = Gtk.Label(label=_("No music files found.\nAdd .mp3 files to ~/.config/lugnarummet/music/"))
            no_music.add_css_class("dim-label")
            no_music.set_margin_top(16)
            page.append(no_music)

        return page

    def _on_music_toggle(self, btn):
        if self.music_player.is_playing:
            self.music_player.pause()
            btn.set_icon_name("media-playback-start-symbolic")
            self.music_now_playing.set_text("")
        else:
            tracks = self.music_player.get_available_tracks()
            if tracks:
                self.music_player.play(tracks[0]["path"])
                btn.set_icon_name("media-playback-pause-symbolic")
                t = tracks[0]
                label = f"♫ {t['composer']} — {t['title']}" if t['composer'] else f"♫ {t['title']}"
                self.music_now_playing.set_text(label)
            elif not self.music_player.is_playing and self.music_player._pipeline:
                self.music_player.resume()
                btn.set_icon_name("media-playback-pause-symbolic")

    def _on_music_volume(self, scale):
        self.music_player.set_volume(scale.get_value() / 100.0)

    def _build_breathe_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page.set_margin_top(20)
        page.set_margin_bottom(20)
        page.set_margin_start(20)
        page.set_margin_end(20)

        title = Gtk.Label(label=_("Breathing Exercise"))
        title.add_css_class("title-2")
        page.append(title)

        self.breathing = BreathingWidget()
        click = Gtk.GestureClick()
        click.connect("released", self._on_breathe_click)
        self.breathing.add_controller(click)
        page.append(self.breathing)

        btn_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.breathe_btn = Gtk.Button(label=_("Start"))
        self.breathe_btn.add_css_class("suggested-action")
        self.breathe_btn.add_css_class("pill")
        self.breathe_btn.connect("clicked", self._on_breathe_click)
        btn_box.append(self.breathe_btn)

        stop_btn = Gtk.Button(label=_("Stop"))
        stop_btn.add_css_class("destructive-action")
        stop_btn.add_css_class("pill")
        stop_btn.connect("clicked", self._on_breathe_stop)
        btn_box.append(stop_btn)
        page.append(btn_box)

        info = Gtk.Label(
            label=_("Breathe in {in_}s · Hold {hold}s · Breathe out {out}s").format(
                in_=self.settings["breathe_in"],
                hold=self.settings["breathe_hold"],
                out=self.settings["breathe_out"],
            )
        )
        info.add_css_class("dim-label")
        page.append(info)

        return page

    def _build_strategies_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        listbox.set_margin_start(12)
        listbox.set_margin_end(12)
        listbox.set_margin_top(12)

        # Emergency button at top
        emergency_btn = Gtk.Button(label=_("🆘 I need help NOW"))
        emergency_btn.add_css_class("destructive-action")
        emergency_btn.add_css_class("pill")
        emergency_btn.set_margin_start(12)
        emergency_btn.set_margin_end(12)
        emergency_btn.set_margin_top(12)
        emergency_btn.connect("clicked", self._on_emergency)
        page.append(emergency_btn)

        for s in STRATEGIES:
            row = Adw.ActionRow(
                title=f"{s['icon']} {_(s['name_key'])}",
                subtitle=_(s["desc_key"]),
            )
            row.set_activatable(True)
            listbox.append(row)

        scroll.set_child(listbox)
        page.append(scroll)
        return page

    def _build_feeling_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_margin_top(20)
        page.set_margin_start(20)
        page.set_margin_end(20)

        title = Gtk.Label(label=_("How stressed are you right now?"))
        title.add_css_class("title-3")
        page.append(title)

        # Stress level scale with emoji
        self.stress_label = Gtk.Label(label="😊")
        self.stress_label.add_css_class("title-1")
        page.append(self.stress_label)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 10, 1)
        scale.set_value(3)
        scale.set_draw_value(True)
        scale.set_hexpand(True)

        # Add marks
        scale.add_mark(1, Gtk.PositionType.BOTTOM, _("Calm"))
        scale.add_mark(5, Gtk.PositionType.BOTTOM, _("Medium"))
        scale.add_mark(10, Gtk.PositionType.BOTTOM, _("Overload"))
        scale.connect("value-changed", self._on_stress_changed)
        page.append(scale)

        self.suggestion_label = Gtk.Label(wrap=True)
        self.suggestion_label.add_css_class("dim-label")
        self.suggestion_label.set_margin_top(12)
        page.append(self.suggestion_label)

        self._on_stress_changed(scale)
        return page

    def _on_breathe_click(self, *_):
        if not self.breathing.running:
            self.breathing.start_cycle(
                self.settings["breathe_in"],
                self.settings["breathe_hold"],
                self.settings["breathe_out"],
            )
            self.breathe_btn.set_label(_("Running…"))
            self.breathe_btn.set_sensitive(False)

    def _on_breathe_stop(self, *_):
        self.breathing.stop()
        self.breathe_btn.set_label(_("Start"))
        self.breathe_btn.set_sensitive(True)

    def _on_emergency(self, *_):
        fav = self.settings.get("favorite_strategy", "")
        if fav:
            msg = _("Your favorite strategy: {strategy}").format(strategy=fav)
        else:
            msg = _("Try this: Take 5 deep breaths. Count each one. You are safe.")
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("You are safe 💙"),
            body=msg,
        )
        dialog.add_response("breathe", _("Go to breathing"))
        dialog.add_response("ok", _("OK"))
        dialog.set_response_appearance("breathe", Adw.ResponseAppearance.SUGGESTED)

        def on_response(d, response):
            d.close()
            if response == "breathe":
                self.stack.set_visible_child_name("breathe")
                GLib.idle_add(self._on_breathe_click)

        dialog.connect("response", on_response)
        if self.settings.get("sound_enabled", True):
            _speak(_("You are safe. Take a deep breath."))
        dialog.present()

    def _on_stress_changed(self, scale):
        val = int(scale.get_value())
        emojis = {1: "😊", 2: "🙂", 3: "😐", 4: "😕", 5: "😟",
                  6: "😰", 7: "😫", 8: "🤯", 9: "😭", 10: "💥"}
        self.stress_label.set_text(emojis.get(val, "😐"))
        if val <= 3:
            self.suggestion_label.set_text(_("You seem calm. Great! Keep doing what you're doing."))
        elif val <= 5:
            self.suggestion_label.set_text(_("Getting a bit tense. Try a short breathing exercise."))
        elif val <= 7:
            self.suggestion_label.set_text(_("High stress. Take a break now. Try the breathing exercise or one of the strategies."))
        else:
            self.suggestion_label.set_text(_("Very high stress. Press the emergency button or go to breathing immediately. You are safe. 💙"))


    def _on_key(self, ctrl, keyval, keycode, state):
        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval == Gdk.KEY_e or keyval == Gdk.KEY_E:
                self._on_export()
                return True
        return False

    def _sessions_path(self):
        p = Path(GLib.get_user_config_dir()) / "lugnarummet"
        p.mkdir(parents=True, exist_ok=True)
        return p / "sessions.json"

    def _load_sessions(self):
        path = self._sessions_path()
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        return []

    def _save_sessions(self):
        self._sessions_path().write_text(
            json.dumps(self.sessions, indent=2, ensure_ascii=False))

    def log_session(self, session_type, duration_min=0, stress_before="", stress_after=""):
        from datetime import datetime
        self.sessions.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "type": session_type,
            "duration": duration_min,
            "stress_before": stress_before,
            "stress_after": stress_after,
        })
        self.sessions = self.sessions[-200:]
        self._save_sessions()

    def _on_export(self, *args):
        self._show_export_dialog(self, self.sessions,
                                 lambda msg: print(msg))


class LugnaRummetApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._on_activate)

    def _on_activate(self, *_):
        win = self.props.active_window
        if not win:
            win = MainWindow(self)
        self._create_action("about", self._on_about)
        self._create_action("preferences", self._on_preferences)
        quit_action = Gio.SimpleAction(name="quit")
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        win.present()

    def _create_action(self, name, callback):
        action = Gio.SimpleAction(name=name)
        action.connect("activate", callback)
        self.add_action(action)

    def _on_about(self, *_):
        dialog = Adw.AboutDialog(
            application_name=_("Calming Room"),
            application_icon=APP_ID,
            version=__version__,
            developer_name="Daniel Nylander",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/yeager/lugnarummet",
            issue_url="https://github.com/yeager/lugnarummet/issues",
            developers=["Daniel Nylander <daniel@danielnylander.se>"],
            copyright="© 2026 Daniel Nylander",
            comments=_("Sensory regulation and calming strategies for autism and ADHD"),
        )
        dialog.present(self.props.active_window)

    def _on_preferences(self, *_):
        win = self.props.active_window
        prefs = Adw.PreferencesWindow(title=_("Preferences"), transient_for=win)
        page = Adw.PreferencesPage(title=_("Breathing"))
        settings = _load_settings()

        group = Adw.PreferencesGroup(title=_("Breathing Pattern"))
        in_row = Adw.SpinRow.new_with_range(1, 10, 1)
        in_row.set_title(_("Breathe in (seconds)"))
        in_row.set_value(settings.get("breathe_in", 4))
        group.add(in_row)

        hold_row = Adw.SpinRow.new_with_range(0, 10, 1)
        hold_row.set_title(_("Hold (seconds)"))
        hold_row.set_value(settings.get("breathe_hold", 4))
        group.add(hold_row)

        out_row = Adw.SpinRow.new_with_range(1, 15, 1)
        out_row.set_title(_("Breathe out (seconds)"))
        out_row.set_value(settings.get("breathe_out", 6))
        group.add(out_row)

        page.add(group)
        prefs.add(page)

        def on_close(*_):
            settings["breathe_in"] = int(in_row.get_value())
            settings["breathe_hold"] = int(hold_row.get_value())
            settings["breathe_out"] = int(out_row.get_value())
            _save_settings(settings)

        prefs.connect("close-request", on_close)
        prefs.present()


def main():
    app = LugnaRummetApp()
    return app.run()
