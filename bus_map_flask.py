from flask import Flask, render_template_string, send_from_directory, request, jsonify
import os
from bus_map import build_bus_map  # 👈 import your 3-ward version
from bus_routing import BusRoutingEngine

app = Flask(__name__)

# Folder containing the 3 GeoJSON ward files
WARD_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), "district_bus_stops"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STOPS_FILE = os.path.join(BASE_DIR, "hanoi_bus_stops_osm.geojson")
ROUTES_FILE = os.path.join(BASE_DIR, "hanoi_bus_routes_osm.geojson")

# Initialize Router
print("⏳ Initializing Bus Routing Engine...")
router = BusRoutingEngine(STOPS_FILE, ROUTES_FILE)
try:
    router.load_data()
except Exception as e:
    print(f"⚠️ Warning: Could not load routing data on startup: {e}")

# Template with an iframe to display the Folium map and Routing Panel
TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Hanoi Bus Map</title>
    <style>
        body, html { margin: 0; padding: 0; height: 100%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        #map-container { width: 100%; height: 100%; position: relative; }
        iframe { width: 100%; height: 100%; border: none; }
        
        #routing-panel {
            position: absolute;
            top: 120px;
            left: 10px; /* Chuyển sang trái để tránh đè lên Layer Control bên phải */
            width: 320px;
            background: white;
            padding: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            border-radius: 12px;
            z-index: 1000;
            max-height: 80vh;
            overflow-y: auto;
            display: none; /* Ẩn mặc định */
            flex-direction: column;
            transition: all 0.3s ease;
        }
        
        #toggle-btn {
            position: absolute;
            top: 10px;
            left: 60px; /* Chuyển sang trái, nằm cạnh nút Zoom */
            z-index: 1001;
            background: #3498db;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 30px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.2);
            cursor: pointer;
            font-weight: bold;
            font-size: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
            width: auto;
        }
        #toggle-btn:hover { background: #2980b9; transform: translateY(-2px); }

        h2 { margin-top: 0; font-size: 20px; color: #2c3e50; margin-bottom: 15px; display: flex; align-items: center; gap: 10px; justify-content: space-between;}
        .close-btn { background: none; border: none; color: #95a5a6; font-size: 24px; cursor: pointer; padding: 0; width: auto; }
        .close-btn:hover { color: #e74c3c; background: none; }

        .input-group { margin-bottom: 12px; }
        label { display: block; font-size: 12px; color: #7f8c8d; margin-bottom: 4px; }
        input { width: 100%; padding: 10px; box-sizing: border-box; border: 1px solid #bdc3c7; border-radius: 6px; font-size: 14px; transition: border 0.3s; }
        input:focus { border-color: #3498db; outline: none; }
        
        .action-btn { width: 100%; padding: 12px; background: #3498db; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 14px; transition: background 0.3s; }
        .action-btn:hover { background: #2980b9; }
        
        #results { margin-top: 20px; font-size: 14px; border-top: 1px solid #eee; padding-top: 10px; }
        .step { margin-bottom: 15px; padding-left: 15px; border-left: 3px solid #ecf0f1; position: relative; }
        .step:last-child { border-left-color: #27ae60; }
        .step-title { font-weight: bold; color: #34495e; display: block; margin-bottom: 5px; }
        
        .route-badge { 
            display: inline-block; 
            background: #e67e22; 
            color: white; 
            padding: 2px 8px; 
            border-radius: 12px; 
            font-size: 11px; 
            margin-right: 4px; 
            margin-bottom: 4px;
        }
        .error { color: #e74c3c; background: #fadbd8; padding: 10px; border-radius: 6px; }
        .loading { color: #7f8c8d; font-style: italic; text-align: center; }

        /* Autocomplete styles */
        .autocomplete-items {
            position: absolute;
            border: 1px solid #d4d4d4;
            border-bottom: none;
            border-top: none;
            z-index: 99;
            top: 100%;
            left: 0;
            right: 0;
            background-color: #fff;
        }
        .autocomplete-items div {
            padding: 10px;
            cursor: pointer;
            background-color: #fff; 
            border-bottom: 1px solid #d4d4d4; 
        }
        .autocomplete-items div:hover {
            background-color: #e9e9e9; 
        }
        .autocomplete-active {
            background-color: DodgerBlue !important; 
            color: #ffffff; 
        }
        .input-group {
            position: relative; /* Important for autocomplete positioning */
        }
    </style>
</head>
<body>
    <div id="map-container">
        <iframe src="/map_embed" allow="geolocation *"></iframe>
        
        <button id="toggle-btn" onclick="togglePanel()">🚌 Tìm đường</button>

        <div id="routing-panel">
            <h2>
                <span>🚌 Tìm đường xe buýt</span>
                <button class="close-btn" onclick="togglePanel()">×</button>
            </h2>
            
            <div class="input-group">
                <label style="display: flex; justify-content: space-between; align-items: center;">
                    Điểm đi 
                    <button onclick="useCurrentLocation()" style="border:none; background:none; cursor:pointer; color:#3498db; font-size:12px; padding: 0;" title="Dùng vị trí hiện tại">
                        📍 Vị trí hiện tại
                    </button>
                </label>
                <input type="text" id="start" placeholder="Nhập tên trạm đi (VD: Kim Mã)" autocomplete="off">
            </div>
            
            <div class="input-group">
                <label>Điểm đến</label>
                <input type="text" id="end" placeholder="Nhập tên trạm đến (VD: Yên Nghĩa)" autocomplete="off">
            </div>
            
            <button class="action-btn" onclick="findRoute()">🔍 Tìm kiếm lộ trình</button>
            
            <div id="results"></div>
        </div>
    </div>

    <script>
        function useCurrentLocation() {
            const startInput = document.getElementById('start');
            const originalPlaceholder = startInput.placeholder;
            startInput.value = "";
            startInput.placeholder = "⏳ Đang lấy vị trí từ bản đồ...";
            
            // Tìm iframe và window của nó
            const iframe = document.querySelector('iframe');
            const iframeWin = iframe.contentWindow;
            
            if (!iframeWin || !iframeWin.L) {
                alert("Bản đồ chưa tải xong. Vui lòng thử lại sau giây lát.");
                startInput.placeholder = originalPlaceholder;
                return;
            }

            // Tìm đối tượng bản đồ Leaflet trong iframe
            let mapInstance = null;
            for (let key in iframeWin) {
                if (iframeWin.hasOwnProperty(key) && iframeWin[key] instanceof iframeWin.L.Map) {
                    mapInstance = iframeWin[key];
                    break;
                }
            }

            if (!mapInstance) {
                alert("Không tìm thấy đối tượng bản đồ.");
                startInput.placeholder = originalPlaceholder;
                return;
            }

            // Lắng nghe sự kiện tìm thấy vị trí
            function onLocationFound(e) {
                const lat = e.latlng.lat;
                const lon = e.latlng.lng;
                
                // Tự động di chuyển map đến vị trí (thay vì setView: true trong locate)
                mapInstance.flyTo(e.latlng, 16);
                
                // Gọi API tìm trạm gần nhất
                fetch(`/find_nearest_stop?lat=${lat}&lon=${lon}`)
                    .then(response => response.json())
                    .then(data => {
                        if (Array.isArray(data) && data.length > 0) {
                            startInput.placeholder = originalPlaceholder;
                            startInput.focus();
                            
                            // Hiển thị danh sách gợi ý
                            closeAllLists();
                            
                            const a = document.createElement("DIV");
                            a.setAttribute("id", startInput.id + "autocomplete-list");
                            a.setAttribute("class", "autocomplete-items");
                            startInput.parentNode.appendChild(a);
                            
                            data.forEach(name => {
                                const b = document.createElement("DIV");
                                b.innerHTML = "<strong>📍 " + name + "</strong>";
                                b.innerHTML += "<input type='hidden' value='" + name + "'>";
                                b.addEventListener("click", function(e) {
                                    startInput.value = this.getElementsByTagName("input")[0].value;
                                    closeAllLists();
                                });
                                a.appendChild(b);
                            });
                            
                        } else {
                            alert("Không tìm thấy trạm nào gần bạn.");
                            startInput.placeholder = originalPlaceholder;
                        }
                    })
                    .catch(err => {
                        console.error(err);
                        alert("Lỗi khi tìm trạm gần nhất.");
                        startInput.placeholder = originalPlaceholder;
                    });
                
                // Xóa sự kiện để tránh gọi lại nhiều lần
                mapInstance.off('locationfound', onLocationFound);
                mapInstance.off('locationerror', onLocationError);
            }

            function onLocationError(e) {
                // Alert lỗi thay vì fallback
                alert("Không thể lấy vị trí (Lỗi: " + e.message + "). Vui lòng kiểm tra quyền truy cập vị trí.");
                startInput.placeholder = originalPlaceholder;
                mapInstance.off('locationfound', onLocationFound);
                mapInstance.off('locationerror', onLocationError);
            }

            mapInstance.on('locationfound', onLocationFound);
            mapInstance.on('locationerror', onLocationError);

            // Kích hoạt tìm vị trí
            // setView: false để ngăn Leaflet tự động zoom ra toàn cầu khi lỗi (fallback behavior)
            mapInstance.locate({setView: false, maxZoom: 16, enableHighAccuracy: true});
        }

        // Hàm đóng danh sách autocomplete (được đưa ra ngoài để dùng chung)
        function closeAllLists(elmnt) {
            var x = document.getElementsByClassName("autocomplete-items");
            for (var i = 0; i < x.length; i++) {
                if (elmnt != x[i] && (elmnt ? elmnt.id != "start" && elmnt.id != "end" : true)) {
                    x[i].parentNode.removeChild(x[i]);
                }
            }
        }
        
        document.addEventListener("click", function (e) {
            closeAllLists(e.target);
        });

        function autocomplete(inp) {
            var currentFocus;
            inp.addEventListener("input", function(e) {
                var a, b, i, val = this.value;
                closeAllLists();
                if (!val) { return false;}
                currentFocus = -1;
                a = document.createElement("DIV");
                a.setAttribute("id", this.id + "autocomplete-list");
                a.setAttribute("class", "autocomplete-items");
                this.parentNode.appendChild(a);
                
                // Gọi API để lấy gợi ý
                fetch(`/search_stops?q=${encodeURIComponent(val)}`)
                    .then(response => response.json())
                    .then(arr => {
                        // Xóa danh sách cũ nếu API trả về chậm
                        a.innerHTML = '';
                        for (i = 0; i < arr.length; i++) {
                            b = document.createElement("DIV");
                            // Highlight phần trùng khớp
                            let name = arr[i];
                            let matchIndex = name.toLowerCase().indexOf(val.toLowerCase());
                            if (matchIndex >= 0) {
                                b.innerHTML = name.substr(0, matchIndex);
                                b.innerHTML += "<strong>" + name.substr(matchIndex, val.length) + "</strong>";
                                b.innerHTML += name.substr(matchIndex + val.length);
                            } else {
                                b.innerHTML = name;
                            }
                            
                            b.innerHTML += "<input type='hidden' value='" + name + "'>";
                            b.addEventListener("click", function(e) {
                                inp.value = this.getElementsByTagName("input")[0].value;
                                closeAllLists();
                            });
                            a.appendChild(b);
                        }
                    });
            });
            
            inp.addEventListener("keydown", function(e) {
                var x = document.getElementById(this.id + "autocomplete-list");
                if (x) x = x.getElementsByTagName("div");
                if (e.keyCode == 40) { // DOWN
                    currentFocus++;
                    addActive(x);
                } else if (e.keyCode == 38) { // UP
                    currentFocus--;
                    addActive(x);
                } else if (e.keyCode == 13) { // ENTER
                    e.preventDefault();
                    if (currentFocus > -1) {
                        if (x) x[currentFocus].click();
                    }
                }
            });
            
            function addActive(x) {
                if (!x) return false;
                removeActive(x);
                if (currentFocus >= x.length) currentFocus = 0;
                if (currentFocus < 0) currentFocus = (x.length - 1);
                x[currentFocus].classList.add("autocomplete-active");
            }
            
            function removeActive(x) {
                for (var i = 0; i < x.length; i++) {
                    x[i].classList.remove("autocomplete-active");
                }
            }
        }

        // Kích hoạt autocomplete cho 2 ô input
        autocomplete(document.getElementById("start"));
        autocomplete(document.getElementById("end"));

        function togglePanel() {
            const panel = document.getElementById('routing-panel');
            const btn = document.getElementById('toggle-btn');
            if (panel.style.display === 'none' || panel.style.display === '') {
                panel.style.display = 'flex';
                btn.style.display = 'none'; // Ẩn nút mở khi panel hiện
            } else {
                panel.style.display = 'none';
                btn.style.display = 'flex'; // Hiện nút mở khi panel ẩn
            }
        }

        async function findRoute() {
            const start = document.getElementById('start').value;
            const end = document.getElementById('end').value;
            const resultsDiv = document.getElementById('results');
            
            if (!start || !end) {
                resultsDiv.innerHTML = '<p class="error">⚠️ Vui lòng nhập cả điểm đi và điểm đến.</p>';
                return;
            }

            resultsDiv.innerHTML = '<p class="loading">⏳ Đang tính toán lộ trình tối ưu...</p>';

            try {
                const response = await fetch(`/find_route?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
                const data = await response.json();

                if (data.error) {
                    resultsDiv.innerHTML = `<p class="error">❌ ${data.error}</p>`;
                } else {
                    // 1. Hiển thị hướng dẫn chi tiết (theo chặng)
                    let html = `<p style="color: #27ae60; font-weight: bold;">🎉 Tìm thấy lộ trình:</p>`;
                    
                    data.path.forEach((segment, index) => {
                        html += `<div class="step">`;
                        html += `<span class="step-title">Chặng ${index + 1}: Đi tuyến <span class="route-badge">${segment.route}</span></span>`;
                        html += `<div style="font-size: 13px; margin-top: 4px;">`;
                        html += `📍 <b>${segment.start_stop}</b> <br>`;
                        html += `⬇ (qua ${segment.num_stops} trạm) <br>`;
                        html += `🏁 <b>${segment.end_stop}</b>`;
                        html += `</div>`;
                        html += `</div>`;
                    });
                    
                    html += `<div style="color: #27ae60; font-size: 12px; text-align: center; margin-top: 10px;">🏁 Đã đến nơi</div>`;
                    
                    resultsDiv.innerHTML = html;

                    // 2. Vẽ đường lên bản đồ (trong iframe)
                    if (data.geometry && data.geometry.length > 0) {
                        drawRouteOnMap(data.geometry, data.path);
                    }
                }
            } catch (err) {
                resultsDiv.innerHTML = '<p class="error">❌ Lỗi kết nối đến server.</p>';
                console.error(err);
            }
        }

        function drawRouteOnMap(coords, segments) {
            const iframe = document.querySelector('iframe');
            const iframeWindow = iframe.contentWindow;

            // Tìm đối tượng bản đồ Leaflet trong iframe
            let mapInstance = null;
            for (const key in iframeWindow) {
                if (iframeWindow[key] && iframeWindow[key].removeLayer && iframeWindow[key].fitBounds) {
                    mapInstance = iframeWindow[key];
                    break;
                }
            }

            if (mapInstance) {
                const L = iframeWindow.L;
                if (!L) return;

                // Xóa đường cũ nếu có
                if (iframeWindow.currentRouteLayer) {
                    mapInstance.removeLayer(iframeWindow.currentRouteLayer);
                }
                // Xóa các marker cũ
                if (iframeWindow.currentMarkers) {
                    iframeWindow.currentMarkers.forEach(m => mapInstance.removeLayer(m));
                }
                iframeWindow.currentMarkers = [];

                // Vẽ đường mới màu xanh dương
                iframeWindow.currentRouteLayer = L.polyline(coords, {
                    color: 'blue',
                    weight: 5,
                    opacity: 0.7
                }).addTo(mapInstance);

                // Vẽ marker cho các điểm chuyển tuyến (Start/End của mỗi segment)
                if (segments && segments.length > 0) {
                    segments.forEach((seg, index) => {
                        console.log(`Adding marker ${index}:`, seg.start_lat, seg.start_lon);
                        
                        // Marker cho điểm bắt đầu của chặng
                        let markerTitle = "";
                        let popupContent = "";
                        let iconHtml = "";

                        if (index === 0) {
                            markerTitle = "Xuất phát";
                            popupContent = `<b>🚩 Xuất phát:</b> ${seg.start_stop}<br>🚌 Lên tuyến: <b>${seg.route}</b>`;
                            // Icon màu xanh lá
                            iconHtml = `<div style="background-color: #2ecc71; width: 12px; height: 12px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.3);"></div>`;
                        } else {
                            markerTitle = "Chuyển tuyến";
                            popupContent = `<b>🔄 Chuyển tuyến:</b> ${seg.start_stop}<br>🚌 Lên tuyến: <b>${seg.route}</b>`;
                            // Icon màu cam
                            iconHtml = `<div style="background-color: #e67e22; width: 12px; height: 12px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.3);"></div>`;
                        }

                        const customIcon = L.divIcon({
                            className: 'custom-div-icon',
                            html: iconHtml,
                            iconSize: [16, 16],
                            iconAnchor: [8, 8]
                        });

                        const marker = L.marker([seg.start_lat, seg.start_lon], {title: markerTitle, icon: customIcon})
                            .addTo(mapInstance)
                            .bindPopup(popupContent);
                        
                        if (index === 0) marker.openPopup();
                        iframeWindow.currentMarkers.push(marker);

                        // Thêm mũi tên chỉ hướng (Text label trên đường)
                        // Lấy điểm giữa của chặng để đặt nhãn tên tuyến
                        // Đây là cách đơn giản để hiển thị "Hướng đi"
                        const midLabel = L.marker([seg.start_lat, seg.start_lon], {
                            icon: L.divIcon({
                                className: 'route-label',
                                html: `<div style="background: white; padding: 2px 5px; border: 1px solid #3498db; border-radius: 4px; font-size: 10px; color: #3498db; white-space: nowrap; box-shadow: 0 1px 3px rgba(0,0,0,0.2);">➡ ${seg.route}</div>`,
                                iconSize: [60, 20],
                                iconAnchor: [-20, 20] // Offset một chút để không che marker
                            })
                        }).addTo(mapInstance);
                        iframeWindow.currentMarkers.push(midLabel);


                        // Nếu là chặng cuối, thêm marker cho điểm kết thúc
                        if (index === segments.length - 1) {
                             const endIconHtml = `<div style="background-color: #e74c3c; width: 12px; height: 12px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.3);"></div>`;
                             const endIcon = L.divIcon({
                                className: 'custom-div-icon',
                                html: endIconHtml,
                                iconSize: [16, 16],
                                iconAnchor: [8, 8]
                            });

                             const endMarker = L.marker([seg.end_lat, seg.end_lon], {title: "Đích đến", icon: endIcon})
                                .addTo(mapInstance)
                                .bindPopup(`<b>🏁 Đích đến:</b> ${seg.end_stop}`);
                            iframeWindow.currentMarkers.push(endMarker);
                        }
                    });
                }

                // Zoom bản đồ để thấy toàn bộ lộ trình
                mapInstance.fitBounds(iframeWindow.currentRouteLayer.getBounds(), {padding: [50, 50]});
            }
        }
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    """Main page showing embedded map."""
    return render_template_string(TEMPLATE)


@app.route("/find_route")
def find_route():
    """API endpoint to find route between two stops."""
    start_stop = request.args.get('start')
    end_stop = request.args.get('end')
    
    if not start_stop or not end_stop:
        return jsonify({"error": "Missing start or end stop"}), 400
        
    path, geom, error = router.find_shortest_path(start_stop, end_stop)
    
    if error:
        return jsonify({"error": error})
    
    return jsonify({"path": path, "geometry": geom})


@app.route("/search_stops")
def search_stops():
    """API endpoint to search for stops by name."""
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify([])
    
    # Tìm kiếm trong stops_gdf của router
    if router.stops_gdf is None:
        return jsonify([])
        
    # Lọc các trạm có tên chứa query
    matches = router.stops_gdf[router.stops_gdf['name'].str.lower().str.contains(query, na=False)]
    
    # Lấy danh sách tên duy nhất (để tránh trùng lặp) và giới hạn số lượng
    results = matches['name'].unique().tolist()[:10]
    
    return jsonify(results)


@app.route("/find_nearest_stop")
def find_nearest_stop():
    """API endpoint to find the nearest stop to a given lat/lon."""
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    
    if lat is None or lon is None:
        return jsonify({"error": "Missing lat or lon"}), 400
        
    try:
        # Trả về danh sách các trạm gần nhất
        stop_names = router.find_nearest_stop(lat, lon)
        return jsonify(stop_names)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
