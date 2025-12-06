import json
import os
import networkx as nx
import geopandas as gpd
from shapely.geometry import LineString, Point, MultiLineString
from shapely.ops import substring, linemerge
import pandas as pd
import warnings

# Tắt cảnh báo của pandas/geopandas để output sạch hơn
warnings.filterwarnings("ignore")

class BusRoutingEngine:
    def __init__(self, stops_file, routes_file):
        self.stops_file = stops_file
        self.routes_file = routes_file
        self.graph = nx.DiGraph()
        self.stops_gdf = None
        self.routes_gdf = None
        self.is_built = False
        self.route_to_stops = {}  # Map: route_name -> list of stop_ids
        self.max_walk_distance_m = 120  # Khoảng cách tối đa để tạo kết nối đi bộ
        self.side_eps = 0.0001          # Bước lấy hướng tuyến để xác định bên đường

    def find_nearest_stop(self, lat, lon, limit=5):
        """Tìm trạm xe buýt gần nhất với tọa độ (lat, lon)"""
        if self.stops_gdf is None:
            self.load_data()
            
        # Tạo điểm từ tọa độ (Lưu ý: GeoJSON dùng lon, lat)
        point = Point(lon, lat)
        
        # Tính khoảng cách đến tất cả các trạm (đơn vị độ)
        # Để tối ưu, có thể dùng sindex nearest, nhưng với số lượng trạm nhỏ (<5000) thì tính hết cũng nhanh
        distances = self.stops_gdf.geometry.distance(point)
        
        # Lấy top 'limit' trạm gần nhất
        nearest_indices = distances.nsmallest(limit).index
        nearest_stops = self.stops_gdf.loc[nearest_indices]
        
        # Trả về danh sách tên trạm (unique để tránh trùng lặp)
        return nearest_stops['name'].unique().tolist()

    def load_data(self):
        """Đọc dữ liệu GeoJSON"""
        print("⏳ Đang đọc dữ liệu...")
        if os.path.exists(self.stops_file) and os.path.exists(self.routes_file):
            self.stops_gdf = gpd.read_file(self.stops_file)
            self.routes_gdf = gpd.read_file(self.routes_file)
            print(f"✅ Đã tải {len(self.stops_gdf)} trạm và {len(self.routes_gdf)} tuyến.")
            print(f"DEBUG: Columns in routes_gdf: {self.routes_gdf.columns}")
            if not self.routes_gdf.empty:
                print(f"DEBUG: Sample route: {self.routes_gdf.iloc[0].drop('geometry').to_dict()}")
        else:
            raise FileNotFoundError("Không tìm thấy file dữ liệu GeoJSON.")

    def build_graph(self):
        """
        Xây dựng đồ thị mạng lưới xe buýt.
        Do dữ liệu không có liên kết trạm-tuyến, ta phải dùng không gian để tính toán.
        """
        if self.stops_gdf is None:
            self.load_data()

        # Đặt lại đồ thị mỗi lần build để tránh cộng dồn các cạnh cũ
        self.graph = nx.DiGraph()
        self.route_to_stops = {}
        self.is_built = False

        print("⏳ Đang xây dựng đồ thị tuyến (có thể mất vài giây)...")
        
        # Tạo chỉ mục không gian (Spatial Index) để truy vấn nhanh
        sindex = self.stops_gdf.sindex

        # Duyệt qua từng tuyến xe buýt
        for idx, route in self.routes_gdf.iterrows():
            route_geom = route.geometry
            
            # Xử lý MultiLineString: cố gắng gộp thành 1 LineString
            if route_geom.geom_type == 'MultiLineString':
                try:
                    merged = linemerge(route_geom)
                    if merged.geom_type == 'LineString':
                        route_geom = merged
                    else:
                        # Nếu không gộp được (do đứt đoạn), lấy đoạn dài nhất hoặc đoạn đầu tiên
                        # Để đơn giản, ta lấy đoạn dài nhất
                        route_geom = max(route_geom.geoms, key=lambda x: x.length)
                except Exception:
                    # Fallback nếu lỗi
                    pass

            if route_geom.geom_type != 'LineString':
                continue

            route_name = route.get('name', f"Route {route.get('id')}")
            
            # 1. Tìm các trạm nằm gần tuyến đường này (buffer khoảng 0.0003 độ ~ 30-40m)
            # Dùng bounding box để lọc sơ bộ trước
            possible_matches_index = list(sindex.intersection(route_geom.bounds))
            possible_matches = self.stops_gdf.iloc[possible_matches_index]
            
            # Lọc chính xác bằng khoảng cách (distance)
            # Lưu ý: Đây là tính toán trên hệ tọa độ phẳng (độ), chỉ mang tính tương đối
            # Giảm buffer xuống 0.0003 (~30m) để tránh bắt nhầm trạm ở đường song song hoặc chiều về
            stops_near_route = possible_matches[possible_matches.distance(route_geom) < 0.0003].copy()

            if stops_near_route.empty:
                continue

            # Xác định bên đường theo hướng tuyến để loại bỏ trạm ngược chiều
            stops_near_route["side"] = stops_near_route.geometry.apply(lambda g: self._compute_side(route_geom, g))
            nonzero = stops_near_route[stops_near_route["side"].abs() > 1e-9]
            if not nonzero.empty:
                pos_count = (nonzero["side"] > 0).sum()
                neg_count = (nonzero["side"] < 0).sum()
                dominant_sign = 1 if pos_count >= neg_count else -1
                filtered = stops_near_route[stops_near_route["side"] * dominant_sign > 1e-9]
                if len(filtered) >= 2:
                    stops_near_route = filtered
            stops_near_route = stops_near_route.drop(columns=["side"])

            # 2. Sắp xếp các trạm theo thứ tự xuất hiện trên tuyến đường
            # Project trạm lên đường thẳng để lấy khoảng cách từ điểm đầu
            stops_near_route['pos_on_line'] = stops_near_route.geometry.apply(lambda x: route_geom.project(x))
            stops_sorted = stops_near_route.sort_values('pos_on_line')

            # 3. Tạo cạnh nối các trạm liên tiếp
            stop_ids = stops_sorted['id'].tolist()
            self.route_to_stops[route_name] = stop_ids # Lưu danh sách trạm của tuyến để tìm đường thẳng
            stop_names = stops_sorted['name'].tolist()
            
            for i in range(len(stop_ids) - 1):
                u = stop_ids[i]
                v = stop_ids[i+1]
                
                # Tính khoảng cách giữa 2 trạm (đơn vị xấp xỉ mét hoặc độ)
                # Ở đây dùng độ dài trên line làm trọng số (weight)
                start_dist = stops_sorted.iloc[i]['pos_on_line']
                end_dist = stops_sorted.iloc[i+1]['pos_on_line']
                dist = end_dist - start_dist
                
                # Thêm cạnh vào đồ thị
                # Nếu đã có cạnh, giữ lại cạnh ngắn nhất hoặc thêm thông tin tuyến
                if self.graph.has_edge(u, v):
                    self.graph[u][v]['routes'].append(route_name)
                else:
                    # Cắt lấy đoạn đường thực tế giữa 2 trạm
                    segment_geom = substring(route_geom, start_dist, end_dist)
                    self.graph.add_edge(u, v, weight=dist, routes=[route_name], geometry=segment_geom)
                    
                # Cập nhật thông tin node (tên, tọa độ)
                # Lưu ý: add_edge tự động tạo node nếu chưa có, nhưng không có thuộc tính
                # Nên ta cần cập nhật thuộc tính cho node dù nó đã tồn tại hay chưa
                self.graph.add_node(u, name=stop_names[i], pos=(stops_sorted.iloc[i].geometry.x, stops_sorted.iloc[i].geometry.y))
                self.graph.add_node(v, name=stop_names[i+1], pos=(stops_sorted.iloc[i+1].geometry.x, stops_sorted.iloc[i+1].geometry.y))

        # Thêm kết nối đi bộ giữa các trạm gần nhau (ví dụ: trạm ở hai bên đường)
        bus_edge_count = self.graph.number_of_edges()
        self._add_walking_edges()
        total_edge_count = self.graph.number_of_edges()

        self.is_built = True
        added_walk_edges = total_edge_count - bus_edge_count
        print(f"✅ Đã xây dựng đồ thị với {self.graph.number_of_nodes()} trạm và {total_edge_count} kết nối (thêm {added_walk_edges} kết nối đi bộ).")

    def _ensure_node(self, stop_row):
        """Đảm bảo node tồn tại trong graph với thông tin tọa độ/tên."""
        self.graph.add_node(
            stop_row['id'],
            name=stop_row.get('name', 'Unknown'),
            pos=(stop_row.geometry.x, stop_row.geometry.y)
        )

    def _add_walk_edge(self, u, v, dist, geom):
        """Thêm cạnh đi bộ hai chiều nếu chưa tồn tại cạnh cùng chiều."""
        if self.graph.has_edge(u, v):
            return
        self.graph.add_edge(u, v, weight=dist, routes=["WALK"], geometry=geom)

    def _add_walking_edges(self):
        """Tự động tạo kết nối đi bộ giữa các trạm gần nhau (đổi hướng tùy ý)."""
        if self.stops_gdf is None:
            return

        # 1 độ ~ 111km. Giới hạn 120m -> khoảng 0.00108 độ
        walk_threshold_deg = self.max_walk_distance_m / 111_000
        sindex = self.stops_gdf.sindex
        processed_pairs = set()

        for idx, stop in self.stops_gdf.iterrows():
            stop_geom = stop.geometry
            candidate_idx = list(sindex.intersection(stop_geom.buffer(walk_threshold_deg).bounds))

            for cand_idx in candidate_idx:
                if cand_idx == idx:
                    continue

                pair_key = tuple(sorted((idx, cand_idx)))
                if pair_key in processed_pairs:
                    continue

                neighbor = self.stops_gdf.iloc[cand_idx]
                neighbor_geom = neighbor.geometry
                distance = stop_geom.distance(neighbor_geom)

                if 0 < distance <= walk_threshold_deg:
                    processed_pairs.add(pair_key)

                    # Đảm bảo node tồn tại và thêm cạnh đi bộ 2 chiều
                    self._ensure_node(stop)
                    self._ensure_node(neighbor)
                    walk_geom = LineString([stop_geom, neighbor_geom])
                    self._add_walk_edge(stop['id'], neighbor['id'], distance, walk_geom)
                    self._add_walk_edge(neighbor['id'], stop['id'], distance, walk_geom)

    def _label_route(self, routes_set):
        """Chọn tên tuyến để hiển thị, ưu tiên tuyến bus, fallback sang 'đi bộ'."""
        if not routes_set:
            return "Unknown"

        bus_routes = sorted([r for r in routes_set if r != "WALK"])
        if bus_routes:
            return bus_routes[0]

        return "🚶 Đi bộ"

    def _compute_side(self, route_geom, stop_geom):
        """Tính dấu xác định trạm nằm bên trái/phải tuyến (theo hướng tuyến)."""
        total_len = route_geom.length
        if total_len == 0:
            return 0.0

        proj_dist = route_geom.project(stop_geom)
        eps = min(self.side_eps, total_len * 0.01)
        if eps == 0:
            return 0.0

        t0 = max(0.0, proj_dist - eps)
        t1 = min(total_len, proj_dist + eps)
        if t1 == t0:
            return 0.0

        p0 = route_geom.interpolate(t0)
        p1 = route_geom.interpolate(t1)
        direction = (p1.x - p0.x, p1.y - p0.y)

        # Offset từ điểm trên tuyến đến trạm
        offset = (stop_geom.x - p0.x, stop_geom.y - p0.y)
        cross = direction[0] * offset[1] - direction[1] * offset[0]
        return cross

    def find_shortest_path(self, start_name, end_name):
        """Tìm đường đi ngắn nhất giữa 2 tên trạm (tìm kiếm gần đúng)"""
        if not self.is_built:
            self.build_graph()

        # Tìm ID trạm dựa trên tên (gần đúng)
        start_nodes = []
        end_nodes = []
        
        # Chuẩn hóa tên để tìm kiếm
        start_name_lower = start_name.lower()
        end_name_lower = end_name.lower()

        for node, data in self.graph.nodes(data=True):
            node_name = data.get('name', '')
            if start_name_lower in node_name.lower():
                start_nodes.append(node)
            if end_name_lower in node_name.lower():
                end_nodes.append(node)
        
        if not start_nodes:
            return None, None, f"Không tìm thấy trạm khởi hành nào khớp với '{start_name}'"
        if not end_nodes:
            return None, None, f"Không tìm thấy trạm đích nào khớp với '{end_name}'"

        # --- Ưu tiên 1: Tìm tuyến đi thẳng ---
        path_ids = None
        for s in start_nodes:
            for e in end_nodes:
                if s == e: continue
                for r_name, stops in self.route_to_stops.items():
                    if s in stops and e in stops:
                        idx_s = stops.index(s)
                        idx_e = stops.index(e)
                        if idx_s < idx_e:
                            p = stops[idx_s : idx_e + 1]
                            if path_ids is None or len(p) < len(path_ids):
                                path_ids = p
                                print(f"✨ Tìm thấy tuyến thẳng: {r_name}")

        # Fallback cho Dijkstra (Tìm đường ngắn nhất trong tất cả các cặp điểm start/end)
        if path_ids is None:
            shortest_path = None
            shortest_len = float('inf')
            
            for s in start_nodes:
                for e in end_nodes:
                    if s == e: continue
                    try:
                        p = nx.shortest_path(self.graph, source=s, target=e, weight='weight')
                        # Tính tổng trọng số (độ dài) thực tế
                        # Lưu ý: weight trong graph là khoảng cách
                        path_len = nx.shortest_path_length(self.graph, source=s, target=e, weight='weight')
                        
                        if path_len < shortest_len:
                            shortest_len = path_len
                            shortest_path = p
                    except nx.NetworkXNoPath:
                        continue
            
            path_ids = shortest_path

        try:
            if path_ids is None:
                return None, None, "Không tìm thấy lộ trình nào kết nối hai điểm này."

            # Chuẩn hóa về số nguyên Python để JSON hóa không lỗi
            path_ids = [int(n) for n in path_ids]
            
            # Xây dựng kết quả chi tiết (Gộp các trạm thành các chặng - Segments)
            segments = []
            full_geometry_coords = []

            if len(path_ids) > 1:
                # Khởi tạo chặng đầu tiên
                u = path_ids[0]
                v = path_ids[1]
                edge_data = self.graph.get_edge_data(u, v)
                current_routes = set(edge_data.get('routes', []))
                current_segment_stops = [u, v]
                segment_start_node = u

                # Duyệt qua các cạnh tiếp theo để gộp
                for i in range(1, len(path_ids) - 1):
                    u = path_ids[i]
                    v = path_ids[i+1]
                    edge_data = self.graph.get_edge_data(u, v)
                    next_edge_routes = set(edge_data.get('routes', []))
                    
                    intersection = current_routes.intersection(next_edge_routes)
                    
                    if intersection:
                        # Vẫn đi được trên cùng tuyến (hoặc một trong các tuyến chung)
                        current_routes = intersection
                        current_segment_stops.append(v)
                    else:
                        # Phải chuyển tuyến
                        # Kết thúc chặng hiện tại
                        route_name = self._label_route(current_routes)
                        start_data = self.graph.nodes[segment_start_node]
                        end_data = self.graph.nodes[u]
                        start_pos = start_data.get('pos', (0, 0))
                        end_pos = end_data.get('pos', (0, 0))
                        
                        segments.append({
                            "start_stop": start_data.get('name', 'Unknown'),
                            "end_stop": end_data.get('name', 'Unknown'),
                            "start_lat": float(start_pos[1]),
                            "start_lon": float(start_pos[0]),
                            "end_lat": float(end_pos[1]),
                            "end_lon": float(end_pos[0]),
                            "route": route_name,
                            "num_stops": len(current_segment_stops) - 1,
                            "stops": [int(s) for s in current_segment_stops]
                        })
                        
                        # Bắt đầu chặng mới
                        current_routes = next_edge_routes
                        current_segment_stops = [u, v]
                        segment_start_node = u

                # Thêm chặng cuối cùng
                if current_segment_stops:
                    route_name = self._label_route(current_routes)
                    start_data = self.graph.nodes[segment_start_node]
                    end_data = self.graph.nodes[path_ids[-1]]
                    start_pos = start_data.get('pos', (0, 0))
                    end_pos = end_data.get('pos', (0, 0))

                    segments.append({
                        "start_stop": start_data.get('name', 'Unknown'),
                        "end_stop": end_data.get('name', 'Unknown'),
                        "start_lat": float(start_pos[1]),
                        "start_lon": float(start_pos[0]),
                        "end_lat": float(end_pos[1]),
                        "end_lon": float(end_pos[0]),
                        "route": route_name,
                        "num_stops": len(current_segment_stops) - 1,
                        "stops": [int(s) for s in current_segment_stops]
                    })

            # Xây dựng geometry (giữ nguyên logic cũ để vẽ đường)
            for i in range(len(path_ids) - 1):
                node_id = path_ids[i]
                next_id = path_ids[i+1]
                edge_data = self.graph.get_edge_data(node_id, next_id)
                
                if 'geometry' in edge_data:
                    geom = edge_data['geometry']
                    if geom.geom_type == 'LineString':
                        coords = list(geom.coords)
                        latlon_coords = [[c[1], c[0]] for c in coords]
                        full_geometry_coords.extend(latlon_coords)
                else:
                    node_data = self.graph.nodes[node_id]
                    pos = node_data.get('pos', (0, 0))
                    full_geometry_coords.append([pos[1], pos[0]])
                    next_node_data = self.graph.nodes[next_id]
                    next_pos = next_node_data.get('pos', (0, 0))
                    full_geometry_coords.append([next_pos[1], next_pos[0]])
                
            return segments, full_geometry_coords, None
            
        except nx.NetworkXNoPath:
            return None, None, "Không tìm thấy đường đi giữa hai trạm này (có thể không có tuyến nối)."

# --- Phần chạy thử (Main) ---
if __name__ == "__main__":
    # Đường dẫn file (cập nhật theo môi trường của bạn)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    STOPS_FILE = os.path.join(BASE_DIR, "hanoi_bus_stops_osm.geojson")
    ROUTES_FILE = os.path.join(BASE_DIR, "hanoi_bus_routes_osm.geojson")

    router = BusRoutingEngine(STOPS_FILE, ROUTES_FILE)
    
    # Thử tìm đường
    print("\n--- TEST TÌM ĐƯỜNG ---")
    start_query = "Kim Mã" 
    end_query = "Yên Nghĩa"
    
    print(f"Tìm đường từ '{start_query}' đến '{end_query}'...")
    path, geom, error = router.find_shortest_path(start_query, end_query)
    
    if error:
        print(f"Lỗi: {error}")
    else:
        print(f"🎉 Tìm thấy lộ trình qua {len(path)} chặng:")
        print(f"📍 Tổng số điểm vẽ trên bản đồ: {len(geom)}")
        for step in path:
            print(f" 🚌 Đi tuyến {step['route']} từ '{step['start_stop']}' đến '{step['end_stop']}' ({step['num_stops']} trạm)")
