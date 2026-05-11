try:
    from processing.core.Processing import Processing
    print("Processing import OK:", Processing)
except Exception as e:
    print("Processing import FAILED:", type(e).__name__, e)
import processing
print("processing module:", processing)
