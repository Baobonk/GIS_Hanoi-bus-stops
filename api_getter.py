import requests
import requests
import geopandas as gpd
from shapely.geometry import Point, LineString, MultiLineString
import time


# === 1. Hàm tải dữ liệu Overpass API ===
def overpass_query(query, attempts=3, pause=2.0):
    url = "https://overpass-api.de/api/interpreter"
    for attempt in range(attempts):
        resp = requests.get(url, params={"data": query}, timeout=180)
        if resp.status_code == 200:
            return resp.json()
        else:
            time.sleep(pause)
    resp.raise_for_status()


if __name__ == '__main__':
    # Define bounding box: south, west, north, east (Hanoi-ish sample)
    south, west, north, east = 20.8, 105.7, 21.3, 106.0

    # === 2. Tải điểm dừng xe buýt ===
    print("⬇️ Đang tải điểm dừng xe buýt từ OSM…")
    bus_stop_query = f"""
    [out:json][timeout:90];
    node["highway"="bus_stop"]({south},{west},{north},{east});
    out body;
    """
    data = overpass_query(bus_stop_query)
    data_stops = data.get('elements', [])

    stops_rows = []
    for el in data_stops:
        if el.get('type') != 'node':
            continue
        lon = el.get('lon')
        lat = el.get('lat')
        if lon is None or lat is None:
            continue
        stops_rows.append({
            'id': el.get('id'),
            'name': el.get('tags', {}).get('name', 'Không tên'),
            'geometry': Point(lon, lat)
        })

    stops = gpd.GeoDataFrame(stops_rows, crs='EPSG:4326') if stops_rows else gpd.GeoDataFrame(columns=['id','name','geometry'], crs='EPSG:4326')
    stops.to_file('hanoi_bus_stops_osm.geojson', driver='GeoJSON')
    print(f"✅ Đã tải {len(stops)} điểm dừng xe buýt.\n")

    # === 3. Tải tuyến xe buýt (ways / relations -> ways) ===
    print("⬇️ Đang tải tuyến xe buýt từ OSM…")
    # Request relations and ways in bbox, then expand members to get geometry (out geom)
    bus_routes_query = f"""
    [out:json][timeout:180];
    (
      relation["route"="bus"]({south},{west},{north},{east});
      way["route"="bus"]({south},{west},{north},{east});
    );
    (._;>;);
    out geom;
    """
    data = overpass_query(bus_routes_query)
    elements = data.get('elements', [])

    # Collect ways with geometry
    ways = {el['id']: el for el in elements if el.get('type') == 'way' and 'geometry' in el}

    routes_rows = []

    # Helper to stitch way segments by matching endpoints into contiguous sequences
    def _stitch_segments(segments):
        # segments: list of lists of (lon,lat) tuples
        remaining = [list(seg) for seg in segments]
        sequences = []
        while remaining:
            seq = remaining.pop(0)
            changed = True
            while changed:
                changed = False
                i = 0
                while i < len(remaining):
                    seg = remaining[i]
                    if not seg:
                        remaining.pop(i)
                        continue
                    # match end-to-start
                    if seq[-1] == seg[0]:
                        seq.extend(seg[1:])
                        remaining.pop(i)
                        changed = True
                        continue
                    # match end-to-end (reverse seg)
                    if seq[-1] == seg[-1]:
                        seq.extend(reversed(seg[:-1]))
                        remaining.pop(i)
                        changed = True
                        continue
                    # match start-to-end
                    if seq[0] == seg[-1]:
                        seq = seg[:-1] + seq
                        remaining.pop(i)
                        changed = True
                        continue
                    # match start-to-start (reverse seg)
                    if seq[0] == seg[0]:
                        seq = list(reversed(seg[1:])) + seq
                        remaining.pop(i)
                        changed = True
                        continue
                    i += 1
            sequences.append(seq)
        return sequences

    # First, build routes from relations by concatenating member ways when possible
    for el in elements:
        if el.get('type') != 'relation':
            continue
        tags = el.get('tags', {})
        name = tags.get('name', tags.get('ref', 'Không tên'))
        # collect way segments for this relation (preserve member order)
        segments = []
        for m in el.get('members', []):
            if m.get('type') == 'way':
                w = ways.get(m.get('ref'))
                if w and 'geometry' in w:
                    coords = [(pt['lon'], pt['lat']) for pt in w['geometry']]
                    if len(coords) >= 2:
                        segments.append(coords)

        if not segments:
            continue

        try:
            stitched = _stitch_segments(segments)
            # Create geometry: single LineString if one continuous sequence, else MultiLineString
            if len(stitched) == 1:
                geom = LineString(stitched[0])
            else:
                # ensure each sub-sequence has at least 2 points
                multiline = [s for s in stitched if len(s) >= 2]
                if len(multiline) == 1:
                    geom = LineString(multiline[0])
                else:
                    geom = MultiLineString(multiline)

            routes_rows.append({'id': el.get('id'), 'name': name, 'geometry': geom})
        except Exception:
            # fall back to naive concatenation
            try:
                flat = [pt for seg in segments for pt in seg]
                if len(flat) >= 2:
                    routes_rows.append({'id': el.get('id'), 'name': name, 'geometry': LineString(flat)})
            except Exception:
                pass

    # Also include standalone ways that are tagged as bus routes
    for w in ways.values():
        tags = w.get('tags', {})
        if tags.get('route') == 'bus' or 'route' in tags:
            coords = [(pt['lon'], pt['lat']) for pt in w['geometry']]
            if len(coords) >= 2:
                try:
                    geom = LineString(coords)
                    routes_rows.append({'id': w.get('id'), 'name': tags.get('name', tags.get('ref', 'Không tên')), 'geometry': geom})
                except Exception:
                    pass

    routes_gdf = gpd.GeoDataFrame(routes_rows, crs='EPSG:4326') if routes_rows else gpd.GeoDataFrame(columns=['id','name','geometry'], crs='EPSG:4326')
    routes_gdf.to_file('hanoi_bus_routes_osm.geojson', driver='GeoJSON')
    print(f"✅ Đã tải {len(routes_gdf)} tuyến xe buýt.\n")

    print("🎉 Hoàn tất! Dữ liệu OSM đã lưu:")
    print(" - hanoi_bus_stops_osm.geojson")
    print(" - hanoi_bus_routes_osm.geojson")
