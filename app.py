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
geolocator = Nominatim(user_agent="ev_routing_app")
OPENCHARGEMAP_KEY = "931d4ae3-014a-4ac1-8c4c-d1aa244c42de"

# EV models (all included)
EV_MODELS = {
    "Nissan Leaf": {"range_km": 240, "fast_rate": 150, "normal_rate": 50},
    "Tesla Model 3": {"range_km": 350, "fast_rate": 250, "normal_rate": 100},
    "Hyundai Kona": {"range_km": 300, "fast_rate": 200, "normal_rate": 70},
    "MG ZS EV": {"range_km": 320, "fast_rate": 180, "normal_rate": 60},
}

AVERAGE_SPEED_KMH = 50

# ---------------------------
# Helper functions
# ---------------------------
def geocode_address(address):
    location = geolocator.geocode(address)
    if location:
        return (location.latitude, location.longitude)
    else:
        st.error(f"Address '{address}' not found!")
        return None

def get_route(start_coords, end_coords):
    url = f"{OSRM_URL}/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&geometries=geojson"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        coords = [(pt[1], pt[0]) for pt in data["routes"][0]["geometry"]["coordinates"]]
        return coords
    else:
        st.error("Error fetching route from OSRM")
        return []

def get_charging_stations(lat, lon, radius_m=10000, maxresults=50):
    url = f"https://api.openchargemap.io/v3/poi/?output=json&latitude={lat}&longitude={lon}&distance={radius_m/1000}&maxresults={maxresults}"
    headers = {"X-API-Key": OPENCHARGEMAP_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        st.error("Error fetching charging stations")
        return []

def estimate_travel_time(distance_km, avg_speed_kmh=AVERAGE_SPEED_KMH):
    return distance_km / avg_speed_kmh

def estimate_charging_time(distance_needed, charger_rate):
    return distance_needed / charger_rate

# ---------------------------
# Smart charging stop selection
# ---------------------------
def get_optimal_charging_stop(lat, lon, ev_range_km, radius_m=5000):
    stations = get_charging_stations(lat, lon, radius_m=radius_m, maxresults=20)
    if not stations:
        return None, "Normal", 0
    best_score = -1
    best_station = None
    charger_type = "Normal"
    for cs in stations:
        level = cs.get("Connections", [{}])[0].get("Level", {})
        if level and "LevelID" in level:
            if level["LevelID"] == 3:
                rate = 150
                c_type = "Fast"
            else:
                rate = 50
                c_type = "Normal"
        else:
            rate = 50
            c_type = "Normal"
        cs_lat = cs["AddressInfo"]["Latitude"]
        cs_lon = cs["AddressInfo"]["Longitude"]
        distance = geodesic((lat, lon), (cs_lat, cs_lon)).km
        score = rate / (distance + 0.1)
        if score > best_score:
            best_score = score
            best_station = cs
            charger_type = c_type
    charge_time = estimate_charging_time(ev_range_km, rate)
    return best_station, charger_type, charge_time

def calculate_eta_for_all_optimal(route_coords):
    eta_dict = {}
    for ev_name, ev in EV_MODELS.items():
        eta_list = []
        now = datetime.now()
        distance_since_last_charge = 0
        for i in range(1, len(route_coords)):
            segment_distance = geodesic(route_coords[i-1], route_coords[i]).km
            distance_since_last_charge += segment_distance
            travel_time = estimate_travel_time(segment_distance)
            now += timedelta(hours=travel_time)
            if distance_since_last_charge >= ev["range_km"]:
                best_charger, charger_type, charge_time = get_optimal_charging_stop(*route_coords[i], ev["range_km"])
                eta_list.append((route_coords[i], now, charger_type, charge_time, best_charger))
                distance_since_last_charge = 0
        eta_list.append((route_coords[-1], now, "None", 0, None))
        eta_dict[ev_name] = eta_list
    return eta_dict

# ---------------------------
# Streamlit UI
# ---------------------------
st.set_page_config(page_title="⚡ Smart EV Pathfinder", layout="wide")
st.title("⚡ Smart EV Pathfinder - Optimal Charging Stops & ETA")

st.sidebar.header("Trip Details")
start_addr = st.sidebar.text_input("Start Location", "Bangalore")
end_addr = st.sidebar.text_input("Destination", "Mysore")

if st.sidebar.button("Start Trip"):
    start_coords = geocode_address(start_addr)
    end_coords = geocode_address(end_addr)
    if start_coords and end_coords:
        route_coords = get_route(start_coords, end_coords)
        charging_stations = get_charging_stations(
            lat=(start_coords[0]+end_coords[0])/2,
            lon=(start_coords[1]+end_coords[1])/2,
            radius_m=50000,
            maxresults=100
        )
        eta_all = calculate_eta_for_all_optimal(route_coords)

        # Map
        m = folium.Map(location=route_coords[0], zoom_start=10)
        folium.PolyLine(route_coords, color="blue", weight=5).add_to(m)
        folium.Marker(route_coords[0], popup="Start", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(route_coords[-1], popup="Destination", icon=folium.Icon(color="red")).add_to(m)

        # Charging stations
        if charging_stations:
            marker_cluster = MarkerCluster().add_to(m)
            for cs in charging_stations:
                lat = cs["AddressInfo"]["Latitude"]
                lon = cs["AddressInfo"]["Longitude"]
                name = cs["AddressInfo"]["Title"]
                folium.Marker([lat, lon], popup=name, icon=folium.Icon(color="orange")).add_to(marker_cluster)

        st.subheader("EV Route with Optimal Charging Stops")
        st_folium(m, width=800, height=600)

        # Display ETA for all EVs
        for ev_name, eta_info in eta_all.items():
            st.sidebar.subheader(f"{ev_name} ETA")
            for stop_coords, eta, charger_type, charge_time, charger in eta_info:
                if charger_type != "None":
                    charger_name = charger["AddressInfo"]["Title"] if charger else "Unknown"
                    st.sidebar.markdown(f"{charger_name}: {charger_type} Stop at {eta.strftime('%H:%M')} ({charge_time:.1f} hrs)")
            st.sidebar.markdown(f"**Destination ETA:** {eta_info[-1][1].strftime('%H:%M')}")
