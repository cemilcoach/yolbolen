import math
import requests
import streamlit as st
import polyline
import folium
from streamlit_folium import st_folium

# ---- Sayfa Ayarları ----
st.set_page_config(page_title="Rota Bölücü PRO", layout="wide")

# ---- API Key Kontrolü ----
try:
    API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
except Exception:
    st.error("🚨 API Anahtarı Bulunamadı! Lütfen secrets.toml dosyasını kontrol edin.")
    st.stop()

# ---- 1. ADRES ve PLUS CODE FONKSİYONLARI ----

def get_coordinates(address):
    """Metin halindeki adresi koordinata çevirir."""
    if not address:
        return None, "Adres girilmedi."
    
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": API_KEY, "language": "tr"}
    
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

def get_plus_code(lat, lng):
    """Koordinattan Google Plus Code (Ör: QRR4+CM Gölbaşı) bulur."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "latlng": f"{lat},{lng}",
        "key": API_KEY,
        "language": "tr"
    }
    try:
        r = requests.get(url, params=params)
        data = r.json()
        
        # API cevabında 'plus_code' alanı varsa onu al
        if data.get('status') == 'OK':
            if 'plus_code' in data:
                # compound_code: Şehir ismiyle birlikte (Ör: QRR4+CM Gölbaşı, Ankara)
                return data['plus_code'].get('compound_code', data['plus_code'].get('global_code'))
            
            # Eğer ana dizinde yoksa, results içindeki ilk elemana bakalım
            if data.get('results') and 'plus_code' in data['results'][0]:
                 return data['results'][0]['plus_code'].get('compound_code')

        # Hiçbiri yoksa ham koordinat döndür
        return f"{lat:.6f}, {lng:.6f}"
    except:
        return f"{lat:.6f}, {lng:.6f}"

# ---- 2. MATEMATİKSEL HESAPLAMALAR ----
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
st.title("📍 Akıllı Rota Bölücü (Plus Code)")
st.markdown("A ve B noktalarını girin, rota tam olarak belirlediğiniz kilometrelerde bölünsün.")

# --- Session State (Hafıza) ---
if "harita_verisi" not in st.session_state:
    st.session_state.harita_verisi = None

col_input1, col_input2 = st.columns(2)
with col_input1:
    origin_text = st.text_input("A Noktası (Başlangıç)", placeholder="Ör: Kızılay, Ankara")
with col_input2:
    dest_text = st.text_input("B Noktası (Varış)", placeholder="Ör: Taksim, İstanbul")

col_opt1, col_opt2 = st.columns([1, 3])
with col_opt1:
    # Kullanıcının istediği varsayılan değer 11.75
    step_km = st.number_input("Bölüm Mesafesi (km)", value=11.75, step=0.25, format="%.2f")
with col_opt2:
    st.write("") 
    st.write("") 
    hesapla_btn = st.button("Rotayı Hesapla ve Göster", type="primary", use_container_width=True)

# ---- HESAPLAMA BUTONU ----
if hesapla_btn:
    if not origin_text or not dest_text:
        st.warning("Lütfen adresleri girin.")
    else:
        with st.spinner("Rota hesaplanıyor ve Plus Code'lar bulunuyor..."):
            # 1. Koordinatları Bul
            origin_data, err1 = get_coordinates(origin_text)
            dest_data, err2 = get_coordinates(dest_text)

            if err1 or err2:
                st.error(f"Adres hatası: {err1 or err2}")
            else:
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
                    
                    # 4. Mola Adreslerini (PLUS CODE) Çek
                    detailed_breaks = []
                    progress_text = st.empty()
                    prog_bar = st.progress(0)
                    
                    for i, bp in enumerate(breaks):
                        # BURADA DEĞİŞİKLİK YAPILDI: Plus Code soruluyor
                        p_code = get_plus_code(bp[0], bp[1])
                        current_km = step_km * (i + 1)
                        
                        detailed_breaks.append({
                            "lat": bp[0],
                            "lng": bp[1],
                            "code": p_code,
                            "km": current_km
                        })
                        
                        prog_bar.progress((i + 1) / len(breaks))
                    
                    prog_bar.empty()
                    
                    # 5. Verileri HAFIZAYA Kaydet
                    st.session_state.harita_verisi = {
                        "pts": pts,
                        "origin": origin_data,
                        "dest": dest_data,
                        "detailed_breaks": detailed_breaks,
                        "total_km": total_km,
                        "segments": segments,
                        "step_km": step_km
                    }

# ---- HARİTA GÖSTERİMİ ----
if st.session_state.harita_verisi is not None:
    data = st.session_state.harita_verisi
    
    st.success(f"Rota: {data['origin']['name']} ➝ {data['dest']['name']}")

    mid_idx = len(data['pts']) // 2
    m = folium.Map(location=[data['pts'][mid_idx][0], data['pts'][mid_idx][1]], zoom_start=9)

    folium.PolyLine(data['pts'], color="blue", weight=5, opacity=0.7).add_to(m)

    folium.Marker(
        [data['origin']['lat'], data['origin']['lng']], 
        popup=f"<b>Başlangıç</b><br>{data['origin']['name']}",
        icon=folium.Icon(color="green", icon="play")
    ).add_to(m)

    folium.Marker(
        [data['dest']['lat'], data['dest']['lng']], 
        popup=f"<b>Varış</b><br>{data['dest']['name']}",
        icon=folium.Icon(color="red", icon="stop")
    ).add_to(m)

    # Mola Noktaları (Plus Code Gösterimi)
    for i, info in enumerate(data['detailed_breaks']):
        # Popup içeriği Plus Code'u öne çıkaracak şekilde düzenlendi
        popup_html = f"""
        <div style="width:220px; font-family:sans-serif;">
            <b style="color:#e65100;">{i+1}. Mola Noktası</b><br>
            <span style="font-size:12px; color:#555;">{info['km']:.2f}. Kilometre</span>
            <hr style="margin:5px 0; border:0; border-top:1px solid #ccc;">
            <div style="background-color:#f0f0f0; padding:5px; border-radius:4px; font-weight:bold; font-size:14px; text-align:center;">
                {info['code']}
            </div>
            <div style="font-size:10px; color:#888; margin-top:3px; text-align:center;">
                (Google Maps'te aratılabilir)
            </div>
        </div>
        """
        
        folium.Marker(
            [info['lat'], info['lng']],
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color="orange", icon="map-marker")
        ).add_to(m)

    m.fit_bounds([[p[0], p[1]] for p in data['pts']])

    st_folium(m, height=500, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Toplam Mesafe", f"{data['total_km']:.2f} km")
    c2.metric("Mola Sayısı", f"{len(data['detailed_breaks'])}")
    c3.metric("Son Kalan Parça", f"{data['segments'][-1]:.2f} km" if data['segments'] else "0")
