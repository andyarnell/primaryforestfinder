"""Test FFT circular focal mean — verifies scipy is available and correct."""
import numpy as np
import time

try:
    from scipy.signal import fftconvolve
    print("scipy.signal.fftconvolve: AVAILABLE")
except ImportError:
    print("scipy NOT available — would fall back to integral-image loop")
    exit(1)

# Build circular kernel
radius_px = 66
y, x = np.ogrid[-radius_px:radius_px+1, -radius_px:radius_px+1]
kernel = ((x*x + y*y) <= radius_px*radius_px).astype(np.float64)
kernel /= kernel.sum()
print(f"Kernel shape: {kernel.shape}, sum: {kernel.sum():.6f}")

# Test on tile-sized array (simulates one Ecuador tile)
rows, cols = 644, 62721
print(f"\nTest array: {rows} x {cols} ({rows*cols*8/1e6:.0f} MB as float64)")
arr = np.zeros((rows, cols), dtype=np.float32)
arr[100:544, 100:62621] = 1  # big forest block

t0 = time.time()
density = fftconvolve(arr.astype(np.float64), kernel, mode='same')
elapsed = time.time() - t0

print(f"FFT convolution time: {elapsed:.1f}s")
print(f"Center density: {density[322, 31000]:.4f} (should be ~1.0)")
print(f"Edge density: {density[100, 31000]:.4f} (should be ~0.5)")
print(f"Outside density: {density[10, 10]:.6f} (should be ~0.0)")

assert density[322, 31000] > 0.99, f"Center too low: {density[322, 31000]}"
assert density[10, 10] < 0.01, f"Outside too high: {density[10, 10]}"

# Estimate for full Ecuador (50 tiles)
print(f"\nEstimated full Ecuador time: {elapsed * 50:.0f}s ({elapsed * 50 / 60:.1f} min)")
print("PASSED")
