"""Lofi: a toolbar button that plays lofi music inside Anki.

Tracklists use lowfi's format (github.com/talwat/lowfi): the first line is a base URL
(or "noheader"), every other line a path or full URL, optionally followed by "!Display name".
Playback is Qt Multimedia (FFmpeg backend), separate from Anki's own mpv. While a card's
audio or video plays, the music fades down and comes back up afterwards.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from urllib.parse import unquote

from aqt import gui_hooks, mw
from aqt.qt import (
    QAction,
    QActionGroup,
    QCursor,
    QFileDialog,
    QKeySequence,
    QMenu,
    QShortcut,
    QSlider,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
    QWidgetAction,
)
from aqt.sound import av_player
from aqt.toolbar import Toolbar
from aqt.utils import tooltip
from PyQt6.QtMultimedia import QAudio, QAudioOutput, QMediaPlayer

ADDON = Path(__file__).parent
USER_FILES = ADDON / "user_files"
STATE_FILE = USER_FILES / "state.json"
FOLDER_SOURCE = "folder"
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}
SOURCE_NAMES = {"chillhop": "Chillhop", "lofigirl": "Lofi Girl (archive.org)"}

DEFAULTS = {
    "shortcuts": {
        "toggle": "Ctrl+Alt+L",
        "next": "Ctrl+Alt+N",
        "volume_up": "Ctrl+Alt+Up",
        "volume_down": "Ctrl+Alt+Down",
    },
    "volume_step": 5,
    "duck_percent": 20,
    "duck_fade_ms": 250,
    "unduck_fade_ms": 800,
    "unduck_delay_ms": 500,
    "folder": "",
    "button": {
        "label": "Lofi",
        "playing_label": "Lofi",
        "playing_style": "text-decoration: underline; text-underline-offset: 4px; font-weight: bold;",
    },
}
STATE_DEFAULTS = {"volume": 40, "source": "chillhop", "playing": False}

# media events don't bubble, but capture listeners on document see them; a removed element
# pauses without reaching document, so a poll drops disconnected ones
MEDIA_WATCH_JS = """<script>
(function () {
  if (window.__lofiMedia) return;
  var playing = new Set(), sent = false, poll = null;
  function report() {
    playing.forEach(function (m) { if (!m.isConnected || m.paused || m.ended || m.muted) playing.delete(m); });
    var now = playing.size > 0;
    if (now !== sent) { sent = now; pycmd("lofi_media:" + (now ? 1 : 0)); }
    if (now && !poll) poll = setInterval(report, 500);
    if (!now && poll) { clearInterval(poll); poll = null; }
  }
  window.__lofiMedia = report;
  document.addEventListener("playing", function (e) { playing.add(e.target); report(); }, true);
  ["pause", "ended", "emptied", "volumechange"].forEach(function (ev) {
    document.addEventListener(ev, function () { setTimeout(report, 0); }, true);
  });
})();
</script>"""


def _config() -> dict:
    conf = mw.addonManager.getConfig(__name__) or {}
    merged = {**DEFAULTS, **conf}
    for key in ("shortcuts", "button"):
        merged[key] = {**DEFAULTS[key], **(conf.get(key) or {})}
    return merged


def _load_state() -> dict:
    try:
        return {**STATE_DEFAULTS, **json.loads(STATE_FILE.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(STATE_DEFAULTS)


def _save_state(state: dict) -> None:
    USER_FILES.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


# --- tracklists -------------------------------------------------------------


def _name_from_path(path: str) -> str:
    stem = unquote(path.rstrip("/").rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    stem = re.sub(r"^\d+[\s.\-_]+", "", stem)
    return stem.replace("_", " ").strip() or path


def _parse_tracklist(text: str) -> list[tuple[str, str]]:
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l and not l.startswith("#")]
    if not lines:
        return []
    header, rest = lines[0], lines[1:]
    base = "" if header == "noheader" else header
    tracks = []
    for line in rest:
        path, _, name = line.partition("!")
        url = path if re.match(r"^(https?|file)://", path) else base + path
        tracks.append((url, name.strip() or _name_from_path(path)))
    return tracks


def _tracklist_files() -> dict[str, Path]:
    files = {}
    for folder in (ADDON / "tracklists", USER_FILES / "tracklists"):
        if folder.is_dir():
            for f in sorted(folder.glob("*.txt")):
                files[f.stem] = f
    return files


def _sources() -> list[tuple[str, str]]:
    out = [(k, SOURCE_NAMES.get(k, k.replace("_", " ").title())) for k in _tracklist_files()]
    folder = _config()["folder"]
    if folder:
        out.append((FOLDER_SOURCE, f"My folder ({Path(folder).name or folder})"))
    return out


def _load_tracks(source: str) -> list[tuple[str, str]]:
    if source == FOLDER_SOURCE:
        folder = Path(_config()["folder"])
        if not folder.is_dir():
            return []
        return [
            (QUrl.fromLocalFile(str(f)).toString(), f.stem)
            for f in sorted(folder.rglob("*"))
            if f.suffix.lower() in AUDIO_EXTS
        ]
    path = _tracklist_files().get(source)
    return _parse_tracklist(path.read_text(encoding="utf-8")) if path else []


# --- player -----------------------------------------------------------------


class Lofi:
    def __init__(self) -> None:
        self.state = _load_state()
        self.player = QMediaPlayer(mw)
        self.output = QAudioOutput(mw)
        self.player.setAudioOutput(self.output)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(self._on_error)
        self.tracks: list[tuple[str, str]] = []
        self.queue: list[int] = []
        self.current: tuple[str, str] | None = None
        self.errors = 0
        self.duck = 1.0  # multiplier, animated between duck_percent/100 and 1
        self.anim = QVariantAnimation(mw)
        self.anim.valueChanged.connect(self._on_duck_value)
        self.unduck_timer = QTimer(mw)
        self.unduck_timer.setSingleShot(True)
        self.unduck_timer.timeout.connect(self._maybe_unduck)
        self.shortcuts: list[QShortcut] = []
        self.web_media = False
        self._apply_volume()

    # playback

    @property
    def playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def toggle(self) -> None:
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if self.current is None:
            self.next()
            if self.current is None:
                return
        self.player.play()
        self.state["playing"] = True
        self._changed()

    def pause(self) -> None:
        self.player.pause()
        self.state["playing"] = False
        self._changed()

    def stop(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.current = None

    def next(self) -> None:
        if not self.tracks:
            self.tracks = _load_tracks(self.state["source"])
            self.queue = []
        if not self.tracks:
            tooltip(f"Lofi: no tracks in {self._source_name()}")
            self.current = None
            self._changed()
            return
        if not self.queue:
            self.queue = list(range(len(self.tracks)))
            random.shuffle(self.queue)
        self.current = self.tracks[self.queue.pop()]
        self.player.setSource(QUrl.fromEncoded(self.current[0].encode()))
        if self.state["playing"]:
            self.player.play()
        self._changed()

    def skip(self) -> None:
        self.state["playing"] = True
        self.next()

    def set_source(self, source: str) -> None:
        self.state["source"] = source
        self.tracks, self.queue = [], []
        _save_state(self.state)
        self.state["playing"] = True
        self.next()

    def _on_status(self, status) -> None:
        S = QMediaPlayer.MediaStatus
        if status == S.BufferedMedia:
            self.errors = 0
        elif status == S.EndOfMedia:
            self.next()

    def _on_error(self, error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self.errors += 1
        if self.errors >= 5:
            self.errors = 0
            self.pause()
            tooltip(f"Lofi: tracks keep failing ({message}), paused")
            return
        QTimer.singleShot(1000, self.next)

    # volume and ducking

    def change_volume(self, delta: int) -> None:
        self.set_volume(self.state["volume"] + delta)
        tooltip(f"Lofi volume {self.state['volume']}%", period=800)

    def set_volume(self, volume: int) -> None:
        self.state["volume"] = max(0, min(100, int(volume)))
        self._apply_volume()
        _save_state(self.state)
        self._update_button()

    def _apply_volume(self) -> None:
        linear = QAudio.convertVolume(
            self.state["volume"] / 100,
            QAudio.VolumeScale.LogarithmicVolumeScale,
            QAudio.VolumeScale.LinearVolumeScale,
        )
        self.output.setVolume(linear * self.duck)

    def _on_duck_value(self, value) -> None:
        self.duck = float(value)
        self._apply_volume()

    def _fade_to(self, target: float, ms: int) -> None:
        self.anim.stop()
        self.anim.setStartValue(self.duck)
        self.anim.setEndValue(target)
        self.anim.setDuration(max(1, int(ms)))
        self.anim.start()

    def on_card_audio_start(self, *args) -> None:
        conf = _config()
        self.unduck_timer.stop()
        self._fade_to(max(0, min(100, conf["duck_percent"])) / 100, conf["duck_fade_ms"])

    def on_card_audio_end(self, *args) -> None:
        self.unduck_timer.start(int(_config()["unduck_delay_ms"]))

    def _maybe_unduck(self) -> None:
        # another file may still be queued or playing (e.g. sentence then word audio)
        if av_player.current_player is not None or self.web_media:
            self.unduck_timer.start(500)
            return
        self._fade_to(1.0, _config()["unduck_fade_ms"])

    # note types that play media in the card itself (<audio>/<video>, e.g. MvJ) bypass
    # av_player, so the card page reports its own media playing via pycmd

    def inject_media_watch(self, web_content, context) -> None:
        if not isinstance(context, Toolbar):
            web_content.head += MEDIA_WATCH_JS

    def on_js_message(self, handled, message: str, context):
        if not message.startswith("lofi_media:"):
            return handled
        self.web_media = message.endswith(":1")
        if self.web_media:
            self.on_card_audio_start()
        else:
            self.on_card_audio_end()
        return (True, None)

    # toolbar button

    def _source_name(self) -> str:
        return dict(_sources()).get(self.state["source"], self.state["source"])

    def _tip(self) -> str:
        track = self.current[1] if self.current else "nothing loaded"
        status = "Playing" if self.playing else "Paused"
        return f"{status}: {track} | {self._source_name()} | {self.state['volume']}%  (right-click for more)"

    def _label_and_style(self) -> tuple[str, str]:
        button = _config()["button"]
        if self.state["playing"]:
            return button["playing_label"], button["playing_style"]
        return button["label"], ""

    def toolbar_link(self, links: list[str], toolbar) -> None:
        label, style = self._label_and_style()
        html = toolbar.create_link("lofi", label, self.toggle, tip=self._tip(), id="lofi")
        toolbar.link_handlers["lofi_menu"] = self.show_menu
        html = html.replace(
            "<a ",
            f'<a style="{style}" oncontextmenu="pycmd(\'lofi_menu\'); return false;" ',
            1,
        )
        links.append(html)

    def _update_button(self) -> None:
        label, style = self._label_and_style()
        js = (
            "(function(){var a=document.getElementById('lofi'); if(!a) return;"
            f"a.textContent={json.dumps(label)}; a.setAttribute('aria-label', {json.dumps(label)});"
            f"a.setAttribute('style', {json.dumps(style)}); a.title={json.dumps(self._tip())};}})();"
        )
        try:
            mw.toolbar.web.eval(js)
        except Exception:
            pass

    def _changed(self) -> None:
        _save_state(self.state)
        self._update_button()

    def show_menu(self) -> None:
        menu = QMenu(mw)
        menu.addAction("Pause" if self.playing else "Play", self.toggle)
        menu.addAction("Next track", self.skip)
        now = menu.addAction(f"Now: {self.current[1]}" if self.current else "Now: -")
        now.setEnabled(False)
        menu.addSeparator()

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(self.state["volume"])
        slider.setMinimumWidth(180)
        slider.setToolTip("Volume")
        slider.valueChanged.connect(self.set_volume)
        volume = QWidgetAction(menu)
        volume.setDefaultWidget(slider)
        menu.addAction(volume)
        menu.addSeparator()

        group = QActionGroup(menu)
        for key, name in _sources():
            action = QAction(name, menu, checkable=True)
            action.setChecked(key == self.state["source"])
            action.triggered.connect(lambda _=False, k=key: self.set_source(k))
            group.addAction(action)
            menu.addAction(action)
        menu.addAction("Choose folder...", self.choose_folder)
        menu.exec(QCursor.pos())

    def choose_folder(self) -> None:
        conf = mw.addonManager.getConfig(__name__) or {}
        folder = QFileDialog.getExistingDirectory(mw, "Lofi: music folder", conf.get("folder") or "")
        if not folder:
            return
        conf["folder"] = folder
        mw.addonManager.writeConfig(__name__, conf)
        self.set_source(FOLDER_SOURCE)

    # shortcuts

    def setup_shortcuts(self, *_args) -> None:
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.shortcuts = []
        conf = _config()
        step = int(conf["volume_step"])
        actions = {
            "toggle": self.toggle,
            "next": self.skip,
            "volume_up": lambda: self.change_volume(step),
            "volume_down": lambda: self.change_volume(-step),
        }
        for name, func in actions.items():
            seq = QKeySequence(conf["shortcuts"].get(name) or "")
            if seq.isEmpty():
                continue
            shortcut = QShortcut(seq, mw)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(func)
            self.shortcuts.append(shortcut)
        self._update_button()

    # profile lifecycle

    def on_profile_open(self) -> None:
        if self.state["playing"]:
            QTimer.singleShot(1500, self.play)

    def on_profile_close(self) -> None:
        was_playing = self.playing or self.state["playing"]
        self.stop()
        self.state["playing"] = was_playing
        _save_state(self.state)


lofi = Lofi()
lofi.setup_shortcuts()
mw.addonManager.setConfigUpdatedAction(__name__, lofi.setup_shortcuts)
gui_hooks.top_toolbar_did_init_links.append(lofi.toolbar_link)
gui_hooks.av_player_did_begin_playing.append(lofi.on_card_audio_start)
gui_hooks.av_player_did_end_playing.append(lofi.on_card_audio_end)
gui_hooks.webview_will_set_content.append(lofi.inject_media_watch)
gui_hooks.webview_did_receive_js_message.append(lofi.on_js_message)
gui_hooks.profile_did_open.append(lofi.on_profile_open)
gui_hooks.profile_will_close.append(lofi.on_profile_close)
