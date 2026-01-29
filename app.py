import json
import math
import requests
import streamlit as st
import polyline
import pydeck as pdk
import streamlit.components.v1 as components

# ---- Sayfa Ayarları ----
st.set_page_config(page_title="Rota Bölücü PRO", layout="wide")

# ---- API Key Kontrolü ----
try:
    API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
except Exception:
    st.error("🚨 API Anahtarı Bulunamadı!")
    st.info("Lütfen .streamlit/secrets.toml dosyasına GOOGLE_MAPS_API_KEY ekleyin.")
    st.stop()

# ---- Matematiksel Fonksiyonlar (Haversine & Interpolasyon) ----
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def interpolate_point(p1, p2, t):
    """İki nokta (p1, p2) arasında t oranındaki (%0-%100) koordinatı verir."""
    lat = p1[0] + (p2[0] - p1[0]) * t
    lon = p1[1] + (p2[1] - p1[1]) * t
    return (lat, lon)

def split_route_by_step_km(points_latlng, step_km):
    """Rotayı hassas matematiksel hesapla step_km parçalarına böler."""
    if len(points_latlng) < 2:
        return 0.0, [], []

    # 1. Rota üzerindeki tüm küçük parçaların mesafelerini hesapla
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

    # 2. Rota üzerinde yürümeye başla
    for i in range(len(points_latlng) - 1):
        p1 = points_latlng[i]
        p2 = points_latlng[i+1]
        d_segment = seg_dists[i]

        # Bu segment içinde hedef noktayı geçiyor muyuz?
        while distance_walked + d_segment >= current_segment_target:
            remaining_needed = current_segment_target - distance_walked
            
            if d_segment > 0:
                # Lineer interpolasyon oranı (t)
                t = remaining_needed / d_segment
                bp = interpolate_point(p1, p2, t)
                breakpoints.append(bp)
                segment_kms.append(step_km)
            
            current_segment_target += step_km

        distance_walked += d_segment

    # Kalan parça hesabı
    final_remainder = total_km - (len(segment_kms) * step_km)
    if final_remainder > 0.01:
        segment_kms.append(final_remainder)

    return total_km, segment_kms, breakpoints

def get_directions_polyline(origin_lat, origin_lng, dest_lat, dest_lng):
    """Google Directions API ile rota çizgisini alır."""
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
    pts = polyline.decode(enc)  # [(lat,lng), ...]
    return pts, None

# ---- ARAYÜZ (UI) ----
st.title("📍 Akıllı Rota Bölücü")
st.markdown("A ve B noktalarını seçin, rota tam olarak belirlediğiniz kilometrelerde bölünsün.")

# Parametre Yönetimi (Query Params)
# URL'den gelen verileri okuyoruz
qp = st.query_params
origin_raw = qp.get("origin", None)
dest_raw = qp.get("dest", None)

origin_data = json.loads(origin_raw) if origin_raw else None
dest_data = json.loads(dest_raw) if dest_raw else None

# ---- JavaScript Enjeksiyonu (Autocomplete İçin) ----
# Not: API Key'i burada kullanmak zorundayız. 
# GÜVENLİK İÇİN: Google Cloud Console'dan bu Key için HTTP Referrer kısıtlaması yapmalısın.
html_code = f"""
<!DOCTYPE html>
<html>
  <body>
    <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:10px;">
      <div style="flex:1; min-width:250px;">
        <label style="font-family:sans-serif; font-size:14px; font-weight:bold; color:#333;">A Noktası (Başlangıç)</label>
        <input id="origin_input" type="text" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:5px;" placeholder="Şehir veya yer ara...">
      </div>
      <div style="flex:1; min-width:250px;">
        <label style="font-family:sans-serif; font-size:14px; font-weight:bold; color:#333;">B Noktası (Varış)</label>
        <input id="dest_input" type="text" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:5px;" placeholder="Şehir veya yer ara...">
      </div>
    </div>

    <script>
      function sendDataToStreamlit(key, payload) {{
        // Veriyi parent window'a (Streamlit'e) gönder
        window.parent.postMessage({{
          type: "streamlit:message",
          key: key,
          value: JSON.stringify(payload)
        }}, "*");
      }}

      function initMap() {{
        const originInput = document.getElementById("origin_input");
        const destInput = document.getElementById("dest_input");
        
        const options = {{ fields: ["geometry", "name", "formatted_address"] }};
        
        const originAC = new google.maps.places.Autocomplete(originInput, options);
        const destAC = new google.maps.places.Autocomplete(destInput, options);

        originAC.addListener("place_changed", () => {{
          const p = originAC.getPlace();
          if (!p.geometry) return;
          sendDataToStreamlit("origin", {{
            name: p.name,
            lat: p.geometry.location.lat(),
            lng: p.geometry.location.lng()
          }});
        }});

        destAC.addListener("place_changed", () => {{
          const p = destAC.getPlace();
          if (!p.geometry) return;
          sendDataToStreamlit("dest", {{
            name: p.name,
            lat: p.geometry.location.lat(),
            lng: p.geometry.location.lng()
          }});
        }});
      }}
    </script>
    <script async defer src="https://maps.googleapis.com/maps/api/js?key={API_KEY}&libraries=places&callback=initMap"></script>
  </body>
</html>
"""

# HTML Bileşeni ve Listener
components.html(html_code, height=100)

# Javascript'ten gelen mesajı yakalamak için gizli bir "listener" scripti
# Streamlit URL'ini günceller ve sayfayı yeniler.
js_listener = """
<script>
window.addEventListener("message", (event) => {
    // Güvenlik kontrolü yapılabilir
    const data = event.data;
    if (data.type === "streamlit:message") {
        const url = new URL(window.location);
        url.searchParams.set(data.key, data.value);
        window.history.pushState({}, "", url);
        // Streamlit'i yeniden tetiklemek için ufak bir trick (bazen gereklidir)
        window.parent.postMessage({type: "streamlit:rerun"}, "*"); 
        location.reload(); 
    }
});
</script>
"""
components.html(js_listener, height=0, width=0)


# ---- Python Tarafı Hesaplama ----
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Ayarlar")
    step_km = st.number_input("Bölüm Mesafesi (km)", value=10.75, step=0.25, format="%.2f")
    
    if origin_data:
        st.success(f"🟢 **A:** {origin_data['name']}")
    else:
        st.info("Yukarıdan A noktasını seçin.")
        
    if dest_data:
        st.error(f"🔴 **B:** {dest_data['name']}")
    else:
        st.info("Yukarıdan B noktasını seçin.")
        
    if origin_data and dest_data:
        btn_calc = st.button("Rotayı Hesapla", type="primary")

with col2:
    if origin_data and dest_data: # Butona basmadan da hesaplatabiliriz veya butona bağlayabiliriz
        with st.spinner("Google'dan rota alınıyor ve bölünüyor..."):
            pts, err = get_directions_polyline(
                origin_data['lat'], origin_data['lng'],
                dest_data['lat'], dest_data['lng']
            )
            
            if err:
                st.error(f"Hata oluştu: {err}")
            else:
                # Hesapla
                total_km, segments, breaks = split_route_by_step_km(pts, step_km)
                
                st.subheader(f"Sonuç: {len(breaks)} Mola Noktası")
                
                # --- PyDeck Harita ---
                # Rota Çizgisi Verisi
                path_layer_data = [{"path": [[p[1], p[0]] for p in pts]}] # Lon, Lat formatı
                
                # Durak Noktaları Verisi
                points_layer_data = []
                for i, bp in enumerate(breaks):
                    points_layer_data.append({
                        "lng": bp[1], 
                        "lat": bp[0], 
                        "tooltip": f"{i+1}. Durak ({step_km * (i+1):.2f} km)"
                    })
                
                # Başlangıç ve Bitiş
                points_layer_data.insert(0, {"lng": origin_data['lng'], "lat": origin_data['lat'], "tooltip": "Başlangıç", "color": [0, 255, 0]})
                points_layer_data.append({"lng": dest_data['lng'], "lat": dest_data['lat'], "tooltip": "Varış", "color": [255, 0, 0]})

                # Görünüm Ortası
                mid_idx = len(pts) // 2
                view_state = pdk.ViewState(
                    latitude=pts[mid_idx][0],
                    longitude=pts[mid_idx][1],
                    zoom=7,
                    pitch=0
                )

                # Katmanlar
                layer_path = pdk.Layer(
                    "PathLayer",
                    path_layer_data,
                    get_path="path",
                    width_scale=20,
                    width_min_pixels=4,
                    get_color=[50, 100, 200],
                    pickable=True
                )

                layer_scatter = pdk.Layer(
                    "ScatterplotLayer",
                    points_layer_data,
                    get_position="[lng, lat]",
                    get_color="color || [255, 140, 0]", # Varsayılan turuncu, start/end özel renk
                    get_radius=2500, # Metre cinsinden
                    pickable=True,
                    stroked=True,
                    filled=True,
                    radius_min_pixels=5,
                    line_width_min_pixels=1
                )

                deck = pdk.Deck(
                    layers=[layer_path, layer_scatter],
                    initial_view_state=view_state,
                    map_style="mapbox://styles/mapbox/light-v10",
                    tooltip={"text": "{tooltip}"}
                )
                
                st.pydeck_chart(deck)
                
                # İstatistikler
                c1, c2 = st.columns(2)
                c1.metric("Toplam Mesafe", f"{total_km:.2f} km")
                c2.metric("Kalan Son Parça", f"{segments[-1]:.2f} km" if segments else "0")
                
                with st.expander("Detaylı Parça Listesi"):
                    st.write(segments)