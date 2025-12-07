#!/usr/bin/env python3
"""
bus_map.py - Enhanced Hanoi Bus Stop Interactive Map Generator
==============================================================

Features:
---------
🚌 Smart bus stop visualization with clustering
🗺️ Multi-layer ward borders with custom styling
🔍 Advanced search with autocomplete
📍 Location tracking with distance calculator
📊 Live statistics panel
🎨 Multiple map tile options
⚡ Performance optimized with caching
🔧 Configurable via JSON config file
📝 Comprehensive logging and error handling

Author: Enhanced version
Date: December 2025
"""

import os
import sys
import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from datetime import datetime

import geopandas as gpd
import pandas as pd
import folium
from folium import Element, Icon, Marker, Tooltip, FeatureGroup
from folium.plugins import (
    Search, LocateControl, MarkerCluster, 
    MiniMap, Fullscreen, MousePosition, MeasureControl
)

# ==================== CONFIGURATION ====================

@dataclass
class MapConfig:
    """Configuration for map generation."""
    
    # Paths
    folder_path: str = "district_bus_stops"
    output_path: str = "hanoi_busmap_enhanced.html"
    ward_borders_folder: str = "ward_borders_all"
    routes_file: str = "hanoi_bus_routes_osm.geojson"
    
    # Map settings
    default_tile: str = "CartoDB Voyager"
    zoom_start: int = 13
    search_zoom: int = 16
    
    # Ward files
    ward_files: List[str] = field(default_factory=lambda: [
        "Phường_Cầu_Giấy.geojson",
        "Phường_Từ_Liêm.geojson",
        "Phường_Nghĩa_Đô.geojson",
        "Phường_Phú_Diễn.geojson",
    ])
    
    # Ward colors
    ward_colors: Dict[str, str] = field(default_factory=lambda: {
        "Phường_Cầu_Giấy.geojson": "#e41a1c",
        "Phường_Từ_Liêm.geojson": "#377eb8",
        "Phường_Nghĩa_Đô.geojson": "#4daf4a",
        "Phường_Phú_Diễn.geojson": "#984ea3",
    })
    
    # Feature flags
    enable_clustering: bool = True
    enable_statistics: bool = True
    enable_distance_calc: bool = True
    enable_minimap: bool = True
    enable_measure: bool = True
    show_stops_by_default: bool = False
    
    # Route filtering
    route_buffer_distances: List[int] = field(default_factory=lambda: [50, 100, 200])
    
    @classmethod
    def from_json(cls, json_path: str) -> 'MapConfig':
        """Load configuration from JSON file."""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls(**data)
        except Exception as e:
            logging.warning(f"Failed to load config from {json_path}: {e}. Using defaults.")
            return cls()


# ==================== LOGGING SETUP ====================

def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure logging with colored output and file handler."""
    logger = logging.getLogger(__name__)
    logger.setLevel(level)
    
    # Console handler with formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    log_file = f"bus_map_{datetime.now():%Y%m%d_%H%M%S}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()


# ==================== UTILITY FUNCTIONS ====================

def make_json_safe(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Convert all non-geometry columns to strings for JSON serialization.
    
    Args:
        gdf: Input GeoDataFrame
        
    Returns:
        GeoDataFrame with string-converted columns
    """
    for col in gdf.columns:
        if col != "geometry":
            gdf[col] = gdf[col].astype(str)
    return gdf


def validate_geojson_file(path: Union[str, Path]) -> bool:
    """Validate if file exists and is a valid GeoJSON.
    
    Args:
        path: Path to GeoJSON file
        
    Returns:
        True if valid, False otherwise
    """
    path = Path(path)
    if not path.exists():
        logger.warning(f"File not found: {path}")
        return False
    
    if not path.suffix.lower() == '.geojson':
        logger.warning(f"Not a GeoJSON file: {path}")
        return False
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if 'type' not in data or data['type'] not in ['FeatureCollection', 'Feature']:
            logger.warning(f"Invalid GeoJSON structure in {path}")
            return False
        return True
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {path}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error validating {path}: {e}")
        return False


# ==================== CORE CLASSES ====================

class GeoDataLoader:
    """Handles loading and processing of geospatial data."""
    
    def __init__(self, config: MapConfig):
        self.config = config
        self._cache: Dict[str, Tuple[Dict, gpd.GeoDataFrame]] = {}
    
    def load_geojson(self, path: Union[str, Path]) -> Tuple[Optional[Dict], Optional[gpd.GeoDataFrame]]:
        """Load GeoJSON file with caching and validation.
        
        Args:
            path: Path to GeoJSON file
            
        Returns:
            Tuple of (geojson_dict, GeoDataFrame) or (None, None) if failed
        """
        path = Path(path)
        path_str = str(path)
        
        # Check cache
        if path_str in self._cache:
            logger.debug(f"Loading from cache: {path.name}")
            return self._cache[path_str]
        
        # Validate file
        if not validate_geojson_file(path):
            return None, None
        
        try:
            # Load as GeoDataFrame
            gdf = gpd.read_file(path)
            
            if gdf.empty:
                logger.warning(f"Empty GeoDataFrame: {path.name}")
                return None, None
            
            # Load as dict
            with open(path, 'r', encoding='utf-8') as f:
                geojson = json.load(f)
            
            # Cache result
            self._cache[path_str] = (geojson, gdf)
            logger.info(f"✅ Loaded {len(gdf)} features from {path.name}")
            
            return geojson, gdf
            
        except Exception as e:
            logger.error(f"Failed to load {path}: {e}")
            return None, None
    
    def ensure_crs(self, gdf: gpd.GeoDataFrame, target_crs: int = 4326) -> gpd.GeoDataFrame:
        """Ensure GeoDataFrame has the correct CRS.
        
        Args:
            gdf: Input GeoDataFrame
            target_crs: Target EPSG code (default: 4326 for WGS84)
            
        Returns:
            GeoDataFrame with correct CRS
        """
        if gdf.crs is None:
            logger.warning("No CRS found, assuming EPSG:4326")
            gdf.set_crs(epsg=target_crs, inplace=True)
        elif gdf.crs.to_epsg() != target_crs:
            logger.debug(f"Reprojecting from {gdf.crs} to EPSG:{target_crs}")
            gdf = gdf.to_crs(epsg=target_crs)
        return gdf
    
    def load_ward_stops(self, folder_path: Union[str, Path]) -> Tuple[gpd.GeoDataFrame, List[Dict]]:
        """Load all ward bus stop files.
        
        Args:
            folder_path: Path to folder containing ward GeoJSON files
            
        Returns:
            Tuple of (combined GeoDataFrame, list of features for search)
        """
        folder_path = Path(folder_path)
        all_gdfs = []
        all_features = []
        
        # Auto-discover all .geojson files if ward_files not specified
        ward_files = self.config.ward_files if self.config.ward_files else []
        
        if not ward_files:
            # Scan folder for all GeoJSON files using os.listdir for better Unicode support
            try:
                for filename in os.listdir(str(folder_path)):
                    if filename.lower().endswith('.geojson'):
                        ward_files.append(filename)
                logger.info(f"📂 Auto-discovered {len(ward_files)} GeoJSON files")
            except Exception as e:
                logger.error(f"❌ Error scanning folder: {e}")
                raise RuntimeError(f"Failed to scan folder: {e}")
        
        for ward_file in ward_files:
            full_path = folder_path / ward_file
            _, gdf = self.load_geojson(str(full_path).replace('\\', '/'))
            
            if gdf is None or gdf.empty:
                continue
            
            # Ensure correct CRS
            gdf = self.ensure_crs(gdf)
            
            # Make JSON-safe
            gdf = make_json_safe(gdf)
            all_gdfs.append(gdf)
            
            # Extract features for search
            for _, row in gdf.iterrows():
                geom = row.geometry
                if geom is None or geom.geom_type != "Point":
                    continue
                
                name = (row.get("name") or row.get("Name") or "").strip()
                if not name:
                    name = f"Stop {len(all_features) + 1}"
                
                lat, lon = geom.y, geom.x
                all_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {"name": name, "ward": ward_file.replace("Phường_", "").replace(".geojson", "").replace("_", " ")}
                })
        
        if not all_gdfs:
            raise RuntimeError("❌ No ward bus stop files found!")
        
        combined = gpd.GeoDataFrame(pd.concat(all_gdfs, ignore_index=True))
        logger.info(f"📊 Total stops loaded: {len(combined)}")
        
        return combined, all_features


class MapBuilder:
    """Builds enhanced Folium map with all features."""
    
    def __init__(self, config: MapConfig):
        self.config = config
        self.loader = GeoDataLoader(config)
        self.map: Optional[folium.Map] = None
        self.stops_gdf: Optional[gpd.GeoDataFrame] = None
        self.features: List[Dict] = []
    
    def create_base_map(self, center: List[float]) -> folium.Map:
        """Create base map with multiple tile layers.
        
        Args:
            center: [lat, lon] for map center
            
        Returns:
            Folium Map object
        """
        m = folium.Map(
            location=center,
            zoom_start=self.config.zoom_start,
            tiles=None,
            prefer_canvas=True
        )
        
        # Add multiple tile layers
        tiles = [
            ("CartoDB Voyager", "🗺️ Vibrant"),
            ("CartoDB Positron", "⚪ Light"),
            ("Esri.WorldImagery", "🛰️ Satellite"),
            ("OpenStreetMap", "🌏 OSM"),
        ]
        
        for tile, name in tiles:
            folium.TileLayer(tile, name=name).add_to(m)
        
        logger.info(f"✅ Base map created with {len(tiles)} tile layers")
        return m
    # ==================== MAP LAYERS ====================
    def add_ward_borders(self) -> None:
        """Add ward border layers to the map."""
        if self.map is None:
            raise RuntimeError("Map not initialized. Call create_base_map first.")
        
        ward_border_folder = Path(self.config.ward_borders_folder)
        if not ward_border_folder.exists():
            ward_border_folder = Path(__file__).parent / self.config.ward_borders_folder
        
        if not ward_border_folder.exists():
            logger.warning(f"Ward borders folder not found: {ward_border_folder}")
            return
        
        for ward_file in self.config.ward_files:
            border_path = ward_border_folder / ward_file
            
            if not border_path.exists():
                logger.warning(f"Border file not found: {ward_file}")
                continue
            
            try:
                gdf_border = gpd.read_file(border_path)
                if gdf_border.empty:
                    continue
                
                gdf_border = self.loader.ensure_crs(gdf_border)
                gdf_border = make_json_safe(gdf_border)
                
                color = self.config.ward_colors.get(ward_file, "#ff7800")
                ward_name = ward_file.replace("Phường_", "").replace(".geojson", "").replace("_", " ")
                
                folium.GeoJson(
                    gdf_border.__geo_interface__,
                    name=f"🗺️ {ward_name}",
                    style_function=lambda feat, col=color: {
                        "color": col,
                        "weight": 2,
                        "fill": True,
                        "fillColor": col,
                        "fillOpacity": 0.15,
                        "opacity": 0.8,
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=["name"] if "name" in gdf_border.columns else [],
                        aliases=["Ward:"] if "name" in gdf_border.columns else []
                    )
                ).add_to(self.map)
                
                logger.info(f"🗺️ Added border: {ward_name}")
                
            except Exception as e:
                logger.error(f"Failed to add border {ward_file}: {e}")
    
    def add_bus_stops(self) -> None:
        """Add bus stops layer with optional clustering."""
        if self.map is None or self.stops_gdf is None:
            raise RuntimeError("Map and stops not initialized.")
        
        if self.config.enable_clustering:
            # Add clustered markers
            marker_cluster = MarkerCluster(
                name="🚌 Bus Stops (Clustered)",
                show=self.config.show_stops_by_default,
                options={
                    'showCoverageOnHover': False,
                    'zoomToBoundsOnClick': True,
                    'spiderfyOnMaxZoom': True,
                    'disableClusteringAtZoom': 16
                }
            ).add_to(self.map)
            
            for feat in self.features:
                coords = feat['geometry']['coordinates']
                props = feat['properties']
                
                # Enhanced popup with more details
                popup_html = f"""
                <div style="font-family: Arial; min-width: 200px;">
                    <h4 style="margin: 0 0 10px 0; color: #d32f2f;">🚌 {props['name']}</h4>
                    <p style="margin: 5px 0;"><b>Ward:</b> {props.get('ward', 'N/A')}</p>
                    <p style="margin: 5px 0;"><b>Coordinates:</b><br>{coords[1]:.6f}, {coords[0]:.6f}</p>
                </div>
                """
                
                # Enhanced tooltip with HTML styling
                tooltip_html = f"""
                <div style="font-family: Arial; font-size: 12px;">
                    <b>🚌 {props['name']}</b><br>
                    <small style="color: #666;">{props.get('ward', 'N/A')}</small>
                </div>
                """
                
                # Build marker and explicitly attach a simple text tooltip (better cross-browser hover)
                marker = folium.Marker(
                    location=[coords[1], coords[0]],
                    popup=folium.Popup(popup_html, max_width=300),
                    icon=folium.Icon(color='red', icon='bus', prefix='fa')
                )
                # Use plain stop name for tooltip (sticky keeps it near cursor)
                marker.add_child(folium.Tooltip(props.get('name', 'Stop'), sticky=True))
                marker.add_to(marker_cluster)
            
            logger.info(f"✅ Added {len(self.features)} clustered bus stop markers")
        else:
            # Add as GeoJSON layer with enhanced tooltip
            def style_function(feature):
                return {
                    'fillColor': 'red',
                    'color': 'darkred',
                    'weight': 2,
                    'fillOpacity': 0.6
                }
            
            search_layer = folium.GeoJson(
                {"type": "FeatureCollection", "features": self.features},
                name="🚌 Bus Stops",
                marker=folium.Circle(radius=5, color='red', fill=True, fillColor='red', fillOpacity=0.6),
                popup=folium.GeoJsonPopup(
                    fields=["name", "ward"],
                    aliases=["🚌 Stop Name:", "📍 Ward:"],
                    localize=True,
                    labels=True,
                    style="background-color: white; font-family: Arial;"
                ),
                tooltip=folium.GeoJsonTooltip(
                    fields=["name", "ward"],
                    aliases=["🚌", "📍"],
                    localize=True,
                    sticky=True,
                    labels=True,
                    style="""
                        background-color: white;
                        border: 2px solid red;
                        border-radius: 3px;
                        box-shadow: 3px 3px 5px rgba(0,0,0,0.3);
                        font-family: Arial;
                        font-size: 12px;
                    """
                ),
                show=self.config.show_stops_by_default
            ).add_to(self.map)
            
            logger.info(f"✅ Added {len(self.features)} bus stops as GeoJSON layer")
    
    def add_bus_routes(self) -> None:
        """Add bus routes layer with spatial filtering."""
        if self.map is None or self.stops_gdf is None:
            raise RuntimeError("Map and stops not initialized.")
        
        # Find routes file
        possible_paths = [
            Path(self.config.folder_path) / self.config.routes_file,
            Path(__file__).parent / self.config.routes_file,
        ]
        
        route_gdf = None
        for route_path in possible_paths:
            if route_path.exists():
                try:
                    route_gdf = gpd.read_file(route_path)
                    route_gdf = self.loader.ensure_crs(route_gdf)
                    route_gdf = make_json_safe(route_gdf)
                    logger.info(f"🚍 Loaded {len(route_gdf)} route features from {route_path.name}")
                    break
                except Exception as e:
                    logger.error(f"Failed to load routes from {route_path}: {e}")
        
        if route_gdf is None or route_gdf.empty:
            logger.warning("No bus routes found")
            return
        
        # Spatial filtering
        try:
            stops_m = self.stops_gdf.to_crs(epsg=3857)
            routes_m = route_gdf.to_crs(epsg=3857)
            
            selected_mask = None
            for radius in self.config.route_buffer_distances:
                buf = stops_m.geometry.buffer(radius)
                # Use union_all() instead of deprecated unary_union
                try:
                    union = buf.union_all()  # New method in geopandas >= 0.13
                except AttributeError:
                    union = buf.unary_union  # Fallback for older versions
                mask = routes_m.geometry.intersects(union)
                if mask.any():
                    selected_mask = mask
                    logger.info(f"🚍 Found {int(mask.sum())}/{len(routes_m)} routes within {radius}m of stops")
                    break
            
            filtered_routes = route_gdf.loc[selected_mask.values] if selected_mask is not None and selected_mask.any() else route_gdf
            
        except Exception as e:
            logger.warning(f"Spatial filtering failed: {e}. Using all routes.")
            filtered_routes = route_gdf
        
        # Find popup field
        popup_field = None
        for col in ('ref', 'name', 'route', 'route_name'):
            if col in filtered_routes.columns:
                popup_field = col
                break
        
        # Add routes to map
        folium.GeoJson(
            filtered_routes.__geo_interface__,
            name='🚍 Bus Routes',
            style_function=lambda feat: {
                'color': '#ff7800',
                'weight': 3,
                'opacity': 0.7,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[popup_field] if popup_field else [],
                aliases=['Route:'] if popup_field else []
            )
        ).add_to(self.map)
        
        logger.info(f"✅ Added {len(filtered_routes)} bus routes")
    
    def add_search(self) -> None:
        """Add search functionality for bus stops."""
        if self.map is None:
            raise RuntimeError("Map not initialized.")
        
        # Create searchable GeoJSON layer
        search_layer = folium.GeoJson(
            {"type": "FeatureCollection", "features": self.features},
            name="🔍 Search Layer",
            show=False  # Hidden layer just for search
        ).add_to(self.map)
        
        # Add search control
        Search(
            layer=search_layer,
            search_label="name",
            placeholder="🔍 Search for bus stop name...",
            collapsed=False,
            search_zoom=self.config.search_zoom,
            position='topright'
        ).add_to(self.map)
        
        logger.info("✅ Added search functionality")
    
    def add_controls(self) -> None:
        """Add map controls (location, minimap, fullscreen, etc.)."""
        if self.map is None:
            raise RuntimeError("Map not initialized.")
        
        # Locate control
        LocateControl(auto_start=False, position='topright').add_to(self.map)
        
        # Fullscreen
        Fullscreen(position='topright').add_to(self.map)
        
        # Measure control
        if self.config.enable_measure:
            MeasureControl(
                position='bottomleft',
                primary_length_unit='meters',
                secondary_length_unit='kilometers',
                primary_area_unit='sqmeters',
                secondary_area_unit='hectares'
            ).add_to(self.map)
        
        # Mini map
        if self.config.enable_minimap:
            MiniMap(toggle_display=True, position='bottomright').add_to(self.map)
        
        # Mouse position
        MousePosition(
            position='bottomleft',
            separator=' | ',
            empty_string='N/A',
            lng_first=False,
            num_digits=6,
            prefix='Coordinates:'
        ).add_to(self.map)
        
        # Layer control
        folium.LayerControl(collapsed=False, position='topright').add_to(self.map)
        
        logger.info("✅ Added all map controls")
    
    def add_statistics_panel(self) -> None:
        """Add statistics panel showing stop counts and coverage."""
        if self.map is None or self.stops_gdf is None:
            raise RuntimeError("Map and stops not initialized.")
        
        if not self.config.enable_statistics:
            return
        # Build statistics content (moved into a modal, triggered by a small button)
        total_stops = len(self.stops_gdf)
        ward_counts = {}
        for feat in self.features:
            ward = feat['properties'].get('ward', 'Unknown')
            ward_counts[ward] = ward_counts.get(ward, 0) + 1

        # Modal + button HTML/CSS/JS
        stats_html = f"""
        <style>
        /* Small floating stats button */
        #stats-btn {{
            position: fixed;
            top: 60px;
            left: 60px;
            z-index: 99999;
            background: #ff7800;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 30px;
            font-weight: bold;
            box-shadow: 0 4px 10px rgba(0,0,0,0.2);
            cursor: pointer;
        }}
        /* Modal backdrop */
        #stats-modal-backdrop {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.4);
            display: none;
            z-index: 99998;
        }}
        /* Modal content */
        #stats-modal {{
            position: fixed;
            top: 110px;
            left: 60px;
            width: 320px;
            max-height: 70vh;
            overflow: auto;
            background: white;
            border-radius: 8px;
            padding: 12px;
            box-shadow: 0 6px 18px rgba(0,0,0,0.3);
            display: none;
            z-index: 99999;
            font-family: Arial, sans-serif;
        }}
        #stats-modal h3 {{ margin: 0 0 8px 0; color: #333; }}
        #stats-modal .close-btn {{ float: right; cursor: pointer; color: #666; }}
        </style>

        <button id="stats-btn" title="Open statistics">📊 Stats</button>
        <div id="stats-modal-backdrop"></div>
        <div id="stats-modal" role="dialog" aria-modal="true">
            <span class="close-btn" id="stats-close">✖</span>
            <h3>📊 Bus Stop Statistics</h3>
            <p><b>Total Stops:</b> {total_stops}</p>
            <p style="margin:6px 0 4px 0;"><b>Stops by Ward:</b></p>
            <ul style="padding-left:18px; margin-top:4px; font-size:13px;">
        """

        for ward, count in sorted(ward_counts.items()):
            safe_ward = ward.replace('"', '&quot;')
            stats_html += f"<li>{safe_ward}: {count}</li>\n"

        stats_html += f"""
            </ul>
            <p style="font-size:11px; color:#666; margin-top:8px;">Last updated: {datetime.now():%Y-%m-%d %H:%M}</p>
        </div>
        """

        # Add JS in a plain triple-quoted string (avoid f-string braces parsing inside JS)
        stats_html += """
        <script>
        (function(){
            var btn = document.getElementById('stats-btn');
            var modal = document.getElementById('stats-modal');
            var backdrop = document.getElementById('stats-modal-backdrop');
            var close = document.getElementById('stats-close');
            function openModal(){ modal.style.display='block'; backdrop.style.display='block'; }
            function closeModal(){ modal.style.display='none'; backdrop.style.display='none'; }
            if(btn){ btn.addEventListener('click', function(e){ e.preventDefault(); if(modal.style.display==='block'){ closeModal(); } else { openModal(); } }); }
            if(close){ close.addEventListener('click', closeModal); }
            if(backdrop){ backdrop.addEventListener('click', closeModal); }
        })();
        </script>
        """

        # Inject into map HTML (button + modal are hidden until triggered)
        self.map.get_root().html.add_child(Element(stats_html))
        logger.info("✅ Added statistics modal + trigger button")
    
    def add_distance_calculator(self) -> None:
        """Add JavaScript for distance calculation from user location."""
        if self.map is None:
            raise RuntimeError("Map not initialized.")
        
        if not self.config.enable_distance_calc:
            return
        
        distance_js = """
        <script>
        // Haversine distance calculation
        function haversine(lat1, lon1, lat2, lon2) {
            const R = 6371e3; // Earth radius in meters
            const phi1 = lat1 * Math.PI / 180;
            const phi2 = lat2 * Math.PI / 180;
            const dphi = (lat2 - lat1) * Math.PI / 180;
            const dlambda = (lon2 - lon1) * Math.PI / 180;
            
            const a = Math.sin(dphi/2) * Math.sin(dphi/2) +
                     Math.cos(phi1) * Math.cos(phi2) *
                     Math.sin(dlambda/2) * Math.sin(dlambda/2);
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            
            return R * c;
        }
        
        // Format distance
        function formatDistance(meters) {
            if (meters < 1000) {
                return meters.toFixed(0) + ' m';
            } else {
                return (meters / 1000).toFixed(2) + ' km';
            }
        }
        
        // Store user location
        window.userLocation = null;
        
        // Listen for location events
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(function() {
                const map = window.dispatchEvent ? document.querySelector('.folium-map') : null;
                if (map && map._leaflet_id) {
                    const leafletMap = window[Object.keys(window).find(key => 
                        window[key] && window[key]._container === map
                    )];
                    
                    if (leafletMap) {
                        leafletMap.on('locationfound', function(e) {
                            window.userLocation = e.latlng;
                            console.log('📍 User location:', e.latlng);
                        });
                    }
                }
            }, 1000);
        });
        </script>
        """
        
        self.map.get_root().html.add_child(Element(distance_js))
        logger.info("✅ Added distance calculator")
    
    def build(self) -> folium.Map:
        """Build complete map with all layers and features.
        
        Returns:
            Complete Folium Map object
        """
        logger.info("=" * 60)
        logger.info("🚀 Starting map generation")
        logger.info("=" * 60)
        
        # Load stops
        self.stops_gdf, self.features = self.loader.load_ward_stops(self.config.folder_path)
        
        # Calculate center
        center = [self.stops_gdf.geometry.y.mean(), self.stops_gdf.geometry.x.mean()]
        logger.info(f"📍 Map center: {center[0]:.6f}, {center[1]:.6f}")
        
        # Create base map
        self.map = self.create_base_map(center)
        
        # Add all layers
        self.add_ward_borders()
        self.add_bus_stops()
        self.add_bus_routes()
        
        # Add features
        self.add_search()
        self.add_controls()
        self.add_statistics_panel()
        self.add_distance_calculator()
        
        logger.info("=" * 60)
        logger.info("✅ Map generation completed successfully")
        logger.info("=" * 60)
        
        return self.map
    
    def save(self, output_path: Optional[str] = None) -> Path:
        """Save map to HTML file.
        
        Args:
            output_path: Output file path (optional, uses config default)
            
        Returns:
            Path to saved file
        """
        if self.map is None:
            raise RuntimeError("Map not built. Call build() first.")
        
        output_path = Path(output_path or self.config.output_path)
        self.map.save(str(output_path))
        logger.info(f"💾 Map saved to: {output_path.absolute()}")
        
        return output_path


# ==================== MAIN FUNCTION ====================

def build_bus_map(folder_path: str, 
                  output_path: str = "hanoi_busmap_enhanced.html",
                  config_file: Optional[str] = None) -> folium.Map:
    """Build enhanced Hanoi bus map.
    
    Args:
        folder_path: Path to folder containing ward GeoJSON files
        output_path: Output HTML file path
        config_file: Optional JSON config file path
        
    Returns:
        Folium Map object
    """
    # Load config
    if config_file and os.path.exists(config_file):
        config = MapConfig.from_json(config_file)
    else:
        config = MapConfig()
    
    # Override paths from arguments
    config.folder_path = folder_path
    config.output_path = output_path
    
    # Build map
    builder = MapBuilder(config)
    m = builder.build()
    builder.save()
    
    return m


# ==================== CLI ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="🚌 Enhanced Hanoi Bus Stop Map Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --folder district_bus_stops
  %(prog)s --folder district_bus_stops --output my_map.html
  %(prog)s --config my_config.json
  %(prog)s --folder district_bus_stops --no-clustering --no-stats
        """
    )
    
    parser.add_argument(
        "--folder", 
        default="district_bus_stops",
        help="Folder containing ward GeoJSON files (default: district_bus_stops)"
    )
    parser.add_argument(
        "--out", "--output",
        default="hanoi_busmap_enhanced.html",
        help="Output HTML file path (default: hanoi_busmap_enhanced.html)"
    )
    parser.add_argument(
        "--config",
        help="JSON configuration file path"
    )
    parser.add_argument(
        "--no-clustering",
        action="store_true",
        help="Disable marker clustering"
    )
    parser.add_argument(
        "--no-stats",
        action="store_true",
        help="Disable statistics panel"
    )
    parser.add_argument(
        "--no-minimap",
        action="store_true",
        help="Disable mini-map"
    )
    parser.add_argument(
        "--show-stops",
        action="store_true",
        help="Show bus stops layer by default"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Load or create config
    if args.config:
        config = MapConfig.from_json(args.config)
    else:
        config = MapConfig()
    
    # Override config with CLI arguments
    config.folder_path = args.folder
    config.output_path = args.out
    config.enable_clustering = not args.no_clustering
    config.enable_statistics = not args.no_stats
    config.enable_minimap = not args.no_minimap
    config.show_stops_by_default = args.show_stops
    
    # Build map
    try:
        builder = MapBuilder(config)
        map_obj = builder.build()
        output_file = builder.save()
        
        print("\n" + "=" * 60)
        print("✅ SUCCESS!")
        print("=" * 60)
        print(f"📁 Output file: {output_file.absolute()}")
        print(f"🌐 Open in browser: file://{output_file.absolute()}")
        print("=" * 60 + "\n")
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)