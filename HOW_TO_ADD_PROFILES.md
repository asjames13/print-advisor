# How to add your own print profile

A "profile" (aka `--project` type) is a named preset like `decor`, `functional`,
`figure`, `test`, or `lamp` — it controls walls, infill, speed, and supports.
This walks through adding a new one, using `lamp` as the worked example
already in the code, so you can copy the pattern.

There are **6 places** to touch. Do them in this order, and test after step 3
before moving on — that's the fastest place to catch a typo.

---

## 1. `print_advisor.py` — register the name

Find this line near the bottom (`main()` function):

```python
parser.add_argument('--project', choices=['decor', 'functional', 'figure', 'test', 'lamp'],
```

Add your new name to that list, e.g. `..., 'lamp', 'coaster']`.

## 2. `print_advisor.py` — orientation advice

Find `recommend_orientation()`. It's a chain of `if project == 'x': ... elif project == 'y': ...`.
Add your own `elif` block before the final `else:` (which is the fallback
for `test`):

```python
elif project == 'yourtype':
    orientation = "One-sentence summary of how to orient it."
    reasons.append(
        "A longer explanation of why — what's the actual physical reason "
        "this orientation matters for this kind of part?"
    )
```

## 3. `print_advisor.py` — the actual settings

Find `recommend()`. It has separate `if/elif` chains for **Quality**,
**Strength**, and **Speed** (Support and Other are usually automatic based on
the part's geometry, not the project type — leave those alone unless your
profile genuinely needs different behavior there).

Add a branch to each of the three chains. Example from the `lamp` profile
(Strength section):

```python
elif project == 'yourtype':
    settings['strength']['Wall loops'] = 3
    settings['strength']['Top/bottom shell layers'] = 4
    settings['strength']['Sparse infill density'] = '20%'
    settings['strength']['Sparse infill pattern'] = 'Gyroid'
    settings['notes'].append("One sentence explaining the reasoning.")
```

**Test now, before continuing:**
```bash
cd ~/claude-workspace/print-advisor
python3 print_advisor.py <any.stl> --project yourtype --material pla
```
Read the report top to bottom. If a section looks wrong or missing, fix it
here before moving to step 4 — steps 4-6 all copy this same logic, so
mistakes here get triplicated.

## 4. `export_elegoo_profile.py` — real slicer settings

This file mirrors step 3, but with real ElegooSlicer key names instead of
display text (e.g. `'wall_loops': '3'` instead of `'Wall loops': 3`). Two
places:

**a)** Find `slicer_overrides()` — same `if/elif` pattern as `recommend()`,
add matching branches for Quality and Strength:
```python
elif project == 'yourtype':
    process['wall_loops'] = '3'
    process['top_shell_layers'] = '4'
    process['bottom_shell_layers'] = '4'
    process['sparse_infill_density'] = '20%'
    process['sparse_infill_pattern'] = 'gyroid'
```

**b)** In the same function, find `speed_by_project = { ... }` — this is a
plain dictionary, so it needs an entry or the script crashes:
```python
'yourtype': ('120-150mm/s', '180mm/s'),
```

**c)** Also add your name to the `--project choices=[...]` line in `main()`
near the bottom of this same file.

## 5. `patch_elegoo_project.py` — register the name

Near the bottom, find:
```python
parser.add_argument('--project', choices=['decor', 'functional', 'figure', 'test', 'lamp'], required=True)
```
Add your name here too.

**Test the full pipeline now:**
```bash
python3 patch_elegoo_project.py base.3mf <any.stl> --project yourtype --material pla --out /tmp/test.3mf
```
Should finish with no errors and list your overridden settings.

## 6. `PrintAdvisor.applescript` — the drag-and-drop app

Find this line:
```applescript
set projectChoice to choose from list {"functional", "decor", "figure", "test", "lamp"} with prompt "What is this part for?" default items {"functional"} without multiple selections allowed
```
Add your name to that list. Then recompile (this step is required — editing
the `.applescript` file alone does nothing until you rebuild the `.app`):
```bash
rm -rf ~/Desktop/PrintAdvisor.app
osacompile -o ~/Desktop/PrintAdvisor.app ~/claude-workspace/print-advisor/PrintAdvisor.applescript
```

---

## Committing and pushing

Once everything above tests clean:

```bash
cd ~/claude-workspace/print-advisor
git status                              # sanity check what actually changed
git add -A
git commit -m "Add <yourtype> profile"
git push origin main
```

**This repo is public** (`github.com/asjames13/print-advisor`). Anyone can
see the code, the commit history, and your commit messages. Keep that in
mind when naming things and writing commit messages.

If `git push` ever fails with an auth error, run:
```bash
gh auth status        # confirm you're still logged in
gh auth setup-git      # re-wires git to use that login
```

## Checklist

- [ ] `print_advisor.py` — added to `--project choices`
- [ ] `print_advisor.py` — `recommend_orientation()` branch
- [ ] `print_advisor.py` — `recommend()` branches (Quality, Strength, Speed)
- [ ] Tested with `python3 print_advisor.py ...` — report looks right
- [ ] `export_elegoo_profile.py` — `slicer_overrides()` branch
- [ ] `export_elegoo_profile.py` — `speed_by_project` dict entry
- [ ] `export_elegoo_profile.py` — added to `--project choices`
- [ ] `patch_elegoo_project.py` — added to `--project choices`
- [ ] Tested with `python3 patch_elegoo_project.py ...` — no errors
- [ ] `PrintAdvisor.applescript` — added to the `choose from list`
- [ ] Recompiled the app with `osacompile`
- [ ] `git add -A && git commit -m "..." && git push origin main`
