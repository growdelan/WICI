"""Public EUMETView LI AFA images: detected optical activity, not strike locations."""
import asyncio
import math
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

from wici.effis import BOUNDS, HEIGHT, MERCATOR_BBOX, WIDTH, decode_png

ENDPOINT = 'https://view.eumetsat.int/geoserver/wms'
LAYER = 'mtg_fd:li_afa'
STYLE = 'mtg_li_afa'
REFRESH = 300
NS = {'w':'http://www.opengis.net/wms'}
SOURCE = 'https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Ali_afa'


class LightningUnavailable(Exception):
    pass


def instant(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Brak strefy czasu EUMETSAT')
    return parsed.astimezone(UTC)


def parse_times(body, now):
    if b'<!ENTITY' in body.upper() or b'<!DOCTYPE' in body.upper():
        raise ValueError('Nieprawidłowy dokument WMS')
    root = ET.fromstring(body)
    for layer in root.findall('.//w:Layer',NS):
        if layer.findtext('w:Name',namespaces=NS) != LAYER:
            continue
        dimension = next((d for d in layer.findall('w:Dimension',NS) if d.get('name') == 'time'),None)
        if dimension is None or not dimension.text:
            raise ValueError('Brak czasu warstwy EUMETSAT')
        parts = dimension.text.strip().split('/')
        if len(parts) == 3 and parts[2] == 'PT5M':
            start, end = instant(parts[0]), instant(parts[1])
            times = [end-timedelta(minutes=5*i) for i in range(13) if end-timedelta(minutes=5*i)>=start]
        else:
            times = [instant(value.strip()) for value in dimension.text.split(',')]
        times = sorted(set(times))
        if not times or len(times)>10000 or times[-1]>now+timedelta(minutes=5) or (
                now-times[-1]>timedelta(hours=3)):
            raise ValueError('Czas źródła poza bieżącym zakresem')
        return [time for time in times[-13:] if time>=times[-1]-timedelta(hours=1)]
    raise ValueError('Brak warstwy LI AFA')


class LightningService:
    def __init__(self, client, clock, timeout=20, enabled=True, demo=False):
        self.client,self.clock,self.timeout,self.enabled,self.demo = client,clock,timeout,enabled,demo
        self.lock,self.image_lock = asyncio.Lock(),asyncio.Lock()
        self.snapshot,self.legend,self.next_due,self.blocked_until = None,None,None,None
        self.images = OrderedDict()
        self.error = ''

    def base(self):
        return {'enabled':self.enabled and not self.demo,'status':'disabled','frames':[], 'stale':False,
                'message':'EUMETSAT wyłączony w demonstracji (bez sieci).' if self.demo else 'Warstwa wyłączona w konfiguracji.',
                'fetched_at':None,'bounds':BOUNDS,'period_minutes':5,'refresh_seconds':REFRESH,
                'source_name':'EUMETSAT / Meteosat Lightning Imager AFA','source_url':SOURCE,
                'legend_url':'/api/lightning/legend','latest_end':None,'delay_minutes':None}

    def result(self):
        data = dict(self.snapshot or {**self.base(),'enabled':True,'status':'error'})
        end = instant(data['latest_end']) if data['latest_end'] else None
        delay = max(0,int((self.clock()-end).total_seconds()/60)) if end else None
        data.update(delay_minutes=delay,stale=bool(self.error or (delay is not None and delay>15)))
        if self.error:
            data.update(status='error',message=self.error)
        elif data['stale']:
            data['message']='Ostatni dostępny okres kończy się ponad 15 minut temu; obraz nie opisuje bieżącej chwili.'
        return data

    async def fetch(self, params, limit):
        now = self.clock()
        if self.blocked_until and now<self.blocked_until:
            raise LightningUnavailable('Ponowienie EUMETSAT wstrzymane po błędzie/limicie.')
        async with self.client.stream('GET',ENDPOINT,params=params,timeout=self.timeout,follow_redirects=False) as response:
            if response.status_code!=200:
                delay=300
                if response.status_code==429:
                    value=response.headers.get('retry-after','')
                    try:
                        delay=float(value)
                    except ValueError:
                        try:
                            delay=(parsedate_to_datetime(value)-now).total_seconds()
                        except (TypeError,ValueError,OverflowError):
                            delay=300
                if not math.isfinite(delay):delay=300
                self.blocked_until=now+timedelta(seconds=max(300,min(delay,86400)))
                raise LightningUnavailable('Nie udało się odczytać EUMETSAT.')
            body=bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body)>limit:
                    raise LightningUnavailable('Odpowiedź EUMETSAT przekracza limit.')
            return bytes(body)

    async def metadata(self):
        if not self.enabled or self.demo:return self.base()
        async with self.lock:
            now=self.clock()
            if self.next_due and now<self.next_due:return self.result()
            self.next_due=now+timedelta(seconds=REFRESH)
            try:
                times=parse_times(await self.fetch({'SERVICE':'WMS','VERSION':'1.3.0','REQUEST':'GetCapabilities'},1024*1024),now)
                self.snapshot={**self.base(),'enabled':True,'status':'success','message':'','fetched_at':now.isoformat(),
                    'latest_end':(times[-1]+timedelta(minutes=5)).isoformat(), 'frames':[
                        {'time':time.isoformat(),'end':(time+timedelta(minutes=5)).isoformat(),
                         'timestamp':int(time.timestamp()),'image_url':f'/api/lightning/map?time={int(time.timestamp())}'}
                        for time in times]}
                self.error=''
            except (httpx.HTTPError,LightningUnavailable,ValueError,TypeError,ET.ParseError,OverflowError):
                self.error='Nie udało się odświeżyć EUMETSAT; zachowany obraz może być nieaktualny.'
            return self.result()

    async def image(self,time):
        data=await self.metadata()
        if not data['enabled']:raise LightningUnavailable(data['message'])
        frame=next((frame for frame in data['frames'] if frame['timestamp']==time),None)
        if frame is None or self.clock()-instant(frame['end'])>timedelta(hours=3):
            raise ValueError('Okres poza dostępną historią EUMETSAT')
        async with self.image_lock:
            if time in self.images:
                self.images.move_to_end(time);return self.images[time]
            params={'SERVICE':'WMS','VERSION':'1.3.0','REQUEST':'GetMap','LAYERS':LAYER,'STYLES':STYLE,
                    'CRS':'EPSG:3857','BBOX':MERCATOR_BBOX,'WIDTH':WIDTH,'HEIGHT':HEIGHT,'FORMAT':'image/png',
                    'TRANSPARENT':'true','TIME':frame['time'].replace('+00:00','Z')}
            try:
                body=await self.fetch(params,4*1024*1024)
                width,height,channels,rows=decode_png(body)
                if (width,height,channels)!=(WIDTH,HEIGHT,4):raise ValueError('Nieprawidłowy obraz LI AFA')
            except (httpx.HTTPError,ValueError,LightningUnavailable) as exc:
                self.blocked_until=max(self.blocked_until or self.clock(),self.clock()+timedelta(seconds=60))
                raise LightningUnavailable('Nie udało się pobrać obrazu wyładowań.') from exc
            self.images[time]={'body':body,'rows':rows,'frame':frame,
                               'has_visible_activity':any(any(row[3::4]) for row in rows)}
            while len(self.images)>6:self.images.popitem(last=False)
            return self.images[time]

    async def legend_image(self):
        if not self.enabled or self.demo:raise LightningUnavailable(self.base()['message'])
        async with self.image_lock:
            if self.legend is None:
                try:
                    body=await self.fetch({'SERVICE':'WMS','VERSION':'1.3.0','REQUEST':'GetLegendGraphic',
                                          'LAYER':LAYER,'FORMAT':'image/png'},1024*1024)
                    decode_png(body)
                except (httpx.HTTPError,ValueError) as exc:
                    raise LightningUnavailable('Legenda EUMETSAT niedostępna.') from exc
                self.legend=body
            return self.legend

    async def point(self,time,lat,lon):
        if not (math.isfinite(lat) and math.isfinite(lon) and 49<=lat<=55 and 14<=lon<=24.2):
            raise ValueError('Punkt poza zakresem warstwy Polski')
        image=await self.image(time)
        west,south,east,north=map(float,MERCATOR_BBOX.split(','))
        x=math.radians(lon)*6378137
        y=math.log(math.tan(math.pi/4+math.radians(lat)/2))*6378137
        i=min(WIDTH-1,max(0,int((x-west)/(east-west)*WIDTH)))
        j=min(HEIGHT-1,max(0,int((north-y)/(north-south)*HEIGHT)))
        pixel=image['rows'][j][i*4:i*4+4]
        data=self.result()
        return {'latitude':lat,'longitude':lon,'period_start':image['frame']['time'],
                'period_end':image['frame']['end'],'visible_activity':bool(pixel[3]),
                'stale':data['stale'] or self.clock()-instant(image['frame']['end'])>timedelta(minutes=15),
                'source_url':SOURCE,'note':'Odczyt piksela wizualizacji AFA; bez liczby pojedynczych wyładowań i bez rozróżnienia doziemnych.'}
