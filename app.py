import streamlit as st
import folium
from folium.plugins import MarkerCluster
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import requests
from datetime import datetime, timedelta
from streamlit_folium import folium_static

# ---------------------------
# Config
# ---------------------------
OSRM_URL = "http://router.project-osrm.org/route/v1/driving"
geolocator = Nominatim(user_agent="smart_ev_navigator")
OPENCHARGEMAP_KEY = "931d4ae3-014a-4ac1-8c4c-d1aa244c42de"

DEFAULT_EV_RANGE_KM = 300
AVERAGE_SPEED_KMH = 50
LOW_BATTERY_THRESHOLD = 0.25  # 25%

st.set_page_config(page_title="⚡ SmartEV Navigator", layout="wide")
st.title("⚡ SmartEV Navigator")

# ---------------------------
# Cache expensive operations
# ---------------------------
@st.cache_data
def geocode_address(address):
    loc = geolocator.geocode(address)
    if loc:
        return (loc.latitude, loc.longitude)
    return None

@st.cache_data
def get_route(start_coords, end_coords):
    url = f"{OSRM_URL}/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&geometries=geojson"
    r = requests.get(url)
    if r.status_code == 200:
        data = r.json()
        return [(pt[1], pt[0]) for pt in data["routes"][0]["geometry"]["coordinates"]]
    return []

@st.cache_data
def get_charging_stations(lat, lon, radius_m=10000, maxresults=50):
    url = f"https://api.openchargemap.io/v3/poi/?output=json&latitude={lat}&longitude={lon}&distance={radius_m/1000}&maxresults={maxresults}"
    headers = {"X-API-Key": OPENCHARGEMAP_KEY}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json()
    return []

# ---------------------------
# Helper functions
# ---------------------------
def estimate_travel_time(distance_km):
    return distance_km / AVERAGE_SPEED_KMH

def find_nearest_charger(lat, lon):
    stations = get_charging_stations(lat, lon, radius_m=5000, maxresults=20)
    if not stations:
        return None, None
    nearest = min(stations, key=lambda x: geodesic((lat, lon), (x["AddressInfo"]["Latitude"], x["AddressInfo"]["Longitude"])).km)
    distance = geodesic((lat, lon), (nearest["AddressInfo"]["Latitude"], nearest["AddressInfo"]["Longitude"])).km
    eta = datetime.now() + timedelta(hours=estimate_travel_time(distance))
    return nearest, eta

def battery_route_segments(route_coords, ev_range_km=DEFAULT_EV_RANGE_KM):
    segments = []
    remaining_km = ev_range_km
    charging_points = []
    for i in range(1, len(route_coords)):
        start = route_coords[i-1]
        end = route_coords[i]
        seg_distance = geodesic(start, end).km
        remaining_km -= seg_distance
        if remaining_km <= 0:
            charger, eta = find_nearest_charger(*end)
            if charger:
                charging_points.append((charger, eta))
                remaining_km = ev_range_km
            color = "red"
        elif remaining_km <= ev_range_km * LOW_BATTERY_THRESHOLD:
            color = "orange"
        else:
            color = "green"
        segments.append((start, end, color))
    return segments, charging_points

# ---------------------------
# Sidebar for dynamic inputs
# ---------------------------
start_addr = st.sidebar.text_input("Start Location", "Bangalore")
end_addr = st.sidebar.text_input("Destination", "Mysore")

# ---------------------------
# Auto-update route on input change
# ---------------------------
start_coords = geocode_address(start_addr)
end_coords = geocode_address(end_addr)

if start_coords and end_coords:
    route_coords = get_route(start_coords, end_coords)
    if route_coords:
        segments, charging_points = battery_route_segments(route_coords)

        # Build map dynamically
        m = folium.Map(location=start_coords, zoom_start=10)

        # Start & end markers
        folium.Marker(start_coords, popup="Start", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(end_coords, popup="Destination", icon=folium.Icon(color="red")).add_to(m)

        # Route segments
        for start, end, color in segments:
            folium.PolyLine([start, end], color=color, weight=5).add_to(m)

        # Charging points
        if charging_points:
            cluster = MarkerCluster().add_to(m)
            for charger, eta in charging_points:
                lat = charger["AddressInfo"]["Latitude"]
                lon = charger["AddressInfo"]["Longitude"]
                name = charger["AddressInfo"]["Title"]
                folium.Marker([lat, lon],
                              popup=f"{name}\nETA: {eta.strftime('%H:%M')}",
                              icon=folium.Icon(color="red", icon="bolt", prefix="fa")).add_to(cluster)

        # Nearby chargers along route
        mid_lat = (start_coords[0] + end_coords[0]) / 2
        mid_lon = (start_coords[1] + end_coords[1]) / 2
        all_stations = get_charging_stations(mid_lat, mid_lon, radius_m=50000, maxresults=100)
        if all_stations:
            cluster = MarkerCluster().add_to(m)
            for cs in all_stations:
                lat = cs["AddressInfo"]["Latitude"]
                lon = cs["AddressInfo"]["Longitude"]
                name = cs["AddressInfo"]["Title"]
                folium.Marker([lat, lon], popup=name,
                              icon=folium.Icon(color="orange", icon="flash", prefix="fa")).add_to(cluster)

        # Legend
        legend_html = """
        <div style="
        position: fixed; 
        bottom: 50px; left: 50px; width: 250px; height: 130px; 
        border:2px solid grey; z-index:9999; font-size:14px;
        background-color:white;
        padding: 10px;">
        <b>Legend</b><br>
        <i style="color:green;">■</i>&nbsp;Sufficient Battery<br>
        <i style="color:orange;">■</i>&nbsp;Low Battery Warning<br>
        <i style="color:red;">■</i>&nbsp;Must Charge Now<br>
        <i class="fa fa-bolt" style="color:red"></i>&nbsp;Suggested Charging Stop<br>
        <i class="fa fa-plug" style="color:orange"></i>&nbsp;Other Chargers
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

        # Render map
        folium_static(m, width=900, height=600)
    else:
        st.error("Unable to fetch route.")
else:
    st.warning("Please enter valid start and destination addresses!")
