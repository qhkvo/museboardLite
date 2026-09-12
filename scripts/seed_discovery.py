#!/usr/bin/env python3
"""Create an optional original geometric demo collection. Requires Pillow."""
import argparse
import io
import json
from urllib.request import Request, urlopen
from uuid import uuid4
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    base = args.api.rstrip('/')
    def request(path, data, content_type):
        with urlopen(Request(base + path, data=data, headers={'Content-Type': content_type}), timeout=60) as response:
            return json.load(response)
    board = request('/boards', json.dumps({'name': 'Discovery samples', 'description': 'Original generated geometric artwork: warm, cool, and green pairs. No external images.'}).encode(), 'application/json')
    for name, background, ink in [('warm', '#efbd81', '#b64b38'), ('cool', '#a6cdd9', '#355c8b'), ('green', '#bbcea0', '#49744a')]:
        for shape in ['circles', 'blocks']:
            image = Image.new('RGB', (640, 480), background)
            draw = ImageDraw.Draw(image)
            for box in [(60, 70, 280, 290), (340, 210, 540, 410)]:
                (draw.ellipse if shape == 'circles' else draw.rectangle)(box, fill=ink)
            buffer = io.BytesIO(); image.save(buffer, format='PNG')
            boundary = uuid4().hex
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}-{shape}.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + buffer.getvalue() + f'\r\n--{boundary}--\r\n'.encode())
            request(f"/boards/{board['id']}/images", body, f'multipart/form-data; boundary={boundary}')
    print(f"Created Discovery samples: {board['id']} (6 images). Workers will process them automatically.")


if __name__ == '__main__':
    main()
