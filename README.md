# Lofi for Anki

A **Lofi** button in Anki's top toolbar (next to Decks · Add · Browse · Stats · Sync) that plays
lofi music while you review, inspired by [lowfi](https://github.com/talwat/lowfi) and using its tracklists.

- **Click** to play/pause; the button is underlined while playing and its tooltip shows the track.
- **Right-click** for next track, a volume slider, the music source and "Choose folder...".
- **Shortcuts** that work in every Anki window (editable in the add-on config):
  `Ctrl+Alt+L` play/pause, `Ctrl+Alt+N` next track, `Ctrl+Alt+Up/Down` volume.
- **Ducking**: while a card's audio or video plays, the music fades down (to 20% by default) and
  comes back afterwards. Works for `[sound:]` audio and for note types that play `<audio>`/`<video>`
  inside the card.
- **Sources**: Chillhop and Lofi Girl (archive.org) from lowfi's tracklists, any lowfi-format `.txt`
  you drop in `user_files/tracklists/`, or your own music folder.
- Remembers volume, source and whether it was playing; stops when Anki closes and resumes on the next start.

Playback uses Qt Multimedia (bundled with Anki's PyQt6), so nothing else needs installing.
Tested on Anki 26.x (Windows).

## Install

Copy this folder into your Anki `addons21` folder as `lofi` and restart Anki.

## Config

See [config.md](config.md): shortcuts, volume step, duck level and fade times, music folder, and the
button's label and playing style.

## License

MIT, see [LICENSE](LICENSE). The bundled tracklists come from lowfi (MIT, see
[tracklists/LICENSE-lowfi](tracklists/LICENSE-lowfi)); the music itself belongs to its artists and is
streamed from Chillhop and archive.org.
