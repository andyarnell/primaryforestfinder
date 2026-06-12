# Input labelling + FRA framing — review for sign-off

**Date:** 2026-05-11
**Status:** Proposed (awaiting colleague review)
**Affects:** GEE app (`pff_4.js`) + QGIS plugin

---

## Problem

Two coupled UX issues with how the PFF tools handle the raw forest / tree-cover input:

1. **Input is invisible when FRA-aligned is OFF.** The GEE app currently gates the input layer's map visibility and stats row on whether the user picked a category from the FRA dropdown. When the FRA-aligned checkbox is unchecked, the dropdown is hidden, no category is set, and the user sees only the final Primary forest output — not the raw input they fed in. The QGIS plugin has the same gap: `forest_raw` is computed and used for zonal stats but never appears as a map layer.

2. **"FRA-aligned" as a separate checkbox duplicates the dropdown.** The user is currently asked two questions ("are you FRA-aligned?" + "which FRA category?"). These collapse cleanly into one optional question: *"do you want to refine your input by FRA category?"*

## Proposed scheme

Drop the FRA-aligned checkbox entirely. Move the dropdown + refinement toggles into a collapsible subsection inside §2 (Tree Cover Input), **closed by default**. The dropdown becomes the single gate for surfacing intermediate FRA layers (Forest, NRF) in the map and stats.

### §2 layout, collapsed (default)

```
§2 Tree Cover Input
┌─ Tree-cover input definition ─────────────────────────┐
│  Source:    [GLAD / Hansen ▾]                         │
│  Threshold: [─────●────] 5m         (GLAD only)       │
│  Canopy %:  [10/30/50 ▾]            (Hansen only)     │
│  Input raster: [file picker]                          │
└───────────────────────────────────────────────────────┘

▶ Refine input (optional)
```

### §2 expanded

```
▼ Refine input (optional)

  FRA category (for naming + surfacing intermediates):
        [— Select one — ▾]
        │  Tree cover (FRA cascade entry)
        │  Forest (FRA category)
        │  Naturally regenerating forest (FRA)
        │  Primary forest (FRA)
  
  ☐ Exclude OLTC (oil palm / orchards / agroforestry)
  ☐ Exclude planted forest
```

When an FRA category is declared, each toggle gets an inline helper line showing it also creates an intermediate layer:

```
[Tree cover ▾]
☑ Exclude OLTC (oil palm / orchards / agroforestry)
   ↳ creates "Forest" intermediate layer
☑ Exclude planted forest
   ↳ creates "Naturally regenerating forest" intermediate layer
```

The `↳ creates…` lines appear only when a category is declared. Without a declaration the helper lines disappear — the toggles still affect processing, but no intermediate layer is created.

## Core rule

**The dropdown is the single gate for creating intermediate layers.** Toggles are always independent and always interactive — no disabled states, no cascade-order enforcement. An intermediate layer (Forest, NRF) is created only when the corresponding exclusion ran AND that intermediate maps to a valid FRA category given the declaration.

| Dropdown | OLTC | Planted | Map layers / stats rows | Footer text |
|---|:---:|:---:|---|---|
| (empty) | ☐ | ☐ | `Input`, `Primary forest` | *"Input: no FRA declaration. No exclusions applied."* |
| (empty) | ☑ | ☐ | `Input`, `Primary forest` | *"Input: no FRA declaration. Primary forest computed with OLTC excluded."* |
| (empty) | ☑ | ☑ | `Input`, `Primary forest` | *"Input: no FRA declaration. Primary forest computed with OLTC + planted excluded."* |
| Tree cover | ☑ (auto) | ☑ (auto) | `Tree cover`, `Forest`, `Naturally regenerating forest`, `Primary forest` | *"Input declared as Tree cover (FRA cascade). Exclusions: OLTC, planted."* |
| Tree cover | ☑ | ☐ (override) | `Tree cover`, `Forest`, `Primary forest` | *"Input declared as Tree cover. Exclusion: OLTC. Planted: overridden OFF."* |
| Forest | — | ☑ (auto) | `Forest`, `Naturally regenerating forest`, `Primary forest` | *"Input declared as Forest (FRA). Exclusion: planted."* |
| NRF | — | — | `Naturally regenerating forest`, `Primary forest` | *"Input declared as NRF (FRA). No exclusions."* |
| Primary | — | — | `Primary forest` | *"Input declared as Primary (FRA). No exclusions."* |

Two paths to FRA-aligned Primary forest:
- **Path A — declare a category.** Cascade visible. *(workshop happy path)*
- **Path B — tick toggles only.** Same processing, only Input + Primary surfaced. *("just the headline")*

## CSV columns

`{lowercase_layer_name}_kha`. So `input_kha`, `tree_cover_kha`, `forest_kha`, `nrf_kha`, `primary_forest_kha`. The CSV column set matches the map-layer set. `primary_forest_kha` is always present (the headline output).

## Declared vs not declared — visible in the layer name itself

- `Input` in the Layers panel ⇒ user didn't declare (subsection collapsed or dropdown empty).
- `Forest` / `Tree cover` / `Naturally regenerating forest` / `Primary forest` ⇒ user declared that category.

No suffix or badge needed. The label IS the indicator.

## Footer disclosure (audit trail)

Every run produces a one- or two-line footer summarising what happened, in all of:

- GEE stats panel (`ui.Label` below the table)
- GEE CSV export (comment header line)
- GEE run_metadata GeoJSON sidecar (structured fields)
- GEE pre-export confirmation (console message before queuing)
- QGIS area-stats CSV (comment header line)
- QGIS dock log (one-line summary at run completion)

The footer makes the user's choices explicit, so a colleague opening the CSV six months later knows what processing was applied without needing to read the metadata JSON.

## Why it's better

- **Drops one UI concept.** Two questions become one optional question.
- **Default-collapsed subsection** means new users never engage with FRA terminology unless they choose to.
- **Layer / CSV names self-describe** declared vs not declared — no suffix, no badge.
- **No-FRA pathway always 2 rows / 2 layers** regardless of toggles. Stable, predictable.
- **Toggles still useful** for users who want refinement but not FRA framing.
- **Power-user override** preserved — pick a category then untick a toggle to skip part of the cascade.
- **Workshop guidance delivered verbally** by the facilitator (and optionally noted in the participant task doc) — keeps UI clean.

## Trade-offs / known costs

- **Workshop users must expand the subsection + pick Tree cover to see the FRA cascade.** Facilitator says this verbally on the day; no UI hint.
- **QGIS CSV breaking rename.** Today's `forest_kha` column actually contains the raw input (tree_cover_binary). Under the new scheme:
  - `forest_kha` is reserved for the post-OLTC Forest cascade layer (matching GEE's existing convention)
  - The raw input becomes `input_kha` (no declaration) or `tree_cover_kha` (Tree cover declared)
  - Downstream scripts reading the old `forest_kha` column will need to update.
- **Soft warning may feel noisy** if users habitually disable the agriculture buffer.

## Height threshold + source behaviour

- **GLAD:** user-configurable height slider, default 5m (FRA). Can go lower (3m, 2m for countries like Bhutan/Nepal or Bangladesh) or higher. Backed by GLAD's continuous `glad_tree_height_raw` layer.
- **Hansen:** vegetation ≥5m baked in at source (Hansen et al. 2013). The configurable axis is canopy % (10/30/50), not height. Hansen data cannot be re-thresholded below 5m.
- The §2 group box swaps widgets based on source choice: height slider when GLAD, canopy % when Hansen.

## Soft warning for missing agriculture buffer

When the subsection is collapsed (no FRA refinement) AND any of (Agriculture, Built-up small, Built-up large) layers are missing OR have their buffer disabled, surface a warning before run:

> ⚠️ Your input is processed without FRA's OLTC exclusion. Oil palm / orchards / agroforestry in your input may survive into the Primary forest output unless removed by §3's human-influence buffers. You haven't provided an agriculture layer (or have buffer disabled) — consider adding one, or expanding "Refine input" and picking "Tree cover".

For the common workshop case (GEE batch export with agriculture layer present and buffer enabled), this fires silently and the run proceeds. The warning only appears on the genuinely risky combinations.

## Backward compatibility for saved settings

`*_run_metadata.json` / saved settings files from version 0.15.x need to load correctly under the new scheme:

| Saved value | New state |
|---|---|
| `TREE_COVER_MODE: "simple"` | Subsection collapsed; dropdown empty |
| `TREE_COVER_MODE: "fra"` + `INPUT_CATEGORY: "Tree cover…"` | Subsection expanded; Tree cover picked |
| `TREE_COVER_MODE: "fra"` + `INPUT_CATEGORY: "Forest…"` | Forest picked |
| `TREE_COVER_MODE: "fra"` + `INPUT_CATEGORY: "Naturally regenerating forest…"` | NRF picked |
| `TREE_COVER_MODE: "fra"` + `INPUT_CATEGORY: "Primary forest…"` | Primary picked |
| Old `FRA-aligned` boolean | Ignored on load — derived from `INPUT_CATEGORY` |

`EXCLUDE_AGRICULTURE_FROM_FOREST` and `EXCLUDE_PLANTATIONS` toggle states restore directly.

## Sections that don't change

§3 Human Influence, §4 Refine Output (connectivity filter), §5 Area Stats, §6 Outputs, Config — all unchanged.

## Worked example — Bhutan run

### Default (subsection collapsed)

Map: `Input`, `Primary forest` (2 layers).
Stats:
```
Input               4,250 kha
Primary forest      1,820 kha
ℹ Input: no FRA declaration. No exclusions applied.
```

### Workshop happy path (Tree cover declared)

Map: `Tree cover`, `Forest`, `Naturally regenerating forest`, `Primary forest` (4 layers).
Stats:
```
Tree cover                         4,250 kha
Forest                             3,910 kha
Naturally regenerating forest      3,640 kha
Primary forest                     1,540 kha
ℹ Input declared as Tree cover (FRA cascade). Exclusions: OLTC, planted.
```

### "Just the headline" (toggles ticked, dropdown empty)

Map: `Input`, `Primary forest` (still 2 layers — no intermediates surfaced).
Stats:
```
Input               4,250 kha
Primary forest      1,540 kha
ℹ Input: no FRA declaration. Primary forest computed with OLTC + planted excluded.
```

Note: Primary forest number matches the workshop-path result (1,540 kha) because the same processing ran — only the surfacing differs.

## Open questions for review

1. **Soft-warning trigger conditions.** Current proposal fires when agriculture buffer is missing or disabled. Should it also fire on missing built-up layers? Too noisy?
2. **Acceptable to break the `forest_kha` column in QGIS CSV?** No deprecation period — old `forest_kha` (= input) becomes new `forest_kha` (= post-OLTC Forest layer). Anyone with downstream scripts needs to update.
3. **Workshop guidance channel.** The "pick Tree cover for GEE 02a_tree_cover_binary" instruction is delivered verbally by the facilitator (and optionally noted in the participant task doc), not as a UI hint. Confirm this is the right channel.
4. **Toggle visibility when subsection expanded but no declaration.** Currently both toggles always visible. Alternative: hide toggles unless dropdown has a selection (forces declaration first). Preference?
5. **Anything missed.** Sanity-check the behaviour table against your mental model.

## References

- [FRA 2025 Terms and Definitions (FAO Working Paper 194)](https://openknowledge.fao.org/server/api/core/bitstreams/a6e225da-4a31-4e06-818d-ca3aeadfd635/content)
- [FRA Terms and definitions (live)](https://fra-data.fao.org/definitions/fra/2020/en/tad)
- Hansen et al. 2013, *High-Resolution Global Maps of 21st-Century Forest Cover Change*
