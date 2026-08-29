# Cat illustration

A vector reconstruction of the reference cat, built from cubic Bézier curves
rather than traced from the raster.

```
cat_illustration.py   geometry, the four component functions, SVG + PNG output
compare.py            measures a render against the reference, like for like
cat.svg               the deliverable
cat.png               a raster of the same geometry, used only for measuring
```

## Building

```bash
python3 cat_illustration.py                        # writes cat.svg and cat.png
python3 compare.py ~/Downloads/cats.png cat.png    # checks it against the reference
```

The geometry is defined once as control points at the top of
`cat_illustration.py`. The SVG writer and the PIL rasteriser both read those
same numbers, so the thing being measured is always the thing being shipped.

## Components

`createCatHead()` emits the silhouette as **one** closed path of thirteen cubic
segments. The ears are part of the contour rather than shapes placed on top, and
every junction is a curve, so the outline reads as drawn rather than assembled.

The ear tips are authored as sharp corners and rounded afterwards by `_fillet()`,
which trims both curves back by `EAR_FILLET` and bridges the gap with a cubic
approximating a circular arc. Rounding a tip also shortens it, so `EAR_LIFT`
raises the tips by half the radius to pay for what the fillet removes — without
it the whole drawing loses six pixels of height.

The left ear is the only one authored. The right is derived from it by `_m()`,
mirroring across `AXIS` — the head's own axis of symmetry at x=155, which its
cheeks and chin already share to within a pixel. The two ears therefore cannot
drift apart the way independently measured numbers had: the right one was two
to three pixels wider than the left before this.

`EAR_BOW` offsets the control points of all four ear edges perpendicular to the
edge, away from that ear's own centreline, so both sides of each ear swell
instead of running straight. The offset has to be perpendicular rather than
horizontal: the inner edges are steeply diagonal, and a sideways push slides
along them instead of bowing them.

All three are single constants; set `EAR_FILLET = 0` for sharp tips and
`EAR_BOW = 0` for straight-sided ears.

`createEyes()`, `createMouth()` and `createWhiskers()` emit the features.
Whiskers are drawn before the head so they tuck under its outline.

## Colours

Taken from the reference image itself, not from description:

| part | value | note |
|---|---|---|
| background | `#B7F1FF` | measured; a written spec had said `#B2E8F4` |
| head fill | `#F2F2F2` | matches |
| outline | `#818181` | measured at 128–131 grey; a spec had said `#777777` |
| eyes, mouth | `#575757` | measured at 86–87 grey |

## How close it is

`compare.py` measures both images the same way. Against the reference:

| metric | reference | this | diff |
|---|---|---|---|
| top of drawing | 45 | 45 | 0 |
| bottom | 239 | 239 | 0 |
| valley between ears | 94 | 94 | 0 |
| ear tips | 96.0, 209.5 | 96.0, 213.0 | 3.5 (see below) |
| ear edge bow, outer / inner | −3.3 / +2.6 | −2.8 / +3.4 | <1 |
| width at y=140 | 222 | 224 | +2 |
| width at y=150 | 226 | 228 | +2 |
| width at y=215 | 187 | 184 | −3 |
| width at y=225 | 153 | 152 | −1 |
| eye centres | 87.5, 218.0 | 86.5, 217.5 | ≤1 |
| eye diameter | 30 | 30 | 0 |
| eye spacing | 130.5 | 131.0 | +0.5 |
| mouth centre | 152.5, 186.5 | 153.5, 187.0 | ≤1 |
| mouth size | 48 × 12 | 50 × 13 | ≤2 |

The right ear tip is the one figure that moved away from the reference. The
reference centres its ears on x=152.5, two and a half pixels left of where this
head's body is centred, so an ear pair that is both mirrored *and* centred on
its own head cannot also sit exactly where the reference puts it. Mirroring
about 152.5 instead was measured and scores worse overall (94.1% against
94.5%), because the ears then meet the head's flanks unevenly.

Silhouette overlap with the reference is **94.5%** by intersection over union.
Every figure is within 3px on a 313px canvas.
