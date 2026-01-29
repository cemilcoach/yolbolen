import math
import requests
import streamlit as st
import polyline
import pydeck as pdk

# ---- Sayfa Ayarları ----
st.set_page_config(page_title="Rota Bölücü PRO", layout="wide")

# ---- API Key Kontrolü ----
try:
    API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
except Exception:
    st.error("🚨 API Anahtarı Bulunamadı!")
    st.stop()

# ---- 1. ADRESİ KOORDİNATA ÇEVİRME (GEOCODING) ----
def get_coordinates(address):
    """Metin halindeki adresi (Ör: Ankara) enlem/boylama çevirir."""
    if not address:
        return None, "Adres girilmedi."
        
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": API_KEY}
    
    try:
        r = requests.get(url, params=params)
        data = r.json()
        
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            formatted_address = data['results'][0]['formatted_address']
            return {"lat": location['lat'], "lng": location['lng'], "name": formatted_address}, None
        else:
            return None, f"Adres bulunamadı ({data['status']})"
    except Exception as e:
        return None, str(e)

# ---- 2. ROTA ÇİZME VE PARÇALAMA FONKSİYONLARI ----
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def interpolate_point(p1, p2, t):
    lat = p1[0] + (p2[0] - p1[0]) * t
    lon = p1[1] + (p2[1] - p1[1]) * t
    return (lat, lon)

def split_route_by_step_km(points_latlng, step_km):
    if len(points_latlng) < 2:
        return 0.0, [], []

    seg_dists = []
    total_km = 0.0
    for i in range(len(points_latlng) - 1):
        d = haversine_km(points_latlng[i][0], points_latlng[i][1], 
                         points_latlng[i+1][0], points_latlng[i+1][1])
        seg_dists.append(d)
        total_km += d

    breakpoints = []
    segment_kms = []
    current_segment_target = step_km
    distance_walked = 0.0

    for i in range(len(points_latlng) - 1):
        p1 = points_latlng[i]
        p2 = points_latlng[i+1]
        d_segment = seg_dists[i]

        while distance_walked + d_segment >= current_segment_target:
            remaining_needed = current_segment_target - distance_walked
            if d_segment > 0:
                t = remaining_needed / d_segment
                bp = interpolate_point(p1, p2, t)
                breakpoints.append(bp)
                segment_kms.append(step_km)
            current_segment_target += step_km

        distance_walked += d_segment

    final_remainder = total_km - (len(segment_kms) * step_km)
    if final_remainder > 0.01:
        segment_kms.append(final_remainder)

    return total_km, segment_kms, breakpoints

def get_directions_polyline(origin_lat, origin_lng, dest_lat, dest_lng):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{origin_lat},{origin_lng}",
        "destination": f"{dest_lat},{dest_lng}",
        "mode": "driving",
        "key": API_KEY,
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    
    if data.get("status") != "OK":
        return None, data.get("error_message") or data.get("status")
        
    enc = data["routes"][0]["overview_polyline"]["points"]
    pts = polyline.decode(enc)
    return pts, None

# ---- ARAYÜZ (UI) ----
st.title("📍 Akıllı Rota Bölücü")
st.markdown("A ve B noktalarını girin, rota tam olarak belirlediğiniz kilometrelerde bölünsün.")

# Basit ve Sağlam Input Kutuları
col_input1, col_input2 = st.columns(2)
with col_input1:
    origin_text = st.text_input("A Noktası (Başlangıç)", placeholder="Ör: Ankara, Kızılay")
with col_input2:
    dest_text = st.text_input("B Noktası (Varış)", placeholder="Ör: İstanbul, Taksim")

col_opt1, col_opt2 = st.columns([1, 3])
with col_opt1:
    step_km = st.number_input("Bölüm Mesafesi (km)", value=10.75, step=0.25, format="%.2f")
with col_opt2:
    st.write("") 
    st.write("") 
    # Butonu biraz aşağı hizalamak için boşluk
    hesapla_btn = st.button("Rotayı Hesapla ve Böl", type="primary", use_container_width=True)

# ---- HESAPLAMA MANTIĞI ----
if hesapla_btn:
    if not origin_text or not dest_text:
        st.warning("Lütfen hem başlangıç hem de varış noktalarını yazın.")
    else:
        with st.spinner("Adresler bulunuyor ve rota hesaplanıyor..."):
            # 1. Adresleri Koordinata Çevir
            origin_data, err1 = get_coordinates(origin_text)
            dest_data, err2 = get_coordinates(dest_text)

            if err1:
                st.error(f"A Noktası Hatası: {err1}")
            elif err2:
                st.error(f"B Noktası Hatası: {err2}")
            else:
                st.success(f"Rota: **{origin_data['name']}** ➡️ **{dest_data['name']}**")
                
                # 2. Rotayı Çiz
                pts, route_err = get_directions_polyline(
                    origin_data['lat'], origin_data['lng'],
                    dest_data['lat'], dest_data['lng']
                )

                if route_err:
                    st.error(f"Rota çizilemedi: {route_err}")
                else:
                    # 3. Rotayı Böl
                    total_km, segments, breaks = split_route_by_step_km(pts, step_km)

                    # --- HARİTA GÖRSELLEŞTİRME ---
                    path_layer_data = [{"path": [[p[1], p[0]] for p in pts]}]
                    
                    points_layer_data = []
                    # Başlangıç
                    points_layer_data.append({"lng": origin_data['lng'], "lat": origin_data['lat'], "tooltip": f"Başlangıç: {origin_data['name']}", "color": [0, 200, 0], "radius": 300})
                    
                    # Duraklar
                    for i, bp in enumerate(breaks):
                        points_layer_data.append({
                            "lng": bp[1], 
                            "lat": bp[0], 
                            "tooltip": f"{i+1}. Mola ({step_km * (i+1):.2f} km)",
                            "color": [255, 140, 0], # Turuncu
                            "radius": 200
                        })
                    
                    # Varış
                    points_layer_data.append({"lng": dest_data['lng'], "lat": dest_data['lat'], "tooltip": f"Varış: {dest_data['name']}", "color": [200, 0, 0], "radius": 300})

                    mid_idx = len(pts) // 2
                    view_state = pdk.ViewState(latitude=pts[mid_idx][0], longitude=pts[mid_idx][1], zoom=6, pitch=0)

                    layer_path = pdk.Layer(
                        "PathLayer", path_layer_data, get_path="path", width_scale=20, width_min_pixels=4, get_color=[50, 100, 200], pickable=True
                    )
                    
                    layer_scatter = pdk.Layer(
                        "ScatterplotLayer", points_layer_data, get_position="[lng, lat]", get_color="color", get_radius="radius", pickable=True, radius_min_pixels=5, filled=True
                    )

                    st.pydeck_chart(pdk.Deck(
                        layers=[layer_path, layer_scatter],
                        initial_view_state=view_state,
                        map_style="mapbox://styles/mapbox/light-v10",
                        tooltip={"text": "{tooltip}"}
                    ))

                    # İstatistikler
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Toplam Mesafe", f"{total_km:.2f} km")
                    c2.metric("Mola Sayısı", f"{len(breaks)}")
                    c3.metric("Son Kalan Parça", f"{segments[-1]:.2f} km" if segments else "0")
