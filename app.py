import streamlit as st
from euriai import EuriaiClient
import os
import json
import requests
from dotenv import load_dotenv
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic

# Initialize Streamlit config
st.set_page_config(
    page_title="AI Disaster Navigator Pro",
    layout="centered",
    page_icon="🆘"
)

# Load environment variables
load_dotenv()

# Initialize EURI AI client with error handling
def get_ai_client(model="gemini-2.5-pro-exp-03-25"):
    try:
        return EuriaiClient(
            api_key=os.getenv("EURI_API_KEY"),
            model=model
        )
    except Exception as e:
        st.error(f"AI Service Error: {str(e)}")
        return None

# Custom CSS for better UI
st.markdown("""
<style>
    .emergency-header {
        background: linear-gradient(45deg, #ff4444, #ff9800);
        color: white;
        padding: 1.5rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
    }
    .route-step {
        padding: 1rem;
        margin: 1rem 0;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .blocked { border-left: 4px solid #ff4444; background: #fff3f3; }
    .clear { border-left: 4px solid #4CAF50; background: #e8f5e9; }
    .map-container { border-radius: 10px; overflow: hidden; margin: 2rem 0; }
</style>
""", unsafe_allow_html=True)

def get_nearby_resources(lat, lon, resource_type="assembly_point"):
    """Get emergency resources from OpenStreetMap with enhanced error handling"""
    try:
        query = f"""
        [out:json];
        node[emergency={resource_type}](around:5000,{lat},{lon});
        out body;
        """
        response = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=query,
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        return data.get('elements', [])
    except requests.exceptions.RequestException as e:
        st.error(f"Map data error: Failed to fetch resources ({str(e)})")
        return []
    except json.JSONDecodeError:
        st.error("Map data error: Invalid response from server")
        return []

def get_safe_route(start_coord, end_coord, disaster_type):
    """Get route from OSRM with blockage simulation and better error handling"""
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{start_coord[1]},{start_coord[0]};{end_coord[1]},{end_coord[0]}?overview=full"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        route_data = response.json()
        
        if route_data.get('code') != 'Ok':
            return {"error": "No route found"}

        simulated_blockages = {
            "flood": ["Main Street", "River Road"],
            "fire": ["Forest Highway", "Mountain Pass"],
            "earthquake": ["Bridge Approach", "Tunnel Road"]
        }
        
        route_steps = []
        for step in route_data['routes'][0]['legs'][0]['steps']:
            road_name = step.get('name', 'Unnamed Road')
            blockage = road_name in simulated_blockages.get(disaster_type.lower(), [])
            
            route_steps.append({
                "instruction": step['maneuver']['instruction'],
                "distance": f"{step['distance']/1000:.1f} km",
                "duration": f"{step['duration']/60:.1f} min",
                "road": road_name,
                "blocked": blockage,
                "alternative": "Use Service Lane" if blockage else None
            })
        
        return {
            "distance": route_data['routes'][0]['distance'],
            "duration": route_data['routes'][0]['duration'],
            "steps": route_steps,
            "polyline": route_data['routes'][0]['geometry']
        }
    except requests.exceptions.RequestException as e:
        return {"error": f"Routing service error: {str(e)}"}
    except KeyError:
        return {"error": "Invalid route data format"}

def decode_polyline(polyline_str):
    """Convert polyline string to coordinates with validation"""
    coordinates = []
    index = 0
    lat = lng = 0
    
    if not polyline_str:
        return coordinates

    while index < len(polyline_str):
        for coord in [lat, lng]:
            shift = result = 0
            while True:
                if index >= len(polyline_str):
                    return coordinates
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            coord += ~(result >> 1) if (result & 1) else (result >> 1)
        coordinates.append((lat * 1e-5, lng * 1e-5))
    
    return coordinates

# ... (keep all previous imports and setup code unchanged)

def analyze_emergency(text, location, disaster_type):
    """Enhanced emergency analysis with validation"""
    if not text.strip():
        return {"error": "Please describe your emergency situation"}
    
    prompt = f"""EMERGENCY NAVIGATION PROTOCOL v2.1
**Situation**: {text}
**Location**: {location}
**Disaster Type**: {disaster_type}

Generate response with:
1. 3 prioritized safety actions
2. Potential route hazards
3. Local emergency contacts
4. Verification status

Format as clear text with emojis, no JSON needed"""

    try:
        client = get_ai_client()
        if not client:
            return {"error": "AI service unavailable"}
            
        # Remove json_mode parameter
        response = client.generate_completion(
            prompt=prompt,
            temperature=0.3,
            max_tokens=600
        )
        
        # Handle text response directly
        if isinstance(response, dict) and 'choices' in response:
            return response['choices'][0]['text']
        return response
    
    except Exception as e:
        return {"error": f"Analysis error: {str(e)}"}

# ... (keep rest of the code unchanged)

# Main UI Components
st.markdown("<div class='emergency-header'><h1>🚨 AI Emergency Navigator Pro</h1></div>", unsafe_allow_html=True)

# Input Section
with st.form("emergency_form"):
    col1, col2 = st.columns([2, 1])
    
    with col1:
        emergency_desc = st.text_area(
            "Describe your emergency situation:",
            placeholder="e.g., 'Flood waters rising rapidly in my area...'",
            height=120
        )
        disaster_type = st.selectbox(
            "Disaster Type",
            ["Flood", "Fire", "Earthquake", "Tsunami", "Other"],
            index=0
        )
    
    with col2:
        st.subheader("📍 Your Location")
        current_lat = st.number_input("Latitude", value=12.9716, format="%.6f")
        current_lon = st.number_input("Longitude", value=77.5946, format="%.6f")

    submitted = st.form_submit_button("Generate Evacuation Plan")

if submitted:
    if not emergency_desc.strip():
        st.warning("Please describe your emergency situation")
        st.stop()
    
    with st.spinner("🚨 Analyzing emergency and calculating safest route..."):
        # Step 1: Find nearby shelters
        shelters = get_nearby_resources(current_lat, current_lon)
        if not shelters:
            st.error("No emergency shelters found in your area!")
            st.stop()
        
        best_shelter = shelters[0]
        shelter_coords = (best_shelter['lat'], best_shelter['lon'])
        
        # Step 2: Calculate route
        route_data = get_safe_route(
            (current_lat, current_lon),
            shelter_coords,
            disaster_type.lower()
        )
        
        if 'error' in route_data:
            st.error(f"Routing error: {route_data['error']}")
            st.stop()
        
        # Step 3: Get AI analysis
        analysis = analyze_emergency(
            emergency_desc,
            f"{current_lat},{current_lon}",
            disaster_type
        )
        
        if 'error' in analysis:
            st.error(analysis['error'])
            st.stop()
        
        # Display Results
        st.success("✅ Emergency plan generated successfully!")
        
        # Interactive Map
        with st.container():
            st.subheader("🗺️ Evacuation Route Map")
            m = folium.Map(location=[current_lat, current_lon], zoom_start=14)
            
            # Add markers
            folium.Marker(
                [current_lat, current_lon],
                popup="Your Location",
                icon=folium.Icon(color='red', icon='person')
            ).add_to(m)
            
            folium.Marker(
                shelter_coords,
                popup=best_shelter.get('tags', {}).get('name', 'Emergency Shelter'),
                icon=folium.Icon(color='green', icon='shelter')
            ).add_to(m)
            
            # Add route line
            if 'polyline' in route_data:
                folium.PolyLine(
                    decode_polyline(route_data['polyline']),
                    color='#1e90ff',
                    weight=5,
                    opacity=0.7
                ).add_to(m)
            
            # Display map
            st_folium(m, width=700, height=400, returned_objects=[])
        
        # Route Instructions
        st.subheader("🚦 Step-by-Step Directions")
        for idx, step in enumerate(route_data.get('steps', [])):
            status_class = "blocked" if step['blocked'] else "clear"
            st.markdown(f"""
            <div class="route-step {status_class}">
                <b>Step {idx+1}:</b> {step['instruction']}<br>
                📏 {step['distance']} | ⏱️ {step['duration']}<br>
                {f"🚧 Blockage Detected: {step['road']} ➡️ {step['alternative']}" if step['blocked'] else "✅ Clear Path"}
            </div>
            """, unsafe_allow_html=True)
        
        # Safety Information
        st.subheader("🛡️ Safety Advisory")
        cols = st.columns(2)
        with cols[0]:
            st.markdown("### Immediate Actions")
            for action in analysis.get('safety_actions', []):
                st.success(f"● {action}")
        with cols[1]:
            st.markdown("### Route Warnings")
            for warning in analysis.get('route_warnings', []):
                st.error(f"▲ {warning}")

# Footer
st.markdown("---")
st.markdown("""
**Emergency Services**  
📞 National Disaster Helpline: 1070 | 🚒 Fire Department: 101 | 🚑 Medical Emergency: 108  
*Always verify information through official channels*
""")