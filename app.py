import streamlit as st
import folium
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
import requests
from datetime import datetime, timedelta
from streamlit_folium import st_folium

st.set_page_config(page_title="⚡ SmartEV Navigator", layout="wide")
st.title("⚡ SmartEV Navigator")

DEFAULT_EV_RANGE_KM = 300
AVERAGE_SPEED_KMH = 50
LOW_BATTERY_THRESHOLD = 0.25  # 25%

# ---------------------------
# Helper functions
# ---------------------------
def estimate_travel_time(distance_km):
    return distance_km / AVERAGE_SPEED_KMH

def get_route(start_coords, end_coords):
    OSRM_URL = "http://router.project-osrm.org/route/v1/driving"
    url = f"{OSRM_URL}/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&geometries=geojson"
    r = requests.get(url)
    if r.status_code == 200:
        data = r.json()
        return [(pt[1], pt[0]) for pt in data["routes"][0]["geometry"]["coordinates"]]
    return []

# ---------------------------
# Session state
# ---------------------------
if "start_coords" not in st.session_state:
    st.session_state.start_coords = None
if "end_coords" not in st.session_state:
    st.session_state.end_coords = None
if "route_coords" not in st.session_state:
    st.session_state.route_coords = None

# ---------------------------
# Map for user to select points
# ---------------------------
m = folium.Map(location=[20, 78], zoom_start=5)

# Allow clicking for start and end points
click_js = """
function(e){
    if (!window.startSelected){
        window.startSelected = true;
        var marker = L.marker(e.latlng).addTo(window.map).bindPopup("Start").openPopup();
        window.start_coords = [e.latlng.lat, e.latlng.lng];
    } else if (!window.endSelected){
        window.endSelected = true;
        var marker = L.marker(e.latlng).addTo(window.map).bindPopup("Destination").openPopup();
        window.end_coords = [e.latlng.lat, e.latlng.lng];
    }
}
"""
# Note: `st_folium` allows capturing clicks in Python, so we can use simpler handling

map_data = st_folium(m, width=900, height=500, returned_objects=["last_clicked"])

if map_data["last_clicked"]:
    lat, lon = map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]
    if st.session_state.start_coords is None:
        st.session_state.start_coords = (lat, lon)
        st.success(f"Start point set at {st.session_state.start_coords}")
    elif st.session_state.end_coords is None:
        st.session_state.end_coords = (lat, lon)
        st.success(f"Destination set at {st.session_state.end_coords}")

# ---------------------------
# Build route if both points are set
# ---------------------------
if st.session_state.start_coords and st.session_state.end_coords:
    route_coords = get_route(st.session_state.start_coords, st.session_state.end_coords)
    if route_coords:
        folium.PolyLine(route_coords, color="blue", weight=5).add_to(m)
        # Add markers again for clarity
        folium.Marker(st.session_state.start_coords, popup="Start", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(st.session_state.end_coords, popup="Destination", icon=folium.Icon(color="red")).add_to(m)
        folium_static(m, width=900, height=500)
    else:
        st.error("Unable to fetch route.")
