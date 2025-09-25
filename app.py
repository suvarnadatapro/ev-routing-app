import streamlit as st
import folium
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
CHARGER_SPEEDS = {"Fast": 150, "Normal": 50}  # kW

st.set_page_config(page_title="⚡ EV Pathfinder", layout="wide")
st.title("⚡ EV Pathfinder - Charging Stops & ETA")

# ---------------------------
# Cache expensive operations
# ---------------------------
@st.cache_data
def geocode_address(address):
    loc = geolocator.geocode(address)
    return (loc.latitude, loc.longitude) if loc else None

@st.cache_data
def get_route(start_coords, end_coords):
    url = f"{OSRM_URL}/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&geometries=geojson"
    r = requests.get(url)
    if r.status_code == 200:
        data = r.json()
        return [(pt[1], pt[0]) for pt in data["routes"][0]["geometry"]["coordinates"]]
    return []

@st.cache_data
def get_charging_stations(lat, lon, radius_m=50000, maxresults=200):
    url = f"https://api.openchargemap.io/v3/poi/?output=json&latitude={lat}&longitude={lon}&distance={radius_m/1000}&maxresults={maxresults}"
    headers = {"X-API-Key": OPENCHARGEMAP_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else []
    except:
        return []

def calculate_total_distance(route_coords):
    distance = 0
    for i in range(1, len(route_coords)):
        distance += geodesic(route_coords[i-1], route_coords[i]).km
    return distance

def estimate_travel_time(distance_km):
    return distance_km / AVERAGE_SPEED_KMH

# ---------------------------
# Sidebar Inputs
# ---------------------------
st.sidebar.header("Trip Planner")
start_addr = st.sidebar.text_input("Start Location", "Bangalore")
end_addr = st.sidebar.text_input("Destination", "Mysore")

# ---------------------------
# Dynamic Route Calculation
# ---------------------------
if start_addr and end_addr:
    start_coords = geocode_address(start_addr)
    end_coords = geocode_address(end_addr)

    if not start_coords or not end_coords:
        st.error("Invalid start or end location!")
    else:
        route_coords = get_route(start_coords, end_coords)
        if not route_coords:
            st.error("Unable to fetch route.")
        else:
            # Distance & ETA
            total_distance = calculate_total_distance(route_coords)
            travel_time_hours = estimate_travel_time(total_distance)
            eta = datetime.now() + timedelta(hours=travel_time_hours)

            st.metric("Total Distance (km)", f"{total_distance:.1f}")
            st.metric("Estimated Travel Time (h)", f"{travel_time_hours:.1f}")
            st.metric("Estimated Arrival", eta.strftime("%H:%M"))

            # Suggested charging stops
            remaining_km = DEFAULT_EV_RANGE_KM
            suggested_chargers = []
            for i in range(1, len(route_coords)):
                start = route_coords[i-1]
                end = route_coords[i]
                seg_distance = geodesic(start, end).km
                remaining_km -= seg_distance

                if remaining_km <= DEFAULT_EV_RANGE_KM * LOW_BATTERY_THRESHOLD:
                    stations = get_charging_stations(end[0], end[1], radius_m=5000, maxresults=5)
                    if stations:
                        charger = stations[0]  # nearest
                        needed_km = DEFAULT_EV_RANGE_KM - remaining_km
                        speed_kw = CHARGER_SPEEDS.get("Fast", 100)
                        charge_time_h = needed_km / speed_kw
                        eta_charger = datetime.now() + timedelta(hours=charge_time_h)
                        suggested_chargers.append((charger, eta_charger))
                        remaining_km = DEFAULT_EV_RANGE_KM  # reset

            # All chargers along route mid-point
            mid_idx = len(route_coords) // 2
            mid_lat, mid_lon = route_coords[mid_idx]
            all_chargers = get_charging_stations(mid_lat, mid_lon)

            # ---------------------------
            # Map Rendering
            # ---------------------------
            m = folium.Map(location=start_coords, zoom_start=10)
            # Route
            folium.PolyLine(route_coords, color="blue", weight=5).add_to(m)
            # Start & End
            folium.Marker(start_coords, popup="Start", icon=folium.Icon(color="green")).add_to(m)
            folium.Marker(end_coords, popup="Destination", icon=folium.Icon(color="red")).add_to(m)
            # All chargers
            for cs in all_chargers:
                if "AddressInfo" in cs and cs["AddressInfo"].get("Latitude") and cs["AddressInfo"].get("Longitude"):
                    folium.Marker(
                        [cs["AddressInfo"]["Latitude"], cs["AddressInfo"]["Longitude"]],
                        popup=cs["AddressInfo"].get("Title", "Charging Station"),
                        icon=folium.Icon(color="orange", icon="flash", prefix="fa")
                    ).add_to(m)
            # Suggested chargers
            for charger, eta_charger in suggested_chargers:
                folium.Marker(
                    [charger["AddressInfo"]["Latitude"], charger["AddressInfo"]["Longitude"]],
                    popup=f"Suggested Stop: {charger['AddressInfo']['Title']}\nETA: {eta_charger.strftime('%H:%M')}",
                    icon=folium.Icon(color="red", icon="bolt", prefix="fa")
                ).add_to(m)

            folium_static(m, width=900, height=600)
