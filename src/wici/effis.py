"""Bounded local proxy for the official EFFIS/GWIS ECMWF FWI forecast WMS."""
import asyncio
import math
import struct
import xml.etree.ElementTree as ET
import zlib
from datetime import date, timedelta
from zoneinfo import ZoneInfo

ENDPOINT = 'https://maps.effis.emergency.copernicus.eu/gwis'
LAYER = 'ecmwf.fwi'
BOUNDS = [[49, 14], [55, 24.2]]
WIDTH, HEIGHT = 768, 768
MERCATOR_BBOX = ','.join(str(value) for value in (
    math.radians(14)*6378137, math.log(math.tan(math.pi/4+math.radians(49)/2))*6378137,
    math.radians(24.2)*6378137, math.log(math.tan(math.pi/4+math.radians(55)/2))*6378137))
SIGNATURE = b'\x89PNG\r\n\x1a\n'
LIMIT = 4 * 1024 * 1024


def decode_png(body):
    """Validate complete, non-interlaced RGB/RGBA PNG and undo PNG row filters."""
    if not body.startswith(SIGNATURE):
        raise ValueError('Serwer nie zwrócił obrazu PNG')
    pos, data, header, ended = 8, bytearray(), None, False
    while pos + 12 <= len(body):
        size = struct.unpack('>I', body[pos:pos+4])[0]
        kind = body[pos+4:pos+8]
        stop = pos+8+size
        if stop+4 > len(body) or zlib.crc32(body[pos+4:stop]) != struct.unpack('>I', body[stop:stop+4])[0]:
            raise ValueError('Niepełny obraz PNG')
        payload = body[pos+8:stop]
        if kind == b'IHDR':
            if header is not None or pos != 8 or size != 13:
                raise ValueError('Nieprawidłowy nagłówek PNG')
            header = struct.unpack('>IIBBBBB', payload)
        elif kind == b'IDAT':
            data.extend(payload)
        elif kind == b'IEND':
            if size or stop+4 != len(body):
                raise ValueError('Nieprawidłowy koniec PNG')
            ended = True
            break
        pos = stop+4
    if not ended or header is None:
        raise ValueError('Niepełny obraz PNG')
    width, height, depth, color, compression, filtering, interlace = header
    if not (0 < width <= 2048 and 0 < height <= 2048 and depth == 8 and color in (2, 6)
            and compression == filtering == interlace == 0):
        raise ValueError('Nieobsługiwany obraz PNG')
    channels = 4 if color == 6 else 3
    stride = width*channels
    expected = (stride+1)*height
    inflater = zlib.decompressobj()
    raw = inflater.decompress(data, expected+1)
    if len(raw) != expected or not inflater.eof or inflater.unused_data:
        raise ValueError('Nieprawidłowe dane PNG')
    rows, previous = [], bytearray(stride)
    for offset in range(0, expected, stride+1):
        method = raw[offset]
        row = bytearray(raw[offset+1:offset+1+stride])
        if method > 4:
            raise ValueError('Nieprawidłowy filtr PNG')
        for i in range(stride):
            left = row[i-channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i-channels] if i >= channels else 0
            if method == 1:
                row[i] = (row[i]+left) & 255
            elif method == 2:
                row[i] = (row[i]+up) & 255
            elif method == 3:
                row[i] = (row[i]+(left+up)//2) & 255
            elif method == 4:
                p = left+up-corner
                distances = (abs(p-left), abs(p-up), abs(p-corner))
                predictor = (left, up, corner)[distances.index(min(distances))]
                row[i] = (row[i]+predictor) & 255
        rows.append(bytes(row))
        previous = row
    return width, height, channels, rows


def validate_map(body):
    width, height, channels, rows = decode_png(body)
    if (width, height) != (WIDTH, HEIGHT):
        raise ValueError('Nieprawidłowy rozmiar mapy')
    if channels == 4 and not any(any(row[3::4]) for row in rows):
        raise ValueError('Brak danych prognozy dla wybranej daty')
    return body


def parse_capabilities(body):
    # No external entity loading; reject entity definitions explicitly.
    if b'<!ENTITY' in body.upper():
        raise ValueError('Nieprawidłowy dokument WMS')
    root = ET.fromstring(body)
    for layer in root.iter('Layer'):
        if layer.findtext('Name') == LAYER:
            extent = next((e for e in layer.findall('Extent') if e.get('name') == 'time'), None)
            if extent is None or not extent.text:
                raise ValueError('Brak wymiaru czasu WMS')
            return extent.text.strip()
    raise ValueError('Brak warstwy FWI')


def time_supported(extent, day):
    """Capabilities advertises a broad range; actual image must also be checked."""
    for value in extent.split(','):
        parts = value.strip().split('/')
        try:
            if len(parts) == 1 and date.fromisoformat(parts[0][:10]) == day:
                return True
            if len(parts) >= 2 and date.fromisoformat(parts[0][:10]) <= day <= date.fromisoformat(parts[1][:10]):
                return True
        except ValueError:
            continue
    return False


class EffisService:
    def __init__(self, client, clock, timeout=25, demo=False):
        self.client, self.clock, self.timeout, self.demo = client, clock, timeout, demo
        self.cache, self.legend, self.capabilities = {}, None, None
        self.lock = asyncio.Lock()

    def selected_date(self, day):
        today = self.clock().astimezone(ZoneInfo('Europe/Warsaw')).date()
        selected = day or today
        if selected not in [today+timedelta(days=n) for n in range(3)]:
            raise ValueError('EFFIS: dostępne są dziś, jutro i pojutrze (Europe/Warsaw)')
        return selected

    async def fetch(self, params, limit=LIMIT):
        import httpx
        for attempt in range(2):
            try:
                async with self.client.stream('GET', ENDPOINT, params=params, timeout=self.timeout,
                                              follow_redirects=False) as response:
                    if response.status_code != 200:
                        raise ValueError(f'Serwer EFFIS: HTTP {response.status_code}')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > limit:
                            raise ValueError('Zbyt duża odpowiedź EFFIS')
                return bytes(body)
            except httpx.TransportError:
                if attempt:
                    raise
                await asyncio.sleep(0.2)

    async def metadata(self, day=None):
        selected = self.selected_date(day)
        base = {'forecast_date': selected.isoformat(), 'issued_at': None, 'bounds': BOUNDS,
                'model': 'ECMWF FWI', 'available': False, 'image_url': None, 'legend_url': None,
                'fetched_at': None}
        if self.demo:
            return {**base, 'status': 'disabled', 'message': 'EFFIS wyłączony w trybie demo (bez sieci)'}
        async with self.lock:
            now = self.clock()
            # Bound cache across local midnight and provider outages.
            today = now.astimezone(ZoneInfo('Europe/Warsaw')).date()
            self.cache = {key: val for key, val in self.cache.items() if today <= key <= today+timedelta(days=2)}
            cached = self.cache.get(selected)
            if cached and now < cached['expires']:
                return cached['metadata']
            try:
                if self.capabilities is None or now >= self.capabilities[0]:
                    extent = parse_capabilities(await self.fetch({'SERVICE': 'WMS', 'VERSION': '1.1.1',
                                                                  'REQUEST': 'GetCapabilities'}, 1024*1024))
                    self.capabilities = (now+timedelta(hours=1), extent)
                if not time_supported(self.capabilities[1], selected):
                    raise ValueError('Brak daty prognozy w usłudze EFFIS')
                image = await self.fetch({'SERVICE': 'WMS', 'VERSION': '1.1.1', 'REQUEST': 'GetMap',
                    'LAYERS': LAYER, 'STYLES': '', 'FORMAT': 'image/png', 'TRANSPARENT': 'true',
                    'SRS': 'EPSG:3857', 'BBOX': MERCATOR_BBOX,
                    'WIDTH': str(WIDTH), 'HEIGHT': str(HEIGHT), 'TIME': selected.isoformat()})
                image = validate_map(image)
                if self.legend is None or now >= self.legend[0]:
                    legend = await self.fetch({'SERVICE': 'WMS', 'VERSION': '1.1.1', 'REQUEST': 'GetLegendGraphic',
                                               'LAYER': LAYER, 'STYLE': 'default', 'FORMAT': 'image/png'})
                    decode_png(legend)
                    self.legend = (now+timedelta(hours=1), legend)
                metadata = {**base, 'available': True, 'status': 'success', 'message': '',
                            'fetched_at': self.clock().isoformat(), 'image_url': f'/api/effis/map?day={selected}',
                            'legend_url': f'/api/effis/legend?day={selected}'}
                self.cache[selected] = {'metadata': metadata, 'image': image, 'legend': self.legend[1],
                                        'expires': self.clock()+timedelta(hours=1)}
            except Exception:  # noqa: BLE001 — provider text/HTML and transport internals stay local.
                metadata = {**base, 'status': 'error',
                            'message': 'Prognoza EFFIS niedostępna; spróbuj ponownie za kilka minut.'}
                self.cache[selected] = {'metadata': metadata, 'image': None, 'expires': now+timedelta(minutes=5)}
            return metadata

    async def map_image(self, day=None):
        selected = self.selected_date(day)
        metadata = await self.metadata(selected)
        return self.cache[selected]['image'] if metadata['available'] else None

    async def legend_image(self, day=None):
        selected = self.selected_date(day)
        metadata = await self.metadata(selected)
        return self.cache[selected]['legend'] if metadata['available'] else None
