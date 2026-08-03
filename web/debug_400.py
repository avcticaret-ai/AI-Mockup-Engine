import requests
from PIL import Image
import io

url = 'http://127.0.0.1:8080/render'

# PIL ile şeffaf PNG üret
img = Image.new('RGBA', (500, 500), color=(255, 0, 0, 128))
img_byte_arr = io.BytesIO()
img.save(img_byte_arr, format='PNG')
img_bytes = img_byte_arr.getvalue()

tests = [
    ('referans', {}),
    ('scale 1.38', {'scale': '1.38'}),
    ('displace 30', {'displace': '30.0'}),
    ('flip_v', {'flip_v': 'true'}),
    ('offset_x 0.3', {'offset_x': '0.3', 'quad_override': 'true'})
]

print(f"{'TEST':<15} | {'STATUS':<8} | {'BOYUT (BYTE)':<15} | SUNUCU PARAMETRELERİ")
print("-" * 75)

for name, payload in tests:
    # 'design' YERİNE 'design_file' KULLANILDI
    files = {'design_file': ('test.png', img_bytes, 'image/png')}
    data = {'model': 'bella-canvas-3001/black'}
    data.update(payload)
    
    res = requests.post(url, data=data, files=files)
    params_header = res.headers.get('X-Render-Params', 'HEADER_YOK')
    
    if res.status_code == 200:
        print(f"{name:<15} | {res.status_code:<8} | {len(res.content):<15} | {params_header}")
    else:
        print(f"{name:<15} | {res.status_code:<8} | HATA: {res.text}")
