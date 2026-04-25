"""Benchmark scipy.ndimage.uniform_filter on Ecuador-sized array."""
import numpy as np
import time
from scipy.ndimage import uniform_filter

# Tile-sized test (what will actually run per tile)
print("Tile-sized (644 x 62721):")
arr = np.zeros((644, 62721), dtype=np.float32)
arr[100:544, 100:62000] = 1
t0 = time.time()
result = uniform_filter(arr.astype(np.float64), size=117, mode='constant', cval=0.0)
print(f"  Time: {time.time()-t0:.2f}s")
print(f"  Center: {result[322, 30000]:.4f}")

# Full raster (no tiling needed if this fits in RAM)
print("\nFull Ecuador (25276 x 62721):")
arr2 = np.zeros((25276, 62721), dtype=np.float32)
arr2[5000:20000, 5000:57000] = 1
t0 = time.time()
result2 = uniform_filter(arr2.astype(np.float64), size=117, mode='constant', cval=0.0)
elapsed = time.time() - t0
print(f"  Time: {elapsed:.1f}s")
print(f"  Center: {result2[12000, 30000]:.4f}")
print(f"\nDone!")
