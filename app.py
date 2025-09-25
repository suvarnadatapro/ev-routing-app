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
CHARGER_SPEEDS = {"Fast": 150, "Normal": 50}  # kW

st.set_page_config(page_title="⚡ EV Pathfinder", layout="wide")
st.title("⚡ EV Pathfinder - Charging Stops & ETA")

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
        r = requests.get(url, headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else []
    except requests.exceptions.RequestException:
        return []

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
    st.session_state.charging_points = None

# ---------------------------
# Calculate route & charging
# ---------------------------
if plan_btn:
    with st.spinner("Calculating route and charging stops..."):
        start_coords = geocode_address(start_addr)
        end_coords = geocode_address(end_addr)

        if not start_coords or not end_coords:
            st.error("Invalid start or end location!")
        else:
            route_coords = get_route(start_coords, end_coords)
            if not route_coords:
                st.error("Unable to fetch route.")
            else:
                # Compute cumulative distance and find suggested charging stops
                remaining_km = DEFAULT_EV_RANGE_KM
                suggested_chargers = []
                charging_points = []

                for i in range(1, len(route_coords)):
                    start = route_coords[i-1]
                    end = route_coords[i]
                    seg_distance = geodesic(start, end).km
                    remaining_km -= seg_distance

                    # Check if we need to charge
                    if remaining_km <= DEFAULT_EV_RANGE_KM * LOW_BATTERY_THRESHOLD:
                        charger_list = get_charging_stations(end[0], end[1], radius_m=5000, maxresults=5)
                        if charger_list:
                            charger = charger_list[0]  # choose nearest
                            # estimate charging time (simple model)
                            needed_km = DEFAULT_EV_RANGE_KM - remaining_km
                            speed_kw = CHARGER_SPEEDS.get("Fast", 100)
                            charge_time_h = needed_km / speed_kw
                            eta = datetime.now() + timedelta(hours=charge_time_h)
                            suggested_chargers.append((charger, eta))
                            remaining_km = DEFAULT_EV_RANGE_KM  # reset battery
                            charging_points.extend(charger_list)

                # Remove duplicates
                seen = set()
                unique_chargers = []
                for c in charging_points:
                    coord = (c["AddressInfo"]["Latitude"], c["AddressInfo"]["Longitude"])
                    if coord not in seen:
                        seen.add(coord)
                        unique_chargers.append(c)

                st.session_state.route_coords = route_coords
                st.session_state.charging_points = unique_chargers
                st.session_state.suggested_chargers = suggested_chargers

# ---------------------------
# Display map
# ---------------------------
if st.session_state.route_coords:
    start_coords = st.session_state.route_coords[0]
    m = folium.Map(location=start_coords, zoom_start=10)

    # Start & End
    folium.Marker(start_coords, popup="Start", icon=folium.Icon(color="green")).add_to(m)
    folium.Marker(st.session_state.route_coords[-1], popup="Destination", icon=folium.Icon(color="red")).add_to(m)

    # Route in blue
    folium.PolyLine(st.session_state.route_coords, color="blue", weight=5).add_to(m)

    # All chargers along route
    if st.session_state.charging_points:
        cluster = MarkerCluster().add_to(m)
        for charger in st.session_state.charging_points:
            lat = charger["AddressInfo"]["Latitude"]
            lon = charger["AddressInfo"]["Longitude"]
            name = charger["AddressInfo"]["Title"]
            folium.Marker([lat, lon], popup=name,
                          icon=folium.Icon(color="orange", icon="flash", prefix="fa")).add_to(cluster)

    # Suggested chargers with ETA
    if st.session_state.suggested_chargers:
        cluster = MarkerCluster().add_to(m)
        for charger, eta in st.session_state.suggested_chargers:
            lat = charger["AddressInfo"]["Latitude"]
            lon = charger["AddressInfo"]["Longitude"]
            name = charger["AddressInfo"]["Title"]
            folium.Marker([lat, lon],
                          popup=f"Suggested Stop: {name}\nETA: {eta.strftime('%H:%M')}",
                          icon=folium.Icon(color="red", icon="bolt", prefix="fa")).add_to(cluster)

    # Legend
    legend_html = """
    <div style="
    position: fixed; 
    bottom: 50px; left: 50px; width: 230px; height: 130px; 
    border:2px solid grey; z-index:9999; font-size:14px;
    background-color:white;
    padding: 10px;">
    <b>Legend</b><br>
    <i style="color:green;">●</i>&nbsp;Start<br>
    <i style="color:red;">●</i>&nbsp;Destination<br>
    <i style="color:blue;">―</i>&nbsp;Route<br>
    <i class="fa fa-flash" style="color:orange"></i>&nbsp;All Charging Stations<br>
    <i class="fa fa-bolt" style="color:red"></i>&nbsp;Suggested Charging Stops
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    folium_static(m, width=900, height=600)


