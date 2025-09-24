import streamlit as st
import folium
from folium.plugins import MarkerCluster
from geopy.geocoders import Nominatim
import requests
from streamlit_folium import st_folium
from geopy.distance import geodesic
from datetime import datetime, timedelta

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
# Caching API calls for persistence
# ---------------------------
@st.cache_data
def geocode_address(address):
    location = geolocator.geocode(address)
    if location:
        return (location.latitude, location.longitude)
    else:
        return None

@st.cache_data
def get_route(start_coords, end_coords):
    url = f"{OSRM_URL}/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&geometries=geojson"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        coords = [(pt[1], pt[0]) for pt in data["routes"][0]["geometry"]["coordinates"]]
        return coords
    return []

@st.cache_data
def get_charging_stations(lat, lon, radius_m=10000, maxresults=50):
    url = f"https://api.openchargemap.io/v3/poi/?output=json&latitude={lat}&longitude={lon}&distance={radius_m/1000}&maxresults={maxresults}"
    headers = {"X-API-Key": OPENCHARGEMAP_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    return []

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
# Sidebar inputs
# ---------------------------
start_addr = st.sidebar.text_input("Start Location", "Bangalore")
end_addr = st.sidebar.text_input("Destination", "Mysore")

if st.sidebar.button("Plan Trip"):

    start_coords = geocode_address(start_addr)
    end_coords = geocode_address(end_addr)

    if start_coords and end_coords:
        route_coords = get_route(start_coords, end_coords)
        segments, charging_points = battery_route_segments(route_coords)

        # ---------------------------
        # Build map only once
        # ---------------------------
        m = folium.Map(location=route_coords[0], zoom_start=10)
        folium.Marker(route_coords[0], popup="Start", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(route_coords[-1], popup="Destination", icon=folium.Icon(color="red")).add_to(m)

        # Draw route segments
        for start, end, color in segments:
            folium.PolyLine([start, end], color=color, weight=5).add_to(m)

        # Suggested charging points
        if charging_points:
            marker_cluster = MarkerCluster().add_to(m)
            for charger, eta in charging_points:
                lat = charger["AddressInfo"]["Latitude"]
                lon = charger["AddressInfo"]["Longitude"]
                name = charger["AddressInfo"]["Title"]
                folium.Marker(
                    [lat, lon],
                    popup=f"{name}\nETA: {eta.strftime('%H:%M')}",
                    icon=folium.Icon(color="red", icon="bolt", prefix="fa")
                ).add_to(marker_cluster)

        # Nearby chargers
        all_stations = get_charging_stations(
            lat=(start_coords[0]+end_coords[0])/2,
            lon=(start_coords[1]+end_coords[1])/2,
            radius_m=50000,
            maxresults=100
        )
        if all_stations:
            marker_cluster = MarkerCluster().add_to(m)
            for cs in all_stations:
                lat = cs["AddressInfo"]["Latitude"]
                lon = cs["AddressInfo"]["Longitude"]
                name = cs["AddressInfo"]["Title"]
                folium.Marker(
                    [lat, lon],
                    popup=name,
                    icon=folium.Icon(color="orange", icon="flash", prefix="fa")
                ).add_to(marker_cluster)

        # Legend
        legend_html = """
        <div style="
        position: fixed; 
        bottom: 50px; left: 50px; width: 250px; height: 130px; 
        border:2px solid grey; z-index:9999; font-size:14px;
        background-color:white;
        padding: 10px;
        ">
        <b>Legend</b><br>
        <i style="color:green;">■</i>&nbsp;Sufficient Battery<br>
        <i style="color:orange;">■</i>&nbsp;Low Battery Warning<br>
        <i style="color:red;">■</i>&nbsp;Must Charge Now<br>
        <i class="fa fa-bolt" style="color:red"></i>&nbsp;Suggested Charging Stop<br>
        <i class="fa fa-plug" style="color:orange"></i>&nbsp;Other Chargers
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

        # Save map in session_state to prevent disappearing
        st.session_state.map_data = m

# Display the map
if "map_data" in st.session_state and st.session_state.map_data:
    st.subheader("EV Route with Smart Charging & ETA")
    st_folium(st.session_state.map_data, width=900, height=600)
