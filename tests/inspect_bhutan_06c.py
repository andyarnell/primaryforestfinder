"""Inspect the Bhutan 06c nested-forest fixture to lock in the schema
the CEO export algorithm will read. Run from QGIS-aware Python:

    & "C:/Program Files/QGIS 3.38.0/bin/python-qgis.bat" tests/inspect_bhutan_06c.py
"""
from osgeo import ogr

PATH = (
    r"C:\Users\Arnell\Downloads\qgis_pff_testing\BTN\full_workflow_260504"
    r"\BTN_2020_qgis_06c_naturally_regenerating_forest_with_primary_nested_vector.shp"
)


def main():
    ds = ogr.Open(PATH)
    if ds is None:
        print("FAILED to open:", PATH)
        return 1
    layer = ds.GetLayer(0)
    print("Feature count:", layer.GetFeatureCount())
    sr = layer.GetSpatialRef()
    if sr is not None:
        auth = sr.GetAuthorityName(None) or "?"
        code = sr.GetAuthorityCode(None) or "?"
        print("CRS:", auth + ":" + code)
    defn = layer.GetLayerDefn()
    print("Fields:")
    field_names = []
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        field_names.append(fd.GetName())
        print("  ", fd.GetName(), "|", fd.GetTypeName(),
              "| width=", fd.GetWidth())

    print("\nFirst 5 features:")
    for i, feat in enumerate(layer):
        if i >= 5:
            break
        g = feat.GetGeometryRef()
        attrs = {}
        for j in range(defn.GetFieldCount()):
            fd = defn.GetFieldDefn(j)
            attrs[fd.GetName()] = feat.GetField(fd.GetName())
        area = g.GetArea() if g else 0
        print("  fid=", feat.GetFID(), "attrs=", attrs,
              "area_m2=", round(area))

    layer.ResetReading()
    candidates = ["level", "class", "value", "class_id", "dn", "DN"]
    class_field = None
    for c in candidates:
        if c in field_names:
            class_field = c
            break
    print("\nPicked class field:", class_field)
    counts = {}
    for feat in layer:
        v = feat.GetField(class_field) if class_field else None
        counts[v] = counts.get(v, 0) + 1
    print("Counts by class value:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
