#!/usr/bin/env python3
"""Simple CLI to generate the Hanoi bus stops folium map using map_utils."""
import os
from bus_map import build_map


def main():
    base = os.path.dirname(__file__)
    stops = os.path.join(base, 'hanoi_bus_stops_osm.geojson')
    out = os.path.join(base, 'hanoi_busmap_folium.html')
    print('Generating map...')
    build_map(stops, out)
    print('Map written to', out)


if __name__ == '__main__':
    main()
