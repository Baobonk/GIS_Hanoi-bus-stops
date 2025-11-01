#!/usr/bin/env python3
"""
bus_map_search_only.py
----------------------------------------
🚌 Hanoi bus stops + ward borders
✅ Includes Leaflet Search bar to find stops
✅ Bus stops layer hidden by default
✅ Added: Locate Me button ONLY
"""

import os
import json
import geopandas as gpd
import pandas as pd
import folium
from folium.plugins import Search, LocateControl


def load_geojson(path):
    if not os.path.exists(path):
        print(f"⚠️ Missing: {path}")
        return None, None
    gdf = gpd.read_file(path)
    with open(path, "r", encoding="utf-8") as f:
        geojson = json.load(f)
    return geojson, gdf


def make_json_safe(gdf):
    for col in gdf.columns:
        if col != "geometry":
            gdf[col] = gdf[col].astype(str)
    return gdf


def build_bus_map(folder_path, output_path="hanoi_busmap_search_only.html"):
    ward_files = [
        "Phường_Cầu_Giấy.geojson",
        "Phường_Từ_Liêm.geojson",
        "Phường_Nghĩa_Đô.geojson",
        "Phường_Phú_Diễn.geojson",
    ]

    all_gdfs, all_features = [], []

    for ward_file in ward_files:
        full_path = os.path.join(folder_path, ward_file)
        geojson, gdf = load_geojson(full_path)
        if gdf is None or gdf.empty:
            continue

        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)

        gdf = make_json_safe(gdf)
        all_gdfs.append(gdf)
        print(f"✅ Loaded {len(gdf)} stops from {ward_file}")

        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.geom_type != "Point":
                continue
            name = (row.get("name") or row.get("Name") or "").strip()
            lat, lon = geom.y, geom.x
            all_features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"name": name}
            })

    if not all_gdfs:
        raise RuntimeError("❌ No ward bus stop files found!")

    combined = gpd.GeoDataFrame(pd.concat(all_gdfs, ignore_index=True))
    center = [combined.geometry.y.mean(), combined.geometry.x.mean()]

    # Base map
    m = folium.Map(location=center, zoom_start=13, tiles=None)
    folium.TileLayer("CartoDB Voyager", name="🗺️ Vibrant").add_to(m)
    folium.TileLayer("Esri.WorldImagery", name="🛰️ Satellite").add_to(m)
    folium.TileLayer("OpenStreetMap", name="🌏 OSM").add_to(m)

    # Ward borders
    ward_border_folder = os.path.join(os.path.dirname(__file__), "ward_borders_all")
    ward_colors = {
        "Phường_Cầu_Giấy.geojson": "#e41a1c",
        "Phường_Từ_Liêm.geojson": "#377eb8",
        "Phường_Nghĩa_Đô.geojson": "#4daf4a",
        "Phường_Phú_Diễn.geojson": "#984ea3",
    }

    for ward_file in ward_files:
        border_path = os.path.join(ward_border_folder, ward_file)
        if not os.path.exists(border_path):
            continue
        try:
            gdf_border = gpd.read_file(border_path)
            if gdf_border.empty:
                continue

            if gdf_border.crs and gdf_border.crs.to_epsg() != 4326:
                gdf_border = gdf_border.to_crs(4326)

            gdf_border = make_json_safe(gdf_border)
            color = ward_colors.get(ward_file, "#ff7800")
            ward_name = ward_file.replace("Phường_", "").replace(".geojson", "").replace("_", " ")

            folium.GeoJson(
                gdf_border.__geo_interface__,
                name=f"Ranh giới: {ward_name}",
                style_function=lambda feat, col=color: {
                    "color": col,
                    "weight": 2,
                    "fill": True,
                    "fillColor": col,
                    "fillOpacity": 0.15,
                    "opacity": 0.8,
                },
                tooltip=folium.GeoJsonTooltip(fields=["name"] if "name" in gdf_border.columns else None)
            ).add_to(m)

            print(f"🗺️ Added border: {ward_name}")
        except Exception as e:
            print(f"⚠️ Failed to add border: {ward_file} - {e}")

    # Bus stops layer (hidden)
    search_layer = folium.GeoJson(
        {"type": "FeatureCollection", "features": all_features},
        name="🚌 Bus Stops",
        popup=folium.GeoJsonPopup(fields=["name"]),
        show=False
    ).add_to(m)

    # Search bar
    Search(
        layer=search_layer,
        search_label="name",
        placeholder="🔍 Search for a bus stop...",
        collapsed=False,
        search_zoom=16
    ).add_to(m)

    # ✅ Add Locate Me button ONLY
    LocateControl(auto_start=False).add_to(m)

    # 🚍 Add bus routes layer (if available)
    # Try looking in the provided folder_path first, then next to this script
    possible_route_paths = [
        os.path.join(folder_path, "hanoi_bus_routes_osm.geojson"),
        os.path.join(os.path.dirname(__file__), "hanoi_bus_routes_osm.geojson"),
    ]
    route_gdf = None
    for rp in possible_route_paths:
        if os.path.exists(rp):
            try:
                route_gdf = gpd.read_file(rp)
                if route_gdf.crs and route_gdf.crs.to_epsg() != 4326:
                    route_gdf = route_gdf.to_crs(4326)
                route_gdf = make_json_safe(route_gdf)
                print(f"🚍 Loaded routes from {rp} ({len(route_gdf)} features)")
                break
            except Exception as e:
                print(f"⚠️ Failed to load routes from {rp}: {e}")

    if route_gdf is not None and not route_gdf.empty:
        def route_style(feature):
            return {
                'color': '#ff7800',
                'weight': 3,
                'opacity': 0.8,
            }

        # Try to filter routes to those that serve the loaded stops (buffer in meters)
        try:
            stops_gdf = combined
            if stops_gdf.crs is None:
                stops_gdf.set_crs(epsg=4326, inplace=True)
            if route_gdf.crs is None:
                route_gdf.set_crs(epsg=4326, inplace=True)

            stops_m = stops_gdf.to_crs(epsg=3857)
            routes_m = route_gdf.to_crs(epsg=3857)

            selected_mask = None
            for radius in (50, 100, 200):
                buf = stops_m.geometry.buffer(radius)
                union = buf.unary_union
                mask = routes_m.geometry.intersects(union)
                if mask.any():
                    selected_mask = mask
                    print(f"🚍 Filtering routes: found {int(mask.sum())} routes within {radius}m of stops")
                    break

            if selected_mask is None or not selected_mask.any():
                filtered_routes = route_gdf
                print("🚍 No nearby routes found within 200m of stops; adding all routes as fallback.")
            else:
                filtered_routes = route_gdf.loc[selected_mask.values]

        except Exception as e:
            print(f"⚠️ Failed to spatially filter routes: {e}; adding all routes.")
            filtered_routes = route_gdf

        # Add popup/tooltip field if available
        popup_field = None
        for col in ('ref', 'name', 'route'):
            if col in filtered_routes.columns:
                popup_field = col
                break

        folium.GeoJson(
            filtered_routes.__geo_interface__,
            name='🚍 Bus Routes',
            style_function=lambda feat: route_style(feat),
            tooltip=folium.GeoJsonTooltip(fields=[popup_field] if popup_field else None)
        ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(output_path)
    print(f"✅ Map saved to {output_path}")
    return m


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build Hanoi bus map (search only)")
    parser.add_argument("--folder", default=os.path.join("GIS", "Finals", "district_bus_stops"))
    parser.add_argument("--out", default="hanoi_busmap_search_only.html")
    args = parser.parse_args()
    build_bus_map(args.folder, args.out)