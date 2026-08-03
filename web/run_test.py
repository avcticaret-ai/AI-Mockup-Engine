import requests
from PIL import Image
import io

url = 'http://127.0.0.1:8080/render'

# PIL ile motorun kabul edeceği 500x500 gerçek şeffaf PNG üret
img = Image.new('RGBA', (500, 500), color=(255, 0, 0, 128))
img_byte_arr = io.BytesIO()
img.save(img_byte_arr, format='PNG')
png_bytes = img_byte_arr.getvalue()

tests = [
    ('referans', {}),
    ('scale 1.38', {'scale': '1.38'}),
    ('displace 30', {'displace': '30.0'}),
    ('flip_v', {'flip_v': 'true'}),
    ('offset_x 0.3', {'offset_x': '0.3', 'quad_override': 'true'})
]

print("TEST            | STATUS     | SIZEOF_RESPONSE | RECV_HEADER")
print("-" * 75)

for name, payload in tests:
    files = {'design': ('test.png', png_bytes, 'image/png')}
    data = {'model': 'bella-canvas-3001/black'}
    data.update(payload)
    try:
        res = requests.post(url, data=data, files=files)
        recv = res.headers.get('X-Render-Params', 'header_yok')
        size = len(res.content)
        print(f"{name:<15} | {res.status_code:<10} | {size:<15} | {recv}")
    except Exception as e:
        print(f"{name:<15} | HATA       | {e}")
