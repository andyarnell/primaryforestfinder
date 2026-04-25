# GitHub Issue: Align `pFF_4` Workflow with QGIS Plugin

## Summary
The QGIS plugin workflow is now functioning well and produces a reconnect activity filter / primary forest candidate layer that is very similar to the output from `pFF_4`, aside from some expected differences in buffering extent.

The next step is to fully align `pFF_4` and the QGIS plugin in terms of:

- processing logic
- exported layers
- naming conventions
- validation scripts
- projection handling
- optional zonal statistics outputs

---

## Problem

Current inconsistencies include:

- Different export sets between `pFF_4` and the plugin
- Missing export options for some vector inputs, especially roads
- DEM and slope exports are not handled consistently
- Validation scripts in the HS plugin do not match the exported layer types
- Output naming differs between workflows
- Too many unnecessary exports can appear in the Tasks tab
- No clear handling of reprojection to an appropriate UTM CRS
- No optional combined raster output representing the main workflow stages
- Zonal statistics functionality exists in `pFF_4` but not yet in the QGIS plugin

---

## Proposed Changes

### 1. Review and Compare Current Workflows
#### Task
Review `pFF_4` and the QGIS plugin and document differences in:

- buffering logic
- intermediate layers
- exported outputs
- naming conventions
- validation assumptions
- zonal statistics behaviour

#### Acceptance Criteria
- A short comparison document is produced
- Any mismatches are identified and prioritised

---

### 2. Add Selective Export Controls
#### Task
Add export flags / tick boxes so users can choose which layers to export.

Suggested export groups:

- Core outputs
- Intermediate raster outputs
- Intermediate vector outputs
- Validation-supporting layers

Example options:

```text
[ ] Export final primary forest candidate layer
[ ] Export pre-connectivity layer
[ ] Export input forest layer
[ ] Export roads vector
[ ] Export buffered roads vector
[ ] Export other input vectors
[ ] Export DEM
[ ] Export slope
[ ] Export natural protection layer
[ ] Export all intermediate layers
```

#### Acceptance Criteria
- Only selected layers are exported
- Processing time is reduced when unnecessary exports are disabled
- Tasks tab is less cluttered

---

### 3. Add Missing Vector Exports
#### Task
Ensure vector layers used in the workflow can optionally be exported.

Priority layers:

- roads
- buffered roads
- other anthropogenic input vectors
- protected areas
- natural protection polygons

#### Acceptance Criteria
- Roads can be exported from `pFF_4`
- Vector exports match those available in the plugin
- Export names follow the agreed `pFF_4` naming convention

---

### 4. Align DEM and Slope Export Behaviour
#### Task
Review how DEM and slope are currently generated and exported.

Questions to resolve:

- Is only DEM currently exported for natural protection?
- Should slope always be exportable as well?
- Should both be available through export tick boxes?

#### Acceptance Criteria
- DEM and slope export behaviour is consistent across workflows
- Both can be optionally exported

---

### 5. Add Projection Handling
#### Task
Add an option to reproject exported outputs to an appropriate UTM zone.

Suggested option:

```text
[ ] Reproject exports to local UTM zone
```

Possible approaches:

- `pFF_4` determines the correct UTM zone automatically from the AOI centroid
- OR the QGIS plugin detects and reprojects layers on import if needed

#### Acceptance Criteria
- Exported rasters and vectors are in a consistent and suitable CRS
- Projection handling is documented and consistent between workflows

---

### 6. Align Naming Conventions to `pFF_4`
#### Task
Match output names in the plugin to the existing `pFF_4` naming convention.

Examples:

```text
input_forest
forest_outside_buffers
pre_connectivity_forest
primary_forest_candidate
roads_vector
roads_buffered_vector
natural_protection
dem
slope
```

#### Acceptance Criteria
- Equivalent outputs have the same names in `pFF_4` and the plugin
- Output names are predictable and easier to compare across workflows

---

### 7. Add Optional Combined Raster Output
#### Task
Assess whether multiple workflow stages can optionally be combined into a single coded raster.

Suggested coding:

```text
0 = no forest
1 = input forest
2 = forest outside buffers / pre-connectivity forest
3 = final primary forest candidate
```

Potential extension if additional stages are useful:

```text
4 = connectivity-filtered forest
5 = protected-area-filtered forest
```

This should be optional alongside separate raster exports.

Suggested option:

```text
[ ] Export combined coded raster
```

#### Acceptance Criteria
- Users can choose between separate raster outputs and a single coded raster
- Raster class values are documented
- Combined raster is compatible with validation workflows

---

### 8. Add Optional Zonal Statistics to the QGIS Plugin
#### Task
Add zonal statistics functionality to the QGIS plugin equivalent to the functionality already available in `pFF_4`.

This should be optional rather than always enabled.

Suggested option:

```text
[ ] Run zonal statistics
```

Potential additional options:

```text
Zone layer: [dropdown]
Statistic fields:
    [ ] Area by class
    [ ] Percent by class
    [ ] Forest area
    [ ] Primary forest candidate area
    [ ] Combined raster class counts
Output format:
    [ ] CSV
    [ ] Vector layer attributes
```

The zonal statistics should work with:

- separate raster outputs
- the optional combined coded raster
- exported vector layers where relevant

Where possible, the outputs and field names should match those already produced in `pFF_4`.

#### Acceptance Criteria
- The QGIS plugin can optionally produce the same zonal statistics outputs as `pFF_4`
- Field names and output structure align with `pFF_4`
- Zonal statistics can be generated directly from the plugin without requiring external scripts

---

### 9. Align Validation Scripts
#### Task
Update the HS plugin validation scripts so they match the actual outputs exported from `pFF_4` and the plugin.

Validation should support:

- final raster outputs
- intermediate raster outputs
- exported vector layers
- combined coded raster if implemented
- zonal statistics outputs

#### Acceptance Criteria
- Validation scripts work directly with exported outputs
- No manual renaming or format conversion is required

---

### 10. Additional Alignment Recommendations
#### Task
Review both workflows and suggest further opportunities to align:

- buffering methods
- export defaults
- intermediate layer generation
- CRS assumptions
- validation logic
- naming patterns
- zonal statistics structure

#### Acceptance Criteria
- Additional recommendations are documented
- Future maintenance is simpler because both workflows follow the same structure

---

## Deliverables

- Workflow comparison between `pFF_4` and the QGIS plugin
- Proposed aligned export structure
- Proposed naming convent