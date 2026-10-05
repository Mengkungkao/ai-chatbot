# Bundled display assets

These files ship with the app so that installing it downloads nothing from
anywhere but this repository's releases. `install_dependencies.sh` and
`tools/build-release.sh` check them against these SHA-256 sums.

| File | What | License |
| --- | --- | --- |
| `NotoSansSC-Bold.ttf` | Noto Sans SC Bold 2.004, the UI font (Latin and Chinese) | SIL Open Font License 1.1, see `OFL-NotoSansSC.txt` |
| `emoji_svg.zip` | Twemoji SVG glyphs, one file per codepoint (`emoji_svg/<codepoint>.svg`) | CC-BY 4.0, see below |

```
a9c048e539c7b8c37573aa0143f4ca33cd5ba85ca186c1e0bc70f94dd75caf93  NotoSansSC-Bold.ttf
d82effaeeca5e41ee4db5c7de4c162662670eac3243279478e281c02e460ab98  emoji_svg.zip
```

Both are byte-identical to the copies the upstream whisplay-ai-chatbot
installer used to download.

The zip is unpacked into `emoji_svg/`, then `face_gen.py` writes the cat faces
over the codepoints it draws, so a face emoji in a reply looks like the face
on screen.

## Twemoji

Emoji graphics: Twemoji, Copyright 2019 Twitter, Inc and other contributors,
licensed under CC-BY 4.0 (https://creativecommons.org/licenses/by/4.0/).
Source: https://github.com/twitter/twemoji. The 49 face codepoints are replaced
by this app's own cat drawings.
