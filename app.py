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
@st.cache_data(show_spinner=False)
def geocode_address(address):
    loc = geolocator.geocode(address)
    return (loc.latitude, loc.longitude) if loc else None

@st.cache_data(show_spinner=False)
def get_route(start_coords, end_coords):
    url = f"{OSRM_URL}/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&geometries=geojson"
    r = requests.get(url)
    if r.status_code == 200:
        data = r.json()
        return [(pt[1], pt[0]) for pt in data["routes"][0]["geometry"]["coordinates"]]
    return []

@st.cache_data(show_spinner=False)
def get_charging_stations(lat, lon, radius_m=10000, maxresults=50):
    url = f"https://api.openchargemap.io/v3/poi/?output=json&latitude={lat}&longitude={lon}&distance={radius_m/1000}&maxresults={maxresults}"
    headers = {"X-API-Key": OPENCHARGEMAP_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=10)  # Timeout added
        return r.json() if r.status_code == 200 else []
    except requests.exceptions.RequestException:
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
# Sidebar Inputs
# ---------------------------
st.sidebar.header("Trip Planner")
start_addr = st.sidebar.text_input("Start Location", "Bangalore")
end_addr = st.sidebar.text_input("Destination", "Mysore")
plan_btn = st.sidebar.button("Plan Trip")

# ---------------------------
# Session state
# ---------------------------
if "route_coords" not in st.session_state:
    st.session_state.route_coords = None
    st.session_state.segments = None
    st.session_state.charging_points = None

# ---------------------------
# Build route & charging data
# ---------------------------
if plan_btn:
    with st.spinner("Calculating route and charging stations..."):
        start_coords = geocode_address(start_addr)
        end_coords = geocode_address(end_addr)

        if not start_coords or not end_coords:
            st.error("Invalid start or end location!")
        else:
            route_coords = get_route(start_coords, end_coords)
            if not route_coords:
                st.error("Unable to fetch route.")
            else:
                segments, charging_points = battery_route_segments(route_coords)
                st.session_state.route_coords = route_coords
                st.session_state.segments = segments
                st.session_state.charging_points = charging_points

# ---------------------------
# Display map
# ---------------------------
if st.session_state.route_coords:
    start_coords = st.session_state.route_coords[0]
    m = folium.Map(location=start_coords, zoom_start=10)

    # Start & End Markers
    folium.Marker(start_coords, popup="Start", icon=folium.Icon(color="green")).add_to(m)
    folium.Marker(st.session_state.route_coords[-1], popup="Destination", icon=folium.Icon(color="red")).add_to(m)

    # Route segments
    for start, end, color in st.session_state.segments:
        folium.PolyLine([start, end], color=color, weight=5).add_to(m)

    # Charging points
    if st.session_state.charging_points:
        cluster = MarkerCluster().add_to(m)
        for charger, eta in st.session_state.charging_points:
            lat = charger["AddressInfo"]["Latitude"]
            lon = charger["AddressInfo"]["Longitude"]
            name = charger["AddressInfo"]["Title"]
            folium.Marker([lat, lon], popup=f"{name}\nETA: {eta.strftime('%H:%M')}",
                          icon=folium.Icon(color="red", icon="bolt", prefix="fa")).add_to(cluster)

    folium_static(m, width=900, height=600)
