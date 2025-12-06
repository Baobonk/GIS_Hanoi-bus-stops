
"""
save_all_hanoi_wards_polygons.py
----------------------------------------
Fetches all ward (phường) boundaries in Hà Nội from OpenStreetMap
and saves only Polygon/MultiPolygon geometries as GeoJSON files.

✅ Works on all OSMnx versions
✅ Each ward saved individually as 'Phường_<Name>.geojson'
✅ Automatically skips existing files
✅ Filters out non-polygon geometries
"""

import os
import geopandas as gpd
import osmnx as ox

OUTPUT_DIR = os.path.join("GIS", "Finals", "ward_borders_all")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_all_hanoi_wards():
    """Fetch all wards (phường) within Hà Nội from OpenStreetMap."""
    print("🌍 Downloading ward boundaries for Hà Nội...")

    # ✅ Works for both new and old OSMnx versions
    if hasattr(ox, "features_from_place"):
        gdf = ox.features_from_place(
            "Hà Nội, Việt Nam",
            tags={"boundary": "administrative", "admin_level": "10"}
        )
    elif hasattr(ox, "geometries_from_place"):
        gdf = ox.geometries_from_place(
            "Hà Nội, Việt Nam",
            tags={"boundary": "administrative", "admin_level": "10"}
        )
    else:
        raise RuntimeError("❌ Unsupported OSMnx version. Please update via: pip install -U osmnx")

    if gdf.empty:
        raise RuntimeError("❌ No ward boundaries found in OSM data for Hà Nội.")

    # ✅ Filter only Polygon or MultiPolygon geometries
    gdf = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()

    print(f"✅ Retrieved {len(gdf)} ward polygons from OpenStreetMap.")
    return gdf


def save_each_ward(gdf):
    """Save each ward as an individual GeoJSON file."""
    for idx, row in gdf.iterrows():
        name = row.get("name")
        if not name or not isinstance(name, str):
            continue

        safe_name = name.replace(" ", "_").replace("/", "-")
        out_path = os.path.join(OUTPUT_DIR, f"{safe_name}.geojson")

        if os.path.exists(out_path):
            print(f"📂 {safe_name}.geojson already exists, skipping...")
            continue

        try:
            ward_gdf = gpd.GeoDataFrame([row], crs=gdf.crs)
            ward_gdf.to_file(out_path, driver="GeoJSON")
            print(f"✅ Saved {out_path}")
        except Exception as e:
            print(f"⚠️ Failed to save {safe_name}: {e}")


if __name__ == "__main__":
    try:
        wards_gdf = get_all_hanoi_wards()
        save_each_ward(wards_gdf)
        print("\n🎉 All ward polygons saved to:")
        print(OUTPUT_DIR)
    except Exception as e:
        print(f"❌ Error: {e}")
