# Connectivity & Fragmentation Methods in PFF

This document summarizes the various approaches for filtering forest patches and analyzing fragmentation implemented in this repository.

---

## Overview

| File | Purpose | Key Methods |
|------|---------|-------------|
| `pff.js` | Main app | Kernel density smoothing |
| `pff_connectivity.js` | Full module | Morphological ops + patch area filtering |
| `pff_connectivity_simple.js` | Simplified module | Patch area filtering (auto-selects best method) |
| `pff_cepi.js` | CEPI classification | Core-Edge-Periphery zones (Theobald approach) |

---

## 1. Kernel Density Smoothing (`pff.js`)

**Location:** Lines 1437-1449 in `pff.js`

**Approach:** Calculate local forest density using a circular kernel, then threshold to find "dense" forest areas.

```javascript
var boxcar = ee.Kernel.circle({radius: smoothRadiusForest, units: 'meters', normalize: true});
var density = forest.reduceNeighborhood({
  reducer: ee.Reducer.sum(),
  kernel: ee.Kernel.circle({radius: smoothRadiusForest, units: 'meters'}),
  skipMasked: false
});
var largeForestPatches = density.gt(smallPixelThresholdForest).updateMask(forest);
```

**Parameters:**
- `smoothRadiusForest`: Kernel radius (default 2000m)
- `smallPixelThresholdForest`: Density threshold (0-1)

**Pros:**
- Very fast (purely raster-based)
- Finds "chunky" interior areas, not just large patches
- Works globally without geometry limits

**Cons:**
- Doesn't measure actual patch area
- Threshold is abstract (not in hectares)

**Use case:** Quick visualization of intact forest cores

---

## 2. Morphological Operations (`pff_connectivity.js`)

**Location:** Lines 26-115 in `pff_connectivity.js`

**Approach:** Use focal_min/focal_max to erode and dilate binary masks.

### Functions:

| Function | Operation | Effect |
|----------|-----------|--------|
| `erode(mask, radiusM)` | focal_min | Shrinks forest (removes thin features) |
| `dilate(mask, radiusM)` | focal_max | Expands forest (fills gaps) |
| `open(mask, radiusM)` | erode → dilate | Removes thin connections, smooths edges |
| `close(mask, radiusM)` | dilate → erode | Fills small holes/gaps |
| `morphologicalClean(mask, erodeR, dilateR)` | Custom erode → dilate | Flexible cleaning |

**Use case:** Pre-cleaning anthropogenic layers or forest edges before analysis

---

## 3. Patch Area Filtering - Connected Components

### 3a. Basic Connected Components (`pff_connectivity.js` & `pff_connectivity_simple.js`)

**Approach:** Label connected patches, calculate area, filter by minimum.

```javascript
var components = mask.connectedComponents({
  connectedness: ee.Kernel.plus(1),
  maxSize: 1024  // GEE hard limit
});
```

**Limit:** `maxSize: 1024` = max ~92 hectares at 30m resolution

### 3b. Pixel Count with Inverted Logic (`pff_connectivity_simple.js`)

**Function:** `filterByAreaPixelCount(mask, minHa)`

**Approach:** Use `connectedPixelCount` with inverted logic to handle the 1024 pixel cap.

```javascript
// Remove patches DEFINITELY < threshold (count < threshold AND count < cap)
// Keep everything else (including capped large patches)
var isDefinitelySmall = pixelCount.lt(minPixelCount).and(pixelCount.lt(maxSize));
return mask.updateMask(isDefinitelySmall.not());
```

**Why inverted logic?**
- `connectedPixelCount` caps at 1024 pixels
- A 1000ha patch shows as 1024 (capped)
- If we said "keep if count >= 500ha" → 1000ha patch incorrectly removed
- Instead: "remove if DEFINITELY < 500ha" → 1000ha patch correctly kept

**Pros:** Fast, resolution-independent
**Cons:** Max accurate threshold ~92ha at 30m

---

## 4. Patch Area Filtering - Vector (`pff_connectivity.js` & `pff_connectivity_simple.js`)

**Functions:** 
- `filterByAreaVector(mask, minHa, geometry, options)`
- `filterByPatchAreaVector(mask, minHa, options)`

**Approach:** Convert raster to polygons, calculate true geodesic area, filter, rasterize back.

```javascript
var patches = mask.reduceToVectors({geometryType: 'polygon', ...});
var withArea = patches.map(f => f.set('area_m2', f.geometry().area()));
var large = withArea.filter(ee.Filter.gte('area_m2', minM2));
return large.reduceToImage(['zone'], ee.Reducer.first());
```

**Pros:**
- No area limit (any threshold)
- Accurate geodesic area calculation

**Cons:**
- Slower than raster methods
- Memory limits for very large geometries (~35k patches)

---

## 5. Patch Area Filtering - Tiled (`pff_connectivity_simple.js`)

**Function:** `filterByAreaTiled(mask, minHa, geometry, options)`

**Approach:** Split large geometry into grid tiles, process each with buffer to avoid edge effects, use centroid to assign patches to one tile only.

```
┌─────────┬─────────┐
│  Tile A │  Tile B │     Patch X spans boundary
│    ┌────┼────┐    │     Buffer captures full patch in both tiles
│    │  X │    │    │     Centroid in Tile A → only Tile A keeps it
│    └────┼────┘    │     
└─────────┴─────────┘
```

**Parameters:**
- `gridScale`: Tile size (default 100km)
- `buffer`: Buffer around tiles (default 10km)
- `scale`: Vectorization scale (default 100m)

**Pros:**
- Handles any geometry size
- Accurate area measurement

**Cons:**
- More complex, slower

---

## 6. Smart Auto-Selector (`pff_connectivity_simple.js`)

**Function:** `filterByArea(mask, minHa, geometry, options)`

**Decision Logic:**
```
┌─────────────────────────────────────────────────────────────────┐
│ Threshold ≤ 92ha?                                               │
│   YES → pixelCount (fast, accurate)                             │
│   NO  → Need geometry                                           │
│         ├─ Geometry ≤ 1M ha? → vector (accurate)                │
│         └─ Geometry > 1M ha? → tiled (handles scale)            │
└─────────────────────────────────────────────────────────────────┘
```

**Use case:** Single function that auto-selects the best method based on inputs.

---

## 7. CEPI Classification (`pff_cepi.js`)

**Based on:** David Theobald's approach (2024)

**Classification zones:**
- **Core (3):** Forest far from edge (high smoothed distance)
- **Edge (2):** Non-core forest connected to core
- **Periphery (1):** Forest not connected to core

### Functions:

| Function | Method | Speed |
|----------|--------|-------|
| `classify(mask, options)` | cumulativeCost + kernel smoothing | Accurate |
| `classifyFast(mask, options)` | fastDistanceTransform | Faster |

### Theobald's d4Edge Approach:

```javascript
// 1. Distance to edge
var distToEdge = ee.Image(1).cumulativeCost({source: nonForest, ...});

// 2. Smooth with circular kernel (finds "chunky" areas)
var distSmoothed = distToEdge.reduceNeighborhood({
  reducer: ee.Reducer.mean(),
  kernel: ee.Kernel.circle({radius: radius, units: 'meters'})
});

// 3. Threshold for core
var core = distSmoothed.gt(coreDistance);

// 4. Spread from core to find edge (via cost distance through forest)
var cdFromCore = resistance.cumulativeCost({source: core, ...});
var edge = cdFromCore.lt(edgeDistance).and(mask).and(core.not());
```

**Parameters:**
- `coreDistance`: Smoothed distance threshold (default 100m)
- `radius`: Smoothing kernel size (default 2× coreDistance)
- `edgeDistance`: Max distance from core to be "edge" (default 500m)

**Why smoothing matters:**
- Raw distance finds pixels far from edge
- Smoothed distance finds "chunky" interior areas
- A thin corridor might be far from edge but won't have high *smoothed* distance

---

## Method Comparison

| Method | Speed | Max Area | Finds "Chunky" | Output |
|--------|-------|----------|----------------|--------|
| Kernel density | ⚡⚡⚡ | Unlimited | ✅ Yes | Density mask |
| Morphological | ⚡⚡⚡ | Unlimited | ✅ Yes | Cleaned mask |
| connectedPixelCount | ⚡⚡⚡ | ~92ha | ❌ No | Area-filtered mask |
| Vector | ⚡⚡ | Unlimited | ❌ No | Area-filtered mask |
| Tiled | ⚡ | Unlimited | ❌ No | Area-filtered mask |
| CEPI | ⚡⚡ | Unlimited | ✅ Yes | Zones (1-3) |

---

## Recommendations

| Goal | Recommended Method |
|------|-------------------|
| Quick preview of intact cores | Kernel density (`pff.js`) |
| Remove patches < 50ha | `filterByAreaPixelCount` |
| Remove patches < 500ha | `filterByArea` (auto-selects) |
| Remove patches < 10,000ha, large geometry | `filterByAreaTiled` |
| Core-Edge-Periphery classification | `pff_cepi.classify()` |
| Pre-clean noisy layers | `morphologicalClean()` |

---

## Scale Stability

All methods in `pff_cepi.js` use `.reproject({crs: proj, scale: scale})` to ensure results don't change when zooming in/out. This is critical for accurate analysis but can slow down rendering.

For interactive visualization, consider:
1. Use coarser scale (100m instead of 30m) for faster preview
2. Export final results rather than rendering on-the-fly
