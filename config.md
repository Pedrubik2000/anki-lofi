**Lofi**: click the toolbar button to play/pause, right-click it for next track, volume and source.

- `shortcuts`: work on every Anki window (main, browser, editor). Qt names like `Ctrl+Alt+L`, `Ctrl+Shift+Up`, `F9`. Empty string = no shortcut.
- `volume_step`: percent per volume shortcut press.
- `duck_percent`: music volume while card audio/video plays, as a percent of your normal music volume (0 = silent, 100 = no ducking).
- `duck_fade_ms` / `unduck_fade_ms`: fade down / back up time. `unduck_delay_ms`: wait after the card audio ends before fading back up.
- `folder`: your own music folder (searched recursively for mp3, m4a, flac, ogg, opus, wav). Or use "Choose folder..." in the right-click menu.
- `button`: `label` when paused, `playing_label` and `playing_style` (CSS) while playing.

More tracklists: put lowfi-format `.txt` files in this add-on's `user_files/tracklists/` (first line base URL or `noheader`, then one path per line, optional `!Name`).
Volume, source and whether music was playing are remembered in `user_files/state.json`.
