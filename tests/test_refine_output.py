"""Smoke test for the tiled refine_output focal mean functions.
Pure numpy — no QGIS dependency.
"""
import numpy as np


def _circular_focal_mean_fast(arr, radius_px, feedback=None):
    rows, cols = arr.shape
    pad = radius_px + 1
    padded = np.pad(arr.astype(np.float64), pad, mode='constant',
                    constant_values=0)
    integral = padded.cumsum(axis=0).cumsum(axis=1)
    acc = np.zeros((rows, cols), dtype=np.float64)
    n_pixels = 0
    for dy in range(-radius_px, radius_px + 1):
        dx_max = int(np.floor(np.sqrt(max(0, radius_px**2 - dy**2))))
        if dx_max < 0:
            continue
        n_pixels += 2 * dx_max + 1
        r1 = pad + dy - 1
        r2 = pad + dy
        c1 = pad - dx_max
        c2 = pad + dx_max + 1
        acc += (integral[r2:r2 + rows, c2:c2 + cols]
                - integral[r2:r2 + rows, c1:c1 + cols]
                - integral[r1:r1 + rows, c2:c2 + cols]
                + integral[r1:r1 + rows, c1:c1 + cols])
    if n_pixels == 0:
        n_pixels = 1
    return acc / n_pixels


def _square_focal_mean_fast(arr, radius_px, feedback=None):
    rows, cols = arr.shape
    pad = radius_px + 1
    padded = np.pad(arr.astype(np.float64), pad, mode='constant',
                    constant_values=0)
    integral = padded.cumsum(axis=0).cumsum(axis=1)
    side = 2 * radius_px + 1
    box_sum = (integral[side:side + rows, side:side + cols]
               - integral[0:rows, side:side + cols]
               - integral[side:side + rows, 0:cols]
               + integral[0:rows, 0:cols])
    return box_sum / (side * side)


# === Tests ===

print("Test 1: circular focal mean basic...")
arr = np.zeros((200, 300), dtype=np.float32)
arr[50:150, 50:250] = 1
result = _circular_focal_mean_fast(arr, 10)
print(f"  Center={result[100,150]:.4f} Edge={result[50,150]:.4f} Outside={result[10,10]:.4f}")
assert result[100, 150] > 0.99
assert result[10, 10] < 0.01
print("  PASSED")

print("\nTest 2: square focal mean basic...")
result2 = _square_focal_mean_fast(arr, 10)
print(f"  Center={result2[100,150]:.4f}")
assert result2[100, 150] > 0.99
print("  PASSED")

print("\nTest 3: tile-sized (644 x 5000, r=66)...")
big = np.zeros((644, 5000), dtype=np.float32)
big[100:544, 100:4900] = 1
result3 = _circular_focal_mean_fast(big, 66)
print(f"  Center={result3[322,2500]:.4f} Shape={result3.shape}")
assert result3[322, 2500] > 0.99
print("  PASSED")

print("\nMemory per Ecuador tile (644 x 62721 @ float64):")
mem_gb = (644 + 134) * (62721 + 134) * 8 * 3 / 1e9
print(f"  ~{mem_gb:.1f} GB (padded + integral + acc)")

print("\nAll tests passed!")
