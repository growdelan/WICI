"""Read-only presentation of admitted publisher documents, without event approval."""
import hashlib
import json
import re
from datetime import datetime

from wici.daily import civil_day, publication_day
from wici.sources.normalize import EXERCISE, administrative_index, location

SOURCES = {'imgw_meteo','rso','rcb','sg'}


def exercise_notice(text):
    return bool(EXERCISE.search(text) and not re.search(
        r'\bnie\s+(?:(?:są|jest|to|były|było|będą|będzie)\s+){0,2}(?:ćwicze|cwicze|test|trening)',
        text,re.IGNORECASE))


def topic(text, source):
    """Navigation tags only: no inferred severity, occurrence, or progression."""
    if exercise_notice(text):
        return 'other_context'
    if source=='sg' or re.search(r'\bgranic\w*|przejści\w* graniczn|\bdpg\b',text,re.IGNORECASE):
        return 'border'
    if re.search(r'atak\w* powietrzn|przestrze\w* powietrzn',text,re.IGNORECASE):
        return 'airspace'
    if source=='imgw_meteo' or re.search(r'susza hydrolog|ostrzeżeni\w* hydrolog|burz|siln\w* wiatr|upał|intensywn\w* opad|przymrozk',text,re.IGNORECASE):
        return 'weather'
    if re.search(r'\b(?:wypadek|kolizja|zderzenie)\b|utrudnien|\bdk\b|\bdroga\b|ruch\w* drogow|przebudowa drogi',text,re.IGNORECASE):
        return 'infrastructure'
    return 'public_safety'


def original_url(source_id,fields,fallback):
    url=fields.get('source_pdf_url')
    if source_id=='imgw_meteo' and isinstance(url,str) and re.fullmatch(
            r'https://danepubliczne\.imgw\.pl/data/(?:current/ost_meteo/[A-Za-z0-9_-]+\.pdf|arch/ost_meteo/[0-9]{4}/(?:0[1-9]|1[0-2])\.zip)',url):
        return url
    return fallback


def communication(row, fields, now):
    item=dict(row)
    item['original_url']=original_url(item['source_id'],fields,item['url'])
    event=fields.get('event',{})
    item.update(summary=item['text'],category=topic(item['title']+' '+item['text'],item['source_id']),
        warning_status='unknown',locations=[],official_severity=None,valid_from=None,valid_until=None,
        fields=fields)
    item['publication_day'],item['publication_day_basis']=publication_day(
        dict(item,source_published_date=fields.get('source_published_date')),item['first_seen_at'])
    item['source_published_date']=fields.get('source_published_date')
    exercise=exercise_notice(item['title']+' '+item['text'])
    item['communication_type']='exercise' if exercise else 'notice'
    # Only recognised administrative identities are drawn. A publisher distribution
    # area is never promoted to a point or incident area.
    for loc in event.get('locations',[]):
        code=loc.get('admin_code')
        if loc.get('precision')=='administrative' and code in administrative_index():
            safe=location(code,'warning_area' if item['source_id']=='imgw_meteo' else 'notification_area',
                loc.get('source') or item['source_id'])
            item['locations'].append(safe)
    # RCB has no structured provinces: admit only a province name explicitly in a
    # clause referring to voivodeships, not arbitrary place-name matching.
    if item['source_id']=='rcb' and not item['locations']:
        for clause in re.findall(r'(?:województw\w*|woj\.)\s+([^.!?;]{1,350})',item['text'],re.IGNORECASE):
            for code,name in administrative_index().items():
                if len(code)!=2:
                    continue
                stem=name.removesuffix('ie')
                if (re.search(r'(?<!\w)'+re.escape(stem)+r'(?:ie|iego|im|ich)(?!\w)',clause,re.IGNORECASE)
                        and not any(loc['admin_code']==code for loc in item['locations'])):
                    item['locations'].append(location(code,'notification_area','Województwo jawnie wymienione w komunikacie RCB'))
    if item['source_id']=='imgw_meteo' and not exercise and fields.get('recognized_warning_type') is True:
        item.update(communication_type='warning',category='weather',
            official_severity=event.get('official_severity'),valid_from=event.get('valid_from'),
            valid_until=event.get('valid_until'),warning_status=event.get('warning_status','unknown'))
        from wici.processing.time import warning_status
        item['warning_status']=warning_status(item,now)
    elif exercise:
        item['category']='other_context'
    item['display_window']={k:event.get(k) for k in ('valid_from','valid_until')} if item['source_id']=='rso' else None
    item['map_note']='Obszar ostrzeżenia IMGW' if item['source_id']=='imgw_meteo' else 'Obszar powiadomienia; nie ustalone miejsce zdarzenia'
    item['redacted']=bool(re.search(r'pominięt|pominięta|Usunięto potencjalnie',item['text']+' '+(item.get('redaction_note') or ''),re.IGNORECASE))
    if item['source_id']=='imgw_meteo' and fields.get('source_pdf_url'):
        item['compact_group_key']=hashlib.sha256(json.dumps([
            fields['source_pdf_url'],item['source_published_at'],item['text'],
            item['valid_from'],item['valid_until'],item['official_severity'],item['warning_status']
        ],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return item


def matches(item, filters, now):
    for key in ('communication_type','category','source_id'):
        if filters.get(key) and item.get(key)!=filters[key]:
            return False
    if filters.get('voivodeship') and not any(loc['admin_code'].startswith(filters['voivodeship']) for loc in item['locations']):
        return False
    day=filters.get('date')
    if not day:
        return True
    if item['publication_day']==day or civil_day(item.get('source_updated_at'))==day:
        return True
    if not filters.get('include_active') or day!=civil_day(now):
        return False
    window=item['display_window'] or (item if item['source_id']=='imgw_meteo' else {})
    start,end=window.get('valid_from'),window.get('valid_until')
    # Missing/technical dates never imply continued validity. RSO window denotes
    # availability of the message only, not ongoing physical danger.
    try:
        return bool(start and end and datetime.fromisoformat(start)<=now<datetime.fromisoformat(end))
    except (TypeError,ValueError):
        return False
