# Print Advisor — guide for an LLM working on this codebase

This is a local toolchain for the Elegoo Centauri Carbon / Centauri Carbon 2
(via ElegooSlicer, an Orca/Bambu-family fork). It reads an STL, recommends
print settings based on what the part is for, and can bake those settings
into either a real ElegooSlicer preset or a ready-to-slice project file. All
of this runs locally with plain Python 3 + numpy; no network calls, no
external services.

Read this whole file before editing anything — several of the "obvious"
approaches below were tried, failed against the real app, and the fix is
non-obvious. That history is preserved here so it isn't relearned the hard
way.

## Files

| File | Purpose |
|---|---|
| `print_advisor.py` | Core logic. Reads STL geometry, recommends settings, prints a human-readable report. Has no ElegooSlicer-specific output — just text. |
| `export_elegoo_profile.py` | Converts recommendations into real ElegooSlicer **user preset** files (process + filament) that show up in the slicer's dropdown menus. Imports from `print_advisor.py`. |
| `patch_elegoo_project.py` | Converts recommendations + a new STL into a real ElegooSlicer **project file** (`.3mf`) with the mesh and settings baked in, based on patching a real project file the user saved. Imports from both files above. |
| `PrintAdvisor.applescript` | Source for a macOS drag-and-drop app. Compile with `osacompile -o PrintAdvisor.app PrintAdvisor.applescript`. The compiled `.app` currently lives on the user's Desktop, not in this folder. |
| `base.3mf` | A real ElegooSlicer project file the user saved (printer = Centauri Carbon 2, filament = their calibrated "Deeplee" preset). Used as the patch target by `patch_elegoo_project.py` and the AppleScript app. If the user's printer or default filament changes, this needs to be re-saved from ElegooSlicer. |
| `elegoo_profiles/` | Output directory for `export_elegoo_profile.py` — generated preset `.json`/`.info` pairs land here before being copied into ElegooSlicer's user preset folder. |

## Adding a new `--project` type (e.g. a new part category)

Five places need to change together, in this order:

1. **`print_advisor.py` → `main()`**: the `argparse` `choices=[...]` list on the `--project` argument.
2. **`print_advisor.py` → `recommend()`**: has `if project == 'functional': ... elif project == 'figure': ...` blocks covering Quality/Strength/Speed/Support/Other. Add a branch. This produces the human-readable report values (often as ranges/text, e.g. `"40-60%"`).
3. **`print_advisor.py` → `recommend_orientation()`**: same `if/elif` pattern, for bed-orientation advice text.
4. **`export_elegoo_profile.py` → `slicer_overrides()`**: a **parallel, independent** re-implementation of steps 2-3, but returning real ElegooSlicer/Orca config keys and single numeric/enum values instead of display text (e.g. `"outer_wall_speed": "165"` instead of `"150-180mm/s"`). This is deliberately not derived from `recommend()`'s output by parsing the display strings — it mirrors the same decision logic directly so the mapping to real slicer keys stays exact. If you add a project type to `recommend()`, add the matching branch here too, or the report and the generated files will silently diverge.
5. **`PrintAdvisor.applescript`**: the `choose from list {"functional", "decor", "figure", "test"}` line. Recompile after editing (see command above).

## Adding a new `--material`

Add an entry to the `MATERIALS` dict in `print_advisor.py` (nozzle/bed temp, name, and flags like `abrasive`/`hygroscopic`/`high_temp`/`flexible`/`extreme_temp` which drive notes and nozzle selection elsewhere in `recommend()`).

If you also want `export_elegoo_profile.py` to generate a matching filament
preset, add the material to `FILAMENT_BASES['cc']` and/or `FILAMENT_BASES['cc2']`
— but only with a **verified real ElegooSlicer system filament preset name**
(see the hard-won lessons below on why guessing here is risky). If no real
base exists for that material/printer combo, leave it out; the script
already handles that gracefully (skips filament generation, prints a note).

## Hard-won lessons (read before changing preset/project-file logic)

These were each discovered by shipping something that looked correct, having
the user test it in the real app, and it silently failing. Don't reintroduce
these bugs.

1. **ElegooSlicer's `.3mf`/preset format is undocumented and version-sensitive.**
   User preset JSON files (in `~/Library/Application Support/ElegooSlicer/user/default/{process,filament}/`)
   must declare a `"version"` field matching the *currently installed app
   version* exactly, or the app silently ignores the preset — no error, it
   just doesn't appear in the dropdown. `export_elegoo_profile.py` reads the
   real version out of `~/Library/Application Support/ElegooSlicer/ElegooSlicer.conf`
   (`detect_slicer_version()`) rather than hardcoding one, because a
   hardcoded version will go stale the next time the app updates.

2. **User presets need a companion `.info` file**, not just the `.json`.
   Format: `sync_info = create`, `user_id = `, `setting_id = `, `base_id = <code or blank>`,
   `updated_time = <unix timestamp>`. See `build_info()`.

3. **"Centauri Carbon" (`CC`/`ECC`) and "Centauri Carbon 2" (`CC2`/`ECC2`) are
   different printer families with different system preset names** —
   e.g. `0.20mm Standard @Elegoo CC 0.4 nozzle` vs `...CC2...`. There is
   also a *third*, easily-confused family: plain "Centauri 2" (no Carbon,
   folder/suffix `EC2`/`C2`) — do not conflate `EC2`/`C2` (Centauri 2) with
   `ECC2`/`CC2` (Centauri Carbon 2). Check `PRINTER_BASES` and
   `FILAMENT_BASES` in `export_elegoo_profile.py` before assuming a name
   pattern generalizes.

4. **`.3mf` project files store a fully-flattened ~450-key config**
   (`Metadata/project_settings.config`), not a small diff — it merges
   printer + filament + process settings into one JSON blob. Building one
   from scratch would mean reimplementing ElegooSlicer's entire
   settings-inheritance resolver. `patch_elegoo_project.py` avoids this by
   requiring a real base `.3mf` the user saved from the actual app (which
   guarantees every machine-limit/bed-shape/retraction default is correct)
   and only patching specific keys.

5. **Raw value edits to `project_settings.config` are silently discarded
   unless `different_settings_to_system` also lists the changed keys.**
   This field is a 3-slot `[printer, filament, process]` list of
   semicolon-joined key names that the app treats as the authoritative
   source of "what's actually overridden." A key not listed there gets
   re-resolved from the named system preset on open, even if its raw value
   in the JSON is correct. See `mark_process_diff()`.

6. **Even with (5) fixed, if `print_settings_id` exactly matches a real
   system preset name, ElegooSlicer re-resolves it from its own library on
   open and discards the embedded overrides anyway.** The fix is renaming
   `print_settings_id` to something that can't collide with any known preset
   (`rename_process_preset()`), forcing the app to treat it as a standalone
   modified config it must read from the file. This was confirmed by direct
   testing against the real app — both (5) and (6) were required together;
   neither alone was sufficient.

7. **`.3mf` isn't necessarily associated with ElegooSlicer on a machine that
   also has vanilla OrcaSlicer installed** — both declare the extension with
   `LSHandlerRank = Alternate` (not `Owner`) and neither exports a real UTI,
   so macOS's choice between them is unreliable, and OrcaSlicer doesn't have
   access to ElegooSlicer's user preset library (different app-support
   folders), so filament/process names it can't resolve silently fall back
   to generic system presets. Fixed via Finder → Get Info → Open With →
   Change All (the `duti` CLI tool cannot set a default handler for a
   synthesized "dynamic" UTI — this was tried and fails with error -50).

8. **AppleScript droplet quirks** (`PrintAdvisor.applescript`):
   - Dropping exactly *one* file can hand `on open theFiles` a bare
     alias/string instead of a list containing one item. Iterating over a
     string with `repeat...in` walks it character-by-character. Always
     normalize with `if class of theFiles is not list then set theFiles to {theFiles}`
     before iterating.
   - Calling the bare `open somePath` command *inside a compiled AppleScript
     app that itself defines `on open theFiles`* re-sends the Apple Event to
     itself, recursively re-invoking its own handler, instead of opening the
     file in its default app. Use `do shell script "open " & quoted form of somePath`
     instead.

9. **STL files with all-zero normal vectors are valid** per spec (some
   exporters rely on the reader deriving normals from vertex winding order).
   `print_advisor.py`'s `compute_face_normals()` always derives normals from
   triangle vertices directly and ignores whatever is in the file, rather
   than trusting file normals and silently producing wrong overhang%/
   flattest-face results on such files.

