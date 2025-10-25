#!/usr/bin/env python3
"""map_utils.py — Hanoi bus map with visible red dots, tooltips, search, and clustering."""

import os
import json
import math
import geopandas as gpd
import folium
from folium import Element, Marker, Tooltip, Icon, CircleMarker
from folium.plugins import MarkerCluster, Search


# ------------------- Helpers -------------------

def load_stops(geojson_path: str):
    """Load stops as both dict (geojson) and GeoDataFrame."""
    if not os.path.exists(geojson_path):
        raise FileNotFoundError(f"Stops file not found: {geojson_path}")
    gdf = gpd.read_file(geojson_path)
    with open(geojson_path, 'r', encoding='utf-8') as fh:
        geojson = json.load(fh)
    return geojson, gdf


def haversine_py(lat1, lon1, lat2, lon2):
    """Return distance in meters between (lat1, lon1) and (lat2, lon2)."""
    R = 6371e3
    phi1, phi2 = map(math.radians, (lat1, lat2))
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_js_helpers():
    """Return JavaScript for user click + distance panel."""
    return r"""
    <script>
    function getMapInstance() {
        var leafletDiv = document.querySelector('div.leaflet-container');
        return leafletDiv && leafletDiv._leaflet_map;
    }

    function haversine(lat1, lon1, lat2, lon2) {
        var R = 6371e3;
        var toRad = x => x * Math.PI / 180;
        var dLat = toRad(lat2 - lat1);
        var dLon = toRad(lon2 - lon1);
        var a = Math.sin(dLat/2)**2 + Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLon/2)**2;
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    }

    function createDistanceControl() {
        var control = L.control({position: 'topright'});
        control.onAdd = function(map) {
            var div = L.DomUtil.create('div', 'distance-control');
            div.style.background = 'white';
            div.style.padding = '6px 8px';
            div.style.borderRadius = '6px';
            div.style.boxShadow = '0 0 6px rgba(0,0,0,0.2)';
            div.innerHTML = '<b>Stops</b><br/>Click a stop to select.<br/>Click map to set your location.<hr/><div id="distance-output">No selection</div>';
            return div;
        };
        return control;
    }

    document.addEventListener('DOMContentLoaded', function() {
        var map = getMapInstance();
        if (!map) return;

        window.distanceControl = createDistanceControl();
        window.distanceControl.addTo(map);

        window.userMarker = null;
        window.lastSelectedStop = null;

        function updateDistancePanel() {
            var out = document.getElementById('distance-output');
            if (!out) return;
            if (window.lastSelectedStop && window.userMarker) {
                var s = window.lastSelectedStop;
                var u = window.userMarker.getLatLng();
                var d = haversine(u.lat, u.lng, s.lat, s.lng);
                out.innerHTML = 'Distance to <b>' + (s.name||'Không tên') + '</b>: ' + 
                    (d>=1000 ? (d/1000).toFixed(2)+' km' : d.toFixed(1)+' m');
            } else if (window.lastSelectedStop) {
                out.innerHTML = 'Selected: <b>' + (window.lastSelectedStop.name||'Không tên') + '</b>';
            } else if (window.userMarker) {
                out.innerHTML = 'Your location set. Click a stop to compute distance.';
            } else out.innerHTML = 'No selection';
        }

        map.on('click', function(e) {
            var latlng = e.latlng;
            if (window.userMarker) window.userMarker.setLatLng(latlng);
            else {
                window.userMarker = L.circleMarker(latlng, {
                    radius: 6, color: 'red', fillColor: 'red', fillOpacity: 0.8
                }).addTo(map).bindPopup('Your location').openPopup();
            }
            updateDistancePanel();
        });
    });
    </script>
    """


# ------------------- Map Builder -------------------

def build_map(stops_path, output_path=None, tiles='CartoDB Positron'):
    """Build Hanoi bus map with visible red dots, clustering, tooltips, and search."""
    geojson, stops = load_stops(stops_path)

    # Compute map center
    if not stops.empty and 'geometry' in stops:
        pts = [geom for geom in stops.geometry if geom and geom.geom_type == 'Point']
        if pts:
            xs, ys = [p.y for p in pts], [p.x for p in pts]
            center = [sum(xs)/len(xs), sum(ys)/len(ys)]
        else:
            center = [21.0278, 105.8342]
    else:
        center = [21.0278, 105.8342]

    m = folium.Map(location=center, zoom_start=12, tiles=tiles)

    # ✅ Create red-dot layer manually (works in all folium versions)
    dot_layer = folium.FeatureGroup(name="Bus Stops (searchable)").add_to(m)
    features = []

    for _, row in stops.iterrows():
        geom = row.geometry
        if geom is None or geom.geom_type != 'Point':
            continue
        name = (row.get('name') or row.get('Name') or '').strip()
        lat, lon = geom.y, geom.x

        CircleMarker(
            location=[lat, lon],
            radius=3,
            color='red',
            fill=True,
            fill_color='red',
            fill_opacity=0.8,
            tooltip=name if name else None
        ).add_to(dot_layer)

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name}
        })

    # ✅ Use separate lightweight GeoJson for Search
    geojson_layer = folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name="Search Layer"
    ).add_to(m)

    # ✅ Custom Search control (no blue pin)
    search = Search(
        layer=geojson_layer,
        search_label='name',
        placeholder='Search stops...',
        collapsed=False,
        search_zoom=16
    ).add_to(m)

    # Remove the default search marker (blue pin)
    disable_pin_js = """
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        var mapDiv = document.querySelector('div.leaflet-container');
        if (!mapDiv) return;
        var map = mapDiv._leaflet_map;
        if (!map) return;

        // Listen to search events
        map.on('search:locationfound', function(e) {
            try {
                // Remove the default Leaflet blue pin
                if (e.layer && e.layer._icon) {
                    e.layer.remove();
                }
            } catch(err) { console.warn('Search marker cleanup failed:', err); }
        });
    });
    </script>
    """
    m.get_root().html.add_child(Element(disable_pin_js))


    # 🟠 Clustered visible markers for terminals
    cluster = MarkerCluster(name="Bus Stops (clustered)").add_to(m)
    for _, row in stops.iterrows():
        geom = row.geometry
        if geom is None or geom.geom_type != 'Point':
            continue
        name = (row.get('name') or '').strip()
        lname = name.lower()
        if lname.startswith('bến xe'):
            Marker(
                location=[geom.y, geom.x],
                tooltip=Tooltip(name, sticky=True),
                popup=folium.Popup(name, max_width=250),
                icon=Icon(color='orange', icon='bus', prefix='fa')
            ).add_to(m)
        else:
            Marker(
                location=[geom.y, geom.x],
                tooltip=Tooltip(name, sticky=True),
                popup=folium.Popup(name, max_width=250),
                icon=Icon(color='red', icon='circle', prefix='fa')
            ).add_to(cluster)

    # Add JS for distance interactivity
    m.get_root().html.add_child(Element(get_js_helpers()))

    if output_path:
        m.save(output_path)
    return m


# ------------------- CLI -------------------

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Build Hanoi bus stops folium map')
    parser.add_argument('--stops', default=os.path.join(os.path.dirname(__file__), 'hanoi_bus_stops_osm.geojson'))
    parser.add_argument('--out', default=os.path.join(os.path.dirname(__file__), 'hanoi_busmap_folium.html'))
    args = parser.parse_args()
    print('Loading', args.stops)
    build_map(args.stops, args.out)
    print('Saved map to', args.out)
