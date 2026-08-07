# Lamp profile (vase mode) — design

**Date:** 2026-08-07
**Status:** Approved by Anthony (restore lamp + spiral/vase mode; no changes to existing profiles)

## Goal

Add a `lamp` project type for lamp shades, based on the previously-shipped lamp
profile from commit `6cfbe98`, upgraded to use spiral (vase) mode. Purely
additive: decor, functional, figure, test, and structure keep their settings
exactly as they are.

Also fix one stale list: `export_elegoo_profile.py`'s `--project` argparse
choices currently list `lamp` (no logic behind it — selecting it crashes with a
`KeyError` in `speed_by_project`) and omit `structure` (logic exists but can't
be selected). Correct the list to match the code. No profile settings change.

## Lamp profile settings

| Area | Report (`print_advisor.py`) | Export (`export_elegoo_profile.py`) |
|---|---|---|
| Layer height | 0.16mm (smoother light diffusion) | `layer_height: 0.16` |
| First layer | 0.2mm | `initial_layer_print_height: 0.2` |
| Spiral/vase mode | Recommended, with applicability note | `spiral_mode: 1` |
| Walls | 1 (single continuous perimeter) | `wall_loops: 1` |
| Top shells | 0 (open top) | `top_shell_layers: 0` |
| Bottom shells | 3 (solid base) | `bottom_shell_layers: 3` |
| Infill | 0% (hollow shell) | `sparse_infill_density: 0%` |
| Seam | N/A — spiral mode has no layer seam | (seam key untouched; irrelevant in spiral mode) |
| Outer wall speed | 80–100mm/s (even extrusion = even glow) | `outer_wall_speed: 90` |
| Infill speed | N/A (no infill) | `sparse_infill_speed: 90` (unused, key must exist) |
| Supports | Off — incompatible with spiral mode | `enable_support: 0` (forced, skips overhang check) |
| Ironing | No ironing | (default, lamp not in ironing branch) |

**Orientation:** opening/base face down, standing upright — even wall thickness
top to bottom; printing on its side causes visible banding in transmitted light.

**Report notes to include:**
- Vase mode requires a single open-top shell — one continuous outline per
  layer, no separate islands, no closed top. If the shade has double walls or
  bridging geometry, turn spiral mode off in-slicer (profile still works as a
  2-wall hollow shell — but walls default back to 1, so bump to 2 manually).
- Spiral mode cannot use supports; overhangs steeper than ~45° will droop.
- If the design needs a solid mount for a bulb socket, handle it in-slicer
  with a modifier rather than infilling the whole part.

## Files to change (per AGENTS.md, five places + docs)

1. `print_advisor.py` — `--project` choices: add `lamp`
2. `print_advisor.py` — `recommend()`: lamp branches in Quality/Strength/Speed/Support + notes
3. `print_advisor.py` — `recommend_orientation()`: lamp branch
4. `export_elegoo_profile.py` — `slicer_overrides()`: lamp branches with real
   Orca keys (table above); argparse choices fixed to
   `['decor', 'functional', 'figure', 'test', 'structure', 'lamp']`
5. `PrintAdvisor.applescript` — add `"lamp"` to `choose from list`; recompile
   with `osacompile` (compiled app lives on the Desktop, not in repo)
6. `patch_elegoo_project.py` — argparse choices: add `lamp` (logic flows
   through `slicer_overrides()` automatically)
7. `README.md` — add lamp row to the project-types table

## Error handling / edge cases

- Support logic: lamp must force supports **off** even when `overhang_pct > 5`
  (spiral mode is incompatible with supports). Both `recommend()` and
  `slicer_overrides()` need this carve-out — the existing overhang-driven
  support block must not fire for lamp.
- Flexible-material wall bump (`wall_loops >= 3` for TPU) conflicts with vase
  mode's single wall. Lamp keeps `wall_loops = 1` and instead adds a note that
  TPU vase prints are possible but walls stay single.
- The old lamp had 2 walls / 0 bottom shells; this version is 1 wall / 3
  bottom shells because spiral mode needs a solid base and prints one
  perimeter. This is intentional, not drift.

## Verification

- `python3 -m py_compile` on all three scripts
- Generate a simple open-cylinder STL in the scratchpad; run
  `print_advisor.py --project lamp` and `export_elegoo_profile.py --project lamp`
  end-to-end; confirm the generated process preset contains `spiral_mode: 1`
  and the lamp keys above
- Regression: run one existing profile (e.g. `--project structure` via export,
  previously unselectable) to confirm the argparse fix works and other
  profiles' output is unchanged
- Recompile the AppleScript and confirm it compiles cleanly
