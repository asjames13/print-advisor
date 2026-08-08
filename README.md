# Print Advisor

A settings advisor for the Elegoo Centauri Carbon / Centauri Carbon 2, built for
Elegoo Slicer (Orca-based). Reads an STL file's geometry and recommends nozzle,
material temps, and full Quality/Strength/Speed/Support/Other tab settings based
on what the part is for.

## Requirements

- Python 3 (already installed on macOS)
- numpy

Install numpy:
```bash
pip3 install numpy --break-system-packages
```

If you use `patch_elegoo_project.py` (bundles an STL + recommended settings into
a real ElegooSlicer `.3mf` project file), you'll also need:
```bash
pip3 install defusedxml --break-system-packages
```

## Usage

```bash
python3 print_advisor.py <path-to-file.stl> --project TYPE --material MATERIAL
```

**Example:**
```bash
python3 print_advisor.py ~/Downloads/my_letter.stl --project decor --material pla
```

There's no "upload" step — just point the script at the file path on your own
machine. Wherever the STL already lives (Downloads, a project folder, wherever),
that's the path you pass in.

## Project types (`--project`)

| Type | Use for | Priority |
|---|---|---|
| `decor` | Bubble letters, wall panels, display pieces | Finish quality, warp prevention |
| `functional` | Gym brackets, pulleys, mechanical/load-bearing parts | Strength, wall count, load-direction orientation |
| `figure` | Action figures, articulated joints, organic sculpts | Detail, joint/peg strength |
| `test` | Quick calibration or throwaway test prints | Speed, minimal material use |
| `structure` | Max-strength brackets, high-stress structural parts | 8 walls, 100% infill, slow speeds |
| `lamp` | Lamp shades, light diffusers | Spiral/vase mode, hollow single-wall shell, even light diffusion |

## Materials (`--material`)

| Key | Material | Notes |
|---|---|---|
| `pla` | Basic PLA | Default, no special handling |
| `pla_plus` | PLA+ / Rapid PLA+ | Slightly higher temp |
| `petg` | PETG | Higher temp/bed |
| `petg_cf` | PETG-CF / Nylon-CF | Abrasive — hardened nozzle only |
| `tpu` | TPU (flexible) | Slower speeds, more walls, direct-drive preferred |
| `paht_cf` | PAHT-CF | High-temp, hygroscopic (dry before use), abrasive |
| `ppa_cf` | PPA-CF | High-temp, hygroscopic, abrasive |
| `pa12_cf` | PA12-CF | High-temp, hygroscopic, abrasive |
| `pa6_cf` | PA6-CF | High-temp, hygroscopic, abrasive |
| `pps_cf` | PPS-CF | Very high-temp — may exceed stock hotend's ~350°C ceiling, script will warn |

## What the report includes

- **Geometry read**: dimensions, volume, triangle count, flattest face, estimated
  overhang %, whether it fits the 256×256×256mm build volume
- **Nozzle recommendation**: sizing based on project type, forced to hardened
  steel for abrasive materials
- **Orientation guidance**: how to place the part on the bed for best rigidity
  (functional parts prioritize load direction across layer lines; figures
  prioritize joint/peg strength; decor prioritizes flattest stable face and
  keeping the visible side away from supports)
- **Full settings** across Quality, Strength, Speed, Support, and Other tabs,
  matching Elegoo Slicer's actual tab layout
- **Notes**: anything geometry- or material-specific worth flagging (warping
  risk on large flat parts, drying requirements, hotend temp ceiling warnings,
  bed-fit issues)

## Notes on accuracy

- Overhang % is calculated from the STL's **as-uploaded orientation**, not
  necessarily the orientation you'll actually print in. Re-check after you
  rotate the part in-slicer.
- Flat-face detection is a rough geometric estimate (percentage of surface
  area facing each of the 6 cardinal directions). Organic/sculpted parts often
  don't have a strong flat face — the script will say so rather than force a
  bad recommendation.
- This tool gives starting-point settings, not a substitute for watching your
  first layer and adjusting from there.
- Face normals used for flat-face and overhang detection are **recomputed
  from each triangle's vertices**, not read from the file. Some STL exporters
  write all-zero normal vectors and rely on the reader to derive them from
  vertex winding order — trusting the file's normals directly would silently
  produce a 0% overhang / arbitrary flattest-face result on those files.

## Extending it

The rule logic lives in `recommend()` and `recommend_orientation()` inside
`print_advisor.py`. To add a new project type or material, add an entry to the
`MATERIALS` dict or a new branch in the relevant `if project == ...` block.

See **`AGENTS.md`** in this folder for the full picture: which of the five
files need to change together for a new project type, and a list of
non-obvious ElegooSlicer/`.3mf` behaviors that were discovered by trial and
error against the real app (version-string matching, preset diff-tracking,
printer-family naming, AppleScript droplet quirks, etc). Worth reading before
touching `export_elegoo_profile.py` or `patch_elegoo_project.py` — several
"obviously correct" approaches there were tried and silently failed.
