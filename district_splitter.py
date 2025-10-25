import geopandas as gpd
import osmnx as ox
import os

# === 1. Load bus stops ===
print("Loading bus stops...")
stops = gpd.read_file("hanoi_bus_stops_osm.geojson")

# === 2. Download Hanoi districts ===
print("Downloading Hanoi district boundaries...")
districts = ox.features_from_place(
    "Hà Nội, Việt Nam",
    tags={"boundary": "administrative", "admin_level": "7"}
).reset_index()

# === 3. Detect district name column ===
name_col = None
for c in ["name", "name:vi", "official_name", "official_name:vi"]:
    if c in districts.columns:
        name_col = c
        break

if name_col is None:
    raise KeyError("No suitable district name column found in OSM data. Columns available: "
                   + ", ".join(districts.columns))

print(f"Using district name column: {name_col}")

# Keep only name + geometry
districts = districts[[name_col, "geometry"]].rename(columns={name_col: "district"})

# === 4. Match coordinate systems ===
stops = stops.to_crs(districts.crs)

# === 5. Spatial join (which district each stop belongs to) ===
print("Matching bus stops to districts...")
stops_with_district = gpd.sjoin(stops, districts, how="left", predicate="within")

# === 6. Export ===
os.makedirs("district_bus_stops", exist_ok=True)

summary = []
for district_name, group in stops_with_district.groupby("district", dropna=True):
    safe_name = district_name.replace(" ", "_")
    outpath = f"district_bus_stops/{safe_name}.geojson"
    group.to_file(outpath, driver="GeoJSON")
    summary.append((district_name, len(group)))
    print(f"Saved {outpath} ({len(group)} stops)")

# === 7. Optional: summary report ===
import pandas as pd
summary_df = pd.DataFrame(summary, columns=["District", "StopCount"])
summary_df.to_csv("district_bus_stops_summary.csv", index=False)
print("\n✅ Done! Bus stops separated by district.")
print(summary_df)
