from flask import Flask, render_template_string, send_from_directory
import os
from bus_map import build_bus_map  # 👈 import your 3-ward version

app = Flask(__name__)

# Folder containing the 3 GeoJSON ward files
WARD_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), "district_bus_stops"))


# Template with an iframe to display the Folium map
TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Hanoi Bus Map (3 Wards)</title>
    <style>
        body, html { margin: 0; padding: 0; height: 100%; }
        iframe { width: 100%; height: 100%; border: none; }
        h1 { text-align: center; font-family: sans-serif; padding: 10px; background: #f0f0f0; margin: 0; }
    </style>
</head>
<body>
    <h1>🚌 Hanoi Bus Stops — 3 Wards</h1>
    <iframe src="/map_embed"></iframe>
</body>
</html>
"""

@app.route("/")
def index():
    """Main page showing embedded map."""
    return render_template_string(TEMPLATE)


@app.route("/map_embed")
def map_embed():
    """Generate and serve the Folium map dynamically."""
    print("🛠 Generating Folium map...")
    folium_map = build_bus_map(WARD_FOLDER)
    return folium_map.get_root().render()


@app.route("/data/<path:filename>")
def data_files(filename):
    """Serve static GeoJSON or support files if needed."""
    return send_from_directory(WARD_FOLDER, filename)


if __name__ == "__main__":
    app.run(debug=True)
