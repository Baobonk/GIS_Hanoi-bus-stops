#!/usr/bin/env python3
"""
Optimized bus_map.py
- Fast generation for large stop counts using FastMarkerCluster
- Keeps routes (simplified for long geometries), heatmap (sampled), search + fuzzy recommendations
- Highlights stops starting with "Bến xe" in orange
- Accepts custom tile URL and attribution
"""

import os
import argparse
import json
import re
import unicodedata
from difflib import get_close_matches
from folium.plugins import MarkerCluster
import geopandas as gpd
import folium
from folium.plugins import HeatMap
import branca
from shapely.geometry import LineString, MultiLineString
from folium import Tooltip, Marker, Icon
from folium.features import DivIcon
# -------------------------
# CONFIG: set custom tiles here (or leave None to use CartoDB Positron)
# -------------------------
CUSTOM_TILES_URL = None
CUSTOM_TILES_ATTRIB = ""  # set attribution string for custom tiles if using one

# -------------------------
# Utility helpers
# -------------------------
def normalize_name(s: str) -> str:
    if not isinstance(s, str):
        return ''
    s = s.strip().lower()
    s = re.sub(r"\([^)]*\)", "", s)                # remove parentheses content
    s = re.sub(r"\s+", " ", s).strip()             # collapse whitespace
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')  # remove diacritics
    s = re.sub(r"[^0-9a-z\s]", "", s)              # remove punctuation keep alnum+space
    s = re.sub(r"\s+", " ", s).strip()
    return s

def simplify_coords(coords, max_pts=800):
    """If coords is long, downsample to reduce HTML size."""
    n = len(coords)
    if n <= max_pts:
        return coords
    step = max(1, n // max_pts)
    return [coords[i] for i in range(0, n, step)]

# -------------------------
# Main builder
# -------------------------
def build_map(stops_path=None, routes_path=None, output_path=None):
    BASE_DIR = os.path.dirname(__file__)
    stops_file = stops_path or os.path.join(BASE_DIR, 'hanoi_bus_stops_osm.geojson')
    routes_file = routes_path or os.path.join(BASE_DIR, 'hanoi_bus_routes_osm.geojson')
    output_file = output_path or os.path.join(BASE_DIR, 'hanoi_busmap_folium.html')

    # fallback alt paths
    if not os.path.exists(stops_file):
        alt = os.path.join(BASE_DIR, '..', 'hanoi_bus_stops_osm.geojson')
        if os.path.exists(alt): stops_file = alt
    if not os.path.exists(routes_file):
        alt = os.path.join(BASE_DIR, '..', 'hanoi_bus_routes_osm.geojson')
        if os.path.exists(alt): routes_file = alt

    stops = gpd.read_file(stops_file) if os.path.exists(stops_file) else gpd.GeoDataFrame(columns=['geometry'])
    routes = gpd.read_file(routes_file) if os.path.exists(routes_file) else gpd.GeoDataFrame(columns=['geometry'])

    print(f"Loaded {len(stops)} stops and {len(routes)} routes")

    # ensure WGS84
    try:
        if stops.crs and stops.crs.to_string() != 'EPSG:4326':
            stops = stops.to_crs('EPSG:4326')
    except Exception:
        pass
    try:
        if routes.crs and routes.crs.to_string() != 'EPSG:4326':
            routes = routes.to_crs('EPSG:4326')
    except Exception:
        pass

    # center
    pts = [g for g in stops.geometry if g is not None and getattr(g, 'geom_type', None) == 'Point']
    if pts:
        center = [sum(p.y for p in pts)/len(pts), sum(p.x for p in pts)/len(pts)]
    else:
        center = [21.0278, 105.8342]

    # init map (prefer canvas for better performance)
    if CUSTOM_TILES_URL:
        tiles_arg = None
    else:
        tiles_arg = 'CartoDB Positron'

    m = folium.Map(location=center, zoom_start=12, tiles=tiles_arg, prefer_canvas=False)

    if CUSTOM_TILES_URL:
        folium.TileLayer(tiles=CUSTOM_TILES_URL, attr=CUSTOM_TILES_ATTRIB, name='Custom').add_to(m)

    # --- draw routes (simplify long geometries) ---
    route_geoms = []
    if 'geometry' in routes.columns and len(routes) > 0:
        for _, r in routes.iterrows():
            geom = r.geometry
            if geom is None:
                continue
            if isinstance(geom, LineString):
                coords = [(lat, lon) for lon, lat in geom.coords]
                coords = simplify_coords(coords, max_pts=1000)
                folium.PolyLine(coords, color='blue', weight=1, opacity=0.6).add_to(m)
                route_geoms.append(LineString([(lon, lat) for lon, lat in geom.coords]))
            elif isinstance(geom, MultiLineString):
                for part in geom.geoms:
                    coords = [(lat, lon) for lon, lat in part.coords]
                    coords = simplify_coords(coords, max_pts=1000)
                    folium.PolyLine(coords, color='blue', weight=1, opacity=0.6).add_to(m)
                    route_geoms.append(LineString([(lon, lat) for lon, lat in part.coords]))

    # --- lightweight single-dot background (kept minimal) ---
    try:
        for _, row in stops.iterrows():
            geom = row.geometry
            if geom is None or getattr(geom, 'geom_type', None) != 'Point':
                continue
            name = (row.get('name') or row.get('Name') or '').strip()
            folium.CircleMarker(
                location=[geom.y, geom.x],
                radius=2,
                color='#800000',
                fill=True,
                fillOpacity=0.7,
                tooltip=name if name else None
            ).add_to(m)
    except Exception:
        pass

    # --- relations (go/back) parsing (unchanged logic) ---
    data_folder = os.path.join(BASE_DIR, 'datafolder')
    def _load_relation_file(path):
        if not os.path.exists(path):
            return []
        out = []
        with open(path, 'r', encoding='utf-8') as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                parts = [p.strip() for p in re.split(r"\s*[-–—>]+\s*", raw) if p.strip()]
                out.append(parts)
        return out

    go_lines = _load_relation_file(os.path.join(data_folder, 'go.txt'))
    back_lines = _load_relation_file(os.path.join(data_folder, 'back.txt'))

    # build normalized name maps
    norm_to_names = {}
    name_to_coords = {}
    for idx, row in stops.iterrows():
        nm = row.get('name') or row.get('Name') or ''
        n = normalize_name(nm)
        if n:
            norm_to_names.setdefault(n, []).append((idx, nm))
            geom = row.geometry
            if geom is not None and getattr(geom, 'geom_type', None) == 'Point':
                name_to_coords[n] = (geom.y, geom.x)

    def _match_name_to_idx(target):
        t = normalize_name(target)
        if not t:
            return None
        if t in norm_to_names and norm_to_names[t]:
            return int(norm_to_names[t][0][0])
        keys = list(norm_to_names.keys())
        t_nospace = t.replace(' ', '')
        for k in keys:
            if k.replace(' ', '') == t_nospace:
                return int(norm_to_names[k][0][0])
        m = get_close_matches(t, keys, n=1, cutoff=0.65)
        if m:
            return int(norm_to_names[m[0]][0][0])
        return None

    rel_go_coords = []
    rel_back_coords = []
    stop_rel_go = {int(i): [] for i in stops.index}
    stop_rel_back = {int(i): [] for i in stops.index}

    for ln in go_lines:
        coords = []
        member_idxs = []
        for p in ln:
            idx = _match_name_to_idx(p)
            if idx is not None and idx in stops.index:
                geom = stops.loc[idx].geometry
                if geom is not None and getattr(geom, 'geom_type', None) == 'Point':
                    coords.append([geom.y, geom.x])
                    member_idxs.append(int(idx))
        rel_go_coords.append(coords)
        if member_idxs:
            rel_id = len(rel_go_coords) - 1
            for si in set(member_idxs):
                stop_rel_go.setdefault(si, []).append(rel_id)

    for ln in back_lines:
        coords = []
        member_idxs = []
        for p in ln:
            idx = _match_name_to_idx(p)
            if idx is not None and idx in stops.index:
                geom = stops.loc[idx].geometry
                if geom is not None and getattr(geom, 'geom_type', None) == 'Point':
                    coords.append([geom.y, geom.x])
                    member_idxs.append(int(idx))
        rel_back_coords.append(coords)
        if member_idxs:
            rel_id = len(rel_back_coords) - 1
            for si in set(member_idxs):
                stop_rel_back.setdefault(si, []).append(rel_id)


    # --- build related_map (proximity or route-based) ---
    related_map = {}
    if 'geometry' in stops.columns and len(stops) > 0 and route_geoms:
        tol = 0.0005
        # use spatial index proximity for large
        use_proximity = len(stops) > 2000
        if use_proximity:
            stops_sindex = stops.sindex
            for idx, s in stops.iterrows():
                geom = s.geometry
                if geom is None or getattr(geom, 'geom_type', None) != 'Point':
                    related_map[idx] = []
                    continue
                minx, miny, maxx, maxy = geom.buffer(tol).bounds
                candidate_idxs = list(stops_sindex.intersection((minx, miny, maxx, maxy)))
                related = []
                for cid in candidate_idxs:
                    if cid == idx:
                        continue
                    og = stops.iloc[cid].geometry
                    if og is None or getattr(og, 'geom_type', None) != 'Point':
                        continue
                    dx = og.x - geom.x
                    dy = og.y - geom.y
                    if dx*dx + dy*dy <= tol*tol:
                        related.append((og.x, og.y))
                related_map[idx] = related
        else:
            try:
                route_buffers = gpd.GeoDataFrame({'route_idx': list(range(len(route_geoms)))},
                                                 geometry=[r.buffer(tol) for r in route_geoms],
                                                 crs='EPSG:4326')
                stops_reset = stops.reset_index().rename(columns={'index': 'stop_idx'})
                joined = gpd.sjoin(stops_reset[['stop_idx', 'geometry']], route_buffers, how='left', predicate='intersects')
                route_to_stops = {}
                for r_idx, group in joined.dropna(subset=['route_idx']).groupby('route_idx'):
                    route_to_stops[int(r_idx)] = [int(x) for x in group['stop_idx'].tolist()]
                for stop_idx in stops.index:
                    rows = joined[joined['stop_idx'] == stop_idx]
                    route_ids = rows['route_idx'].dropna().unique()
                    related = set()
                    for rid in route_ids:
                        for other_stop_idx in route_to_stops.get(int(rid), []):
                            og = stops.loc[other_stop_idx].geometry
                            if og is None or getattr(og, 'geom_type', None) != 'Point':
                                continue
                            related.add((og.x, og.y))
                    related_map[stop_idx] = list(related)
            except Exception as e:
                stops_sindex = stops.sindex
                for idx, s in stops.iterrows():
                    geom = s.geometry
                    if geom is None or getattr(geom, 'geom_type', None) != 'Point':
                        related_map[idx] = []
                        continue
                    minx, miny, maxx, maxy = geom.buffer(tol).bounds
                    candidate_idxs = list(stops_sindex.intersection((minx, miny, maxx, maxy)))
                    related = []
                    for cid in candidate_idxs:
                        if cid == idx:
                            continue
                        og = stops.iloc[cid].geometry
                        if og is None or getattr(og, 'geom_type', None) != 'Point':
                            continue
                        dx = og.x - geom.x
                        dy = og.y - geom.y
                        if dx*dx + dy*dy <= tol*tol:
                            related.append((og.x, og.y))
                    related_map[idx] = related

    # --- Prepare stops_copy with relation info ---
    stops_copy = stops.copy()
    stops_copy['related'] = stops_copy.index.map(lambda i: related_map.get(i, []))
    stops_copy['name'] = stops_copy.get('name', stops_copy.get('Name', None))
    stops_copy['rel_go'] = stops_copy.index.map(lambda i: stop_rel_go.get(int(i), []))
    stops_copy['rel_back'] = stops_copy.index.map(lambda i: stop_rel_back.get(int(i), []))

    # --- Build the FastMarkerCluster for all stops (fast) ---
    # --- Draw all stops efficiently with hover tooltips ---


# --- Create clustered layer for bus stops ---
    cluster_layer = MarkerCluster(name="Bus Stops (clustered)").add_to(m)

    for _, row in stops_copy.iterrows():
        geom = row.geometry
        if geom is None or geom.geom_type != 'Point':
            continue

        name = (row.get('name') or row.get('Name') or '').strip()
        lname = name.lower()

        # 🟠 Terminals ("Bến xe ...") — always visible, not clustered
        if lname.startswith('bến xe'):
            Marker(
                location=[geom.y, geom.x],
                tooltip=Tooltip(name, sticky=True),
                popup=folium.Popup(name, max_width=250),
                icon=Icon(color='orange', icon='bus', prefix='fa')
            ).add_to(m)

        # 🔴 Regular stops — inside cluster layer
        else:
            Marker(
                location=[geom.y, geom.x],
                tooltip=Tooltip(name, sticky=True),
                popup=folium.Popup(name, max_width=250),
                icon=Icon(color='red', icon='circle', prefix='fa')
            ).add_to(cluster_layer)


    # --- Heatmap (sample if necessary) ---
    heat_data = [[geom.y, geom.x] for geom in stops.geometry if geom is not None and getattr(geom, 'geom_type', None) == 'Point']
    if len(heat_data) > 1500:
        import random
        heat_data = random.sample(heat_data, 1500)
    if heat_data:
        HeatMap(heat_data, radius=10, blur=8, min_opacity=0.25).add_to(m)

    # --- Build JS payloads once (draw_js, bind_js, search_js) ---
    rel_go_json = json.dumps(rel_go_coords, ensure_ascii=False)
    rel_back_json = json.dumps(rel_back_coords, ensure_ascii=False)

    # Helper JS to get map instance at runtime
    get_map_js = """
    function getMapInstance() {
        var leafletDiv = document.querySelector('div.leaflet-container');
        return leafletDiv && leafletDiv._leaflet_map;
    }
    """

    draw_js = f"""
    <script>
    {get_map_js}
    var highlightLayer = null;
    var rel_go = {rel_go_json};
    var rel_back = {rel_back_json};
    var rel_go_layers = Array(rel_go.length).fill(null);
    var rel_back_layers = Array(rel_back.length).fill(null);
    function clearHighlight() {{
        var map = getMapInstance();
        if (!highlightLayer) highlightLayer = L.layerGroup().addTo(map);
        highlightLayer.clearLayers();
    }}
    function _createRelLayer(coords, style) {{
        try {{ return L.polyline(coords, style); }} catch(e) {{ console.error('createRelLayer', e); return null; }}
    }}
    function getOrCreateRel(type, idx) {{
        if (type === 'go') {{
            if (!rel_go_layers[idx] && rel_go[idx] && rel_go[idx].length >= 2) {{
                rel_go_layers[idx] = _createRelLayer(rel_go[idx], {{color:'green', weight:3, opacity:0.85}});
            }}
            return rel_go_layers[idx];
        }} else {{
            if (!rel_back_layers[idx] && rel_back[idx] && rel_back[idx].length >= 2) {{
                rel_back_layers[idx] = _createRelLayer(rel_back[idx], {{color:'darkgreen', weight:3, opacity:0.85}});
            }}
            return rel_back_layers[idx];
        }}
    }}
    function showRelationsForStop(stopProps) {{
        var map = getMapInstance();
        if (!highlightLayer) highlightLayer = L.layerGroup().addTo(map);
        clearHighlight();
        try {{
            var go_ids = stopProps.rel_go || [];
            var back_ids = stopProps.rel_back || [];
            go_ids.forEach(function(i) {{ var layer = getOrCreateRel('go', i); if (layer) layer.addTo(highlightLayer); }});
            back_ids.forEach(function(i) {{ var layer = getOrCreateRel('back', i); if (layer) layer.addTo(highlightLayer); }});
        }} catch(e) {{ console.error('showRelationsForStop error', e); }}
    }}
    </script>
    """

    bind_js = get_map_js + """
    <script>
    function bindStopHandlers() {
        var map = getMapInstance();
        var selectedStops = [];
        function tryAttach(layer, props) {
            if (!layer) return;
            // only attach to marker-like layers with coordinates
            var latlng = (layer.getLatLng && layer.getLatLng()) || (layer.getBounds && layer.getBounds().getCenter && layer.getBounds().getCenter());
            if (!latlng) return;
            // attach click once
            if (layer._distanceHandlerAttached) return;
            layer._distanceHandlerAttached = true;
            layer.on('click', function(e) {
                console.log('Marker clicked', props || {});
                var name = (props && (props.name || props.Name)) || 'Không tên';
                // manage selection (store globally)
                if (!window.selectedStops) window.selectedStops = [];
                if (window.selectedStops.length === 2) window.selectedStops = [];
                if (!window.selectedStops.some(function(s){ return s.name === name; })) {
                    window.selectedStops.push({name: name, latlng: latlng});
                }
                console.log('Selected stops:', window.selectedStops.map(function(s){return s.name;}));
                if (window.selectedStops.length === 2) {
                    var a = window.selectedStops[0].latlng, b = window.selectedStops[1].latlng;
                    var d = haversine(a.lat, a.lng, b.lat, b.lng);
                    console.log('Distance between "' + window.selectedStops[0].name + '" and "' + window.selectedStops[1].name + '":', d >= 1000 ? (d/1000).toFixed(2) + ' km' : d.toFixed(1) + ' m');
                }
                if (window.updateDistPanel) try { window.updateDistPanel(); } catch(e) { console.log('updateDistPanel error', e); }
                // show relations if available
                if (props && (props.rel_go || props.rel_back)) {
                    try { showRelationsForStop(props); } catch(err) { console.error('showRelationsForStop failed', err); }
                }
                // open popup if present
                if (layer.openPopup) { try { layer.openPopup(); } catch(e){} }
            });
        }

        // iterate layers and attach to markers and to sublayers
        for (var k in map._layers) {
            var lay = map._layers[k];
            if (!lay) continue;
            // direct marker-like
            tryAttach(lay, lay.feature && lay.feature.properties ? lay.feature.properties : (lay.options && lay.options.title ? {name: lay.options.title} : null));
            // groups / geojsons
            if (lay.eachLayer) {
                try {
                    lay.eachLayer(function(sub) {
                        var props = (sub.feature && sub.feature.properties) || (sub.options && sub.options.title ? {name: sub.options.title} : null);
                        tryAttach(sub, props);
                    });
                } catch(e) { console.log('eachLayer error', e); }
            }
        }
    }
    var map = getMapInstance();
    if (map && map.whenReady) { map.whenReady(bindStopHandlers); }

    function haversine(lat1, lon1, lat2, lon2) {
        var R = 6371e3; // meters
        var toRad = function(x){ return x * Math.PI / 180; };
        var dLat = toRad(lat2-lat1);
        var dLon = toRad(lon2-lon1);
        var a = Math.sin(dLat/2)*Math.sin(dLat/2) + Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLon/2)*Math.sin(dLon/2);
        var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        return R * c;
    }
    </script>
    """

    # --- Improved Search JS: flexible, diacritic/whitespace-insensitive, partial, and supports distance calculation by clicking stops
    search_js = r"""
    <script>
    function normalizeStr(s) {
        if (!s) return '';
        s = s.toLowerCase();
        s = s.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        s = s.replace(/[^\w\s]/g, '');
        s = s.replace(/\s+/g, ' ').trim();
        return s;
    }
    (function waitForMapReady(){
        var leafletDiv = document.querySelector('div.leaflet-container');
        var map = leafletDiv && leafletDiv._leaflet_map;
        if (!map) {
            setTimeout(waitForMapReady, 100);
            return;
        }
        console.log('Map found:', map);
    var stopIndex = [];
    window.selectedStops = window.selectedStops || [];
    var selectedStops = window.selectedStops;
        function buildStopIndexAndAttachClicks() {
            stopIndex = [];
            var count = 0;
            for (var k in map._layers) {
                var lay = map._layers[k];
                if (!lay) continue;
                // Accept GeoJson, CircleMarker, Marker, etc.
                if (lay.feature && (lay.getLatLng || lay.getBounds)) {
                    var props = lay.feature.properties || {};
                    if (!props.name && !props.Name) continue;
                    var nm = (props.name || props.Name || '').toString();
                    var norm = normalizeStr(nm);
                    var latlng = lay.getLatLng ? lay.getLatLng() : (lay.getBounds ? lay.getBounds().getCenter() : null);
                    stopIndex.push({name:nm, norm:norm, props:props, latlng: latlng, layer: lay});
                    // Attach click for distance
                    lay.on('click', function(e){
                        if (!latlng) return;
                        if (selectedStops.length === 2) selectedStops = [];
                        if (!selectedStops.some(function(s){return s.name===nm;})) {
                            selectedStops.push({name: nm, latlng:latlng});
                        }
                        updateDistPanel();
                    });
                    count++;
                }
                // Accept GeoJson group layers
                if (lay.eachLayer) {
                    try {
                        lay.eachLayer(function(sub) {
                            if (sub && sub.feature && (sub.getLatLng || sub.getBounds)) {
                                var props = sub.feature.properties || {};
                                if (!props.name && !props.Name) return;
                                var nm = (props.name || props.Name || '').toString();
                                var norm = normalizeStr(nm);
                                var latlng = sub.getLatLng ? sub.getLatLng() : (sub.getBounds ? sub.getBounds().getCenter() : null);
                                stopIndex.push({name:nm, norm:norm, props:props, latlng: latlng, layer: sub});
                                // Attach click for distance
                                sub.on('click', function(e){
                                    if (!latlng) return;
                                    if (selectedStops.length === 2) selectedStops = [];
                                    if (!selectedStops.some(function(s){return s.name===nm;})) {
                                        selectedStops.push({name: nm, latlng:latlng});
                                    }
                                    updateDistPanel();
                                });
                                count++;
                            }
                        });
                    } catch(e) { console.log('Error in eachLayer:', e); }
                }
            }
            console.log('Stop index built:', stopIndex.length, 'stops');
            if (stopIndex.length === 0) {
                console.log('No stops found. Map layers:', map._layers);
                alert('No bus stops found on the map. Please check the data or contact support.');
            }
        }
        function renderResults(list){
            var container = document.getElementById('stop-search-results');
            if (!container) { console.log('No results container'); return; }
            container.innerHTML = '';
            list.slice(0,50).forEach(function(item){
                var div = document.createElement('div');
                div.style.padding = '4px';
                div.style.borderBottom = '1px solid #eee';
                div.style.cursor = 'pointer';
                div.textContent = item.name;
                div.onclick = function(){
                    if (!item.latlng) return;
                    map.setView([item.latlng.lat, item.latlng.lng], 16);
                    showRelationsForStop(item.props);
                    if (item.layer && item.layer.openPopup) {
                        try { item.layer.openPopup(); } catch(e){}
                    }
                };
                container.appendChild(div);
            });
            console.log('Rendered', list.length, 'results');
        }
        function doSearch() {
            var input = document.getElementById('stop-search');
            if (!input) { console.log('No input element'); return; }
            var q = normalizeStr(input.value.trim());
            console.log('Search input:', input.value, 'Normalized:', q);
            if (!q){ var c = document.getElementById('stop-search-results'); if (c) c.innerHTML=''; return; }
            if (!stopIndex.length) { console.log('Stop index empty, rebuilding...'); buildStopIndexAndAttachClicks(); }
            var tokens = q.split(' ');
            var matches = stopIndex.filter(function(s){
                // Only match against normalized name, not coordinates
                return tokens.every(function(tk){ return s.norm.indexOf(tk) !== -1; });
            });
            console.log('Search:', q, 'matches:', matches.length, matches.map(x=>x.name));
            renderResults(matches);
        }
        window.updateDistPanel = function() {
            var panel = document.getElementById('dist-select-panel');
            if (!panel) return;
            panel.innerHTML = '';
            window.selectedStops.forEach(function(item, idx){
                var div = document.createElement('div');
                div.textContent = (idx+1) + '. ' + item.name;
                div.style.fontWeight = 'bold';
                div.style.marginBottom = '2px';
                panel.appendChild(div);
            });
            var info = document.getElementById('dist-info');
            if (!info) return;
            if (window.selectedStops.length === 2) {
                var a = window.selectedStops[0], b = window.selectedStops[1];
                if (a.latlng && b.latlng) {
                    var d = haversine(a.latlng.lat, a.latlng.lng, b.latlng.lat, b.latlng.lng);
                    info.textContent = 'Distance: ' + (d >= 1000 ? (d/1000).toFixed(2)+' km' : d.toFixed(1)+' m');
                } else {
                    info.textContent = 'Could not get coordinates.';
                }
            } else if (window.selectedStops.length === 1) {
                info.textContent = 'Selected 1 stop. Click another to measure.';
            } else {
                info.textContent = 'Select two stops by clicking markers.';
            }
        };
        function haversine(lat1, lon1, lat2, lon2) {
            var R = 6371e3; // meters
            var toRad = function(x){ return x * Math.PI / 180; };
            var dLat = toRad(lat2-lat1);
            var dLon = toRad(lon2-lon1);
            var a = Math.sin(dLat/2)*Math.sin(dLat/2) + Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLon/2)*Math.sin(dLon/2);
            var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            return R * c;
        }
        // Attach after map is ready
        if (map.whenReady) {
            map.whenReady(function(){
                buildStopIndexAndAttachClicks();
                var input = document.getElementById('stop-search');
                var btn = document.getElementById('stop-search-btn');
                if (input) {
                    input.addEventListener('input', doSearch);
                } else {
                    console.log('No search input found');
                }
                if (btn) {
                    btn.addEventListener('click', doSearch);
                } else {
                    console.log('No search button found');
                }
                updateDistPanel();
            });
        } else {
            buildStopIndexAndAttachClicks();
            var input = document.getElementById('stop-search');
            var btn = document.getElementById('stop-search-btn');
            if (input) {
                input.addEventListener('input', doSearch);
            }
            if (btn) {
                btn.addEventListener('click', doSearch);
            }
            updateDistPanel();
        }
        // Expose for debug
        window.debugSearch = doSearch;
        window.debugBuildStopIndex = buildStopIndexAndAttachClicks;
    })();
    </script>
    """
    # --- User location detection JS (robust map finder) ---
    geo_js = """
    <script>
    (function(){
    function findMapInstance() {
        try {
            var leafletDiv = document.querySelector('div.leaflet-container');
            if (leafletDiv && leafletDiv._leaflet_map) return leafletDiv._leaflet_map;
        } catch(e){}
        // Search global window for something that looks like a Leaflet map
        try {
            for (var k in window) {
                if (!window.hasOwnProperty(k)) continue;
                try {
                    var v = window[k];
                    if (v && typeof v === 'object' && typeof v.whenReady === 'function' && typeof v.setView === 'function') {
                        return v;
                    }
                } catch(e){}
            }
        } catch(e){}
        return null;
    }

    function locateUserOnMap(map){
        if (!navigator.geolocation){
            alert('Geolocation not supported by your browser.');
            return;
        }
        navigator.geolocation.getCurrentPosition(function(pos){
            var lat = pos.coords.latitude;
            var lon = pos.coords.longitude;
            try {
                if (window._youMarker && map.removeLayer) map.removeLayer(window._youMarker);
                if (window.L && window.L.circleMarker) {
                    window._youMarker = window.L.circleMarker([lat, lon], {
                        color: 'blue', fillColor:'#1E90FF', fillOpacity:0.9, radius:6
                    }).addTo(map).bindPopup('<b>You are here</b>').openPopup();
                }
                if (map.setView) map.setView([lat, lon], 15);
                if (window.setUserLocation) window.setUserLocation(lat, lon);
            } catch(e) { console.error('Error placing user marker', e); }
        }, function(err){
            console.error('Geolocation error:', err);
            alert('Unable to retrieve your location: ' + (err && err.message ? err.message : 'unknown'));
        }, {enableHighAccuracy:true, maximumAge:60000, timeout:10000});
    }

    function waitAndWire() {
        var map = findMapInstance();
        if (!map) { setTimeout(waitAndWire, 300); return; }
        // wire locate button when it exists in DOM
        var btn = document.getElementById('locate-me-btn');
        if (btn) {
            btn.addEventListener('click', function(){ locateUserOnMap(map); });
        } else {
            // if button not yet in DOM, wait a bit and try again
            var tries = 0;
            var waitBtn = function() {
                var b = document.getElementById('locate-me-btn');
                if (b) { b.addEventListener('click', function(){ locateUserOnMap(map); }); return; }
                tries++;
                if (tries < 10) setTimeout(waitBtn, 300);
            };
            waitBtn();
        }
        // expose global helper
        window.locateUser = function(){ locateUserOnMap(map); };
    }
    waitAndWire();
    })();
    </script>
    """
    # --- legend HTML (defined once) ---
    # Temporarily hide search and selected-stops UI by default; keep Locate button visible
    legend_html = """
        <div id="map-legend" style="position: fixed; bottom: 50px; left: 10px; z-index:9999; background: white; padding:10px; border-radius:6px; box-shadow: 0 0 6px rgba(0,0,0,0.25); width:280px;">
            <b>Legend</b><br>
            <i style="background:blue; width:12px; height:6px; display:inline-block;"></i> Bus routes<br>
            <i style="background:#800000; width:10px; height:10px; border-radius:50%; display:inline-block;"></i> Bus stops<br>
            <i style="background:orange; width:10px; height:10px; border-radius:50%; display:inline-block;"></i> Terminals (Bến xe)<br>
            <i style="background:green; width:12px; height:3px; display:inline-block;"></i> Relations (go/back)<br>
            <hr style="margin:6px 0;" />
            <!-- search hidden temporarily -->
            <div style="display:flex;gap:6px;align-items:center; display:none;" id="legend-search-row">
                <input id="stop-search" placeholder="Search stops..." style="flex:1; box-sizing:border-box; padding:4px;" />
                <button id="stop-search-btn" title="Search" style="margin-left:6px;">🔍</button>
            </div>
            <div id="stop-search-results" style="max-height:140px; overflow:auto; font-size:13px; margin-top:6px; display:none;"></div>
            <hr style="margin:8px 0 6px 0;" />
            <!-- distance panel hidden temporarily -->
            <div style="font-size:13px; margin-bottom:6px; display:none;" id="legend-dist-label"><b>Distance between stops</b></div>
            <div id="dist-select-panel" style="min-height:36px; font-size:13px; color:#222; background:#fafafa; padding:6px; border-radius:4px; border:1px solid #eee; display:none;"></div>
            <div id="dist-info" style="margin-top:6px; font-size:13px; color:#333; display:none;">Select two stops by clicking markers.</div>
            <div style="margin-top:8px; display:flex; gap:6px;"><button id="locate-me-btn" style="flex:1; padding:6px;">Locate me</button></div>
        </div>
        <script>
            // ensure hidden state remains in case scripts try to show them
            (function(){
                var hide = ['legend-search-row','stop-search-results','legend-dist-label','dist-select-panel','dist-info'];
                hide.forEach(function(id){ var el = document.getElementById(id); if (el) el.style.display = 'none'; });
            })();
        </script>
    """

    m.get_root().html.add_child(branca.element.Element(geo_js))

    m.get_root().html.add_child(branca.element.Element(search_js))

    # attach JS blocks once (order matters)
    m.get_root().html.add_child(branca.element.Element(draw_js))
    m.get_root().html.add_child(branca.element.Element(bind_js))
    m.get_root().html.add_child(branca.element.Element(legend_html))

    # save
    m.save(output_file)
    print('Saved map to', output_file)

# -------------------------
# CLI
# -------------------------
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stops', help='Path to stops geojson')
    parser.add_argument('--routes', help='Path to routes geojson')
    parser.add_argument('--out', help='Output html path')
    args = parser.parse_args()
    build_map(stops_path=args.stops, routes_path=args.routes, output_path=args.out)
