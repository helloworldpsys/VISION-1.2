# Recording the demo GIF

The README shows `docs/demo.gif`, which is currently a 1×1 placeholder. Replace
it with a short screen recording so visitors see the product in the first few
seconds.

## What to show (10 seconds, one take)

1. **0–2 s** — Terminal with `python -m vision` running and the line
   `Idle. Clap twice`.
2. **2–4 s** — Two real claps; the holographic window appears.
3. **4–7 s** — Say a visible command (e.g. “open YouTube”); the hologram turns
   red while Vision speaks, then back to blue.
4. **7–10 s** — The browser opens YouTube (or show a screenshot being saved).

Keep the desktop clean: no notifications, personal filenames, tokens, or
browser profiles. Crop to the terminal plus the hologram window.

## Recording

| OS | Tool | Notes |
|---|---|---|
| Windows | [ScreenToGif](https://www.screentogif.com/) | Record at 1280×720, 12–15 fps, then export GIF. |
| macOS | [Kap](https://getkap.co/) | 1280×720, 30 fps recording, export at 12–15 fps. |
| Linux | [Peek](https://github.com/phw/peek) or GNOME Screencast | 1280×720, 10–15 fps. |
| Any | `ffmpeg` | Record MP4, then convert (below). |

Run the interface alone while framing the shot:

```bash
python -m vision --test-interface   # press Enter to close
```

## Convert and shrink (cross-platform)

```bash
ffmpeg -i demo.mp4 \
  -vf "fps=12,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  -loop 0 docs/demo.gif
```

Target **under 8 MB**; GitHub renders large GIFs slowly.

## Finish

1. Save the file as `docs/demo.gif` (overwrite the placeholder).
2. Keep the existing `<img>` tag and `alt` text in `README.md`; delete the
   `<!-- TODO: record ... -->` comment.
3. Confirm the README renders on GitHub before merging.
