import streamlit as st
import folium
from folium.plugins import MarkerCluster
from geopy.geocoders import Nominatim
import requests
from streamlit_folium import st_folium
from geopy.distance import geodesic

# -----------------
# Configurations
# -----------------
OSRM_URL = "http://router.project-osrm.org/route/v1/driving"
geolocator = Nominatim(user_agent="ev_routing_app")

# EV Models with range in km
EV_MODELS = {
    "Tesla Model 3": {"battery": 75, "range": 400},
    "Nissan Leaf": {"battery": 40, "range": 240},
    "Hyundai Kona": {"battery": 64, "range": 415},
}

# Charging Stations (Sample)
CHARGING_STATIONS = [
    {"name": "Fast Charger 1", "lat": 12.9716, "lon": 77.5946},
    {"name": "Fast Charger 2", "lat": 12.9352, "lon": 77.6245},
    {"name": "Normal Charger", "lat": 12.9141, "lon": 77.6387},
    {"name": "Charger 4", "lat": 12.8500, "lon": 77.6000},
]

# -----------------
# Helper Functions
# -----------------
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

def suggest_charging_stops(route_coords, ev_range_km):
    stops = []
    distance_covered = 0
    last_stop = route_coords[0]

    for i in range(1, len(route_coords)):
        segment_dist = geodesic(route_coords[i-1], route_coords[i]).km
        distance_covered += segment_dist

        if distance_covered >= ev_range_km:
            # Find nearest charging station from current point
            nearest_cs = min(CHARGING_STATIONS, key=lambda cs: geodesic(cs=(cs["lat"], cs["lon"]), dest=route_coords[i]).km)
            stops.append(nearest_cs)
            distance_covered = 0
            last_stop = (nearest_cs["lat"], nearest_cs["lon"])

    return stops

# -----------------
# Streamlit UI
# -----------------
st.title("🚗 EV Route Planner with Charging Stops (Free Version)")
st.sidebar.header("Trip Details")

start_addr = st.sidebar.text_input("Start Location", "Bangalore")
end_addr = st.sidebar.text_input("Destination", "Mysore")
ev_choice = st.sidebar.selectbox("Select Your EV", list(EV_MODELS.keys()))

if st.sidebar.button("Start Trip"):
    start_coords = geocode_address(start_addr)
    end_coords = geocode_address(end_addr)

    if start_coords and end_coords:
        route_coords = get_route(start_coords, end_coords)
        ev_range = EV_MODELS[ev_choice]["range"]

        # Suggest charging stops if needed
        charging_stops = suggest_charging_stops(route_coords, ev_range)

        # Map Initialization
        m = folium.Map(location=start_coords, zoom_start=10)

        # Route
        if route_coords:
            folium.PolyLine(route_coords, color="blue", weight=5).add_to(m)

        # Markers: start, end
        folium.Marker(start_coords, popup="Start", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(end_coords, popup="Destination", icon=folium.Icon(color="red")).add_to(m)

        # Charging Stations along route
        marker_cluster = MarkerCluster().add_to(m)
        for cs in CHARGING_STATIONS:
            folium.Marker([cs["lat"], cs["lon"]], popup=cs["name"], icon=folium.Icon(color="orange")).add_to(marker_cluster)

        # Charging stops on route
        for stop in charging_stops:
            folium.Marker([stop["lat"], stop["lon"]], popup=f"Suggested Stop: {stop['name']}",
                          icon=folium.Icon(color="purple", icon="bolt", prefix='fa')).add_to(m)

        st.subheader("Optimal EV Route with Charging Stops")
        st_folium(m, width=700, height=500)
