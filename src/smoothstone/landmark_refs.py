"""Read a landmark's public facts and building geometry, keeping the sources."""
from __future__ import annotations

import hashlib
import json
import math
import re
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WIKIDATA = 'https://www.wikidata.org/w/api.php'
OVERPASS = 'https://overpass-api.de/api/interpreter'
WIKIPEDIA = 'https://en.wikipedia.org/w/api.php'


class LandmarkProblem(Exception):
    """A reference could not be resolved or contains insufficient geometry."""


def _request(url, data=None):
    agent = 'smoothstone' if url.startswith(OVERPASS) else 'smoothstone (https://github.com/baney75/smoothstone)'
    request = urllib.request.Request(url, data=data, headers={'User-Agent': agent})
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def _wiki(params):
    return _request(WIKIDATA + '?' + urllib.parse.urlencode({'format': 'json', **params}))


def _value(entity, prop):
    claims = sorted(entity.get('claims', {}).get(prop, []), key=lambda c: c.get('rank') != 'preferred')
    for claim in claims:
        if claim.get('rank') == 'deprecated':
            continue
        value = claim.get('mainsnak', {}).get('datavalue', {}).get('value')
        if value is not None:
            return value
    return None


def _item_ids(entity, prop):
    for claim in entity.get('claims', {}).get(prop, []):
        val = claim.get('mainsnak', {}).get('datavalue', {}).get('value')
        if claim.get('rank') != 'deprecated' and isinstance(val, dict) and val.get('id'):
            yield val['id']


# Wikidata unit items: metre, centimetre, millimetre, kilometre, foot, inch, yard.
# A length in a unit not listed here is dropped rather than read as metres.
METRES_PER_UNIT = {'Q11573': 1.0, 'Q174728': 0.01, 'Q174789': 0.001, 'Q828224': 1000.0,
                   'Q3710': 0.3048, 'Q218593': 0.0254, 'Q482798': 0.9144}


def _quantity(value):
    if not isinstance(value, dict) or 'amount' not in value:
        return None
    amount = float(value['amount'])
    unit = value.get('unit', '').rsplit('/', 1)[-1]
    factor = METRES_PER_UNIT.get(unit)
    return None if factor is None else amount * factor


def resolve(name: str, job_root: Path) -> dict:
    """Return sourced facts for the closest structure found by name."""
    normalized = ' '.join(name.casefold().split())
    key = hashlib.sha256(f'2 {normalized}'.encode()).hexdigest()  # 2: the ranking that chose the answer
    cache = Path.home() / '.cache' / 'smoothstone' / 'wikidata' / (key + '.json')
    ref_path = Path(job_root) / 'refs' / 'landmark.json'
    if cache.exists() and time.time() - cache.stat().st_mtime < 7 * 86400:
        try:
            ref = json.loads(cache.read_text())
            if (ref.get('id') and ref.get('latitude') is not None and ref.get('longitude') is not None
                    and (ref.get('matched_name') == normalized or ref.get('label', '').casefold() == normalized)):
                wikidata_height = _quantity(_value(ref.get('wikidata_raw', {}), 'P2048'))
                if wikidata_height is not None:
                    ref['height'] = wikidata_height
                _write_atomic(ref_path, json.dumps(ref, indent=2, ensure_ascii=False) + '\n')
                return ref
        except (OSError, ValueError, TypeError):
            pass
    try:
        result = _wiki({'action': 'wbsearchentities', 'search': name, 'language': 'en', 'limit': 15})
        hits = result.get('search', [])
        if not hits:
            raise LandmarkProblem(f'No Wikidata entity found for {name}.')
        ids = '|'.join(hit['id'] for hit in hits)
        entities = _wiki({'action': 'wbgetentities', 'ids': ids,
                          'props': 'labels|descriptions|claims|sitelinks', 'languages': 'en'}).get('entities', {})
        forbidden = re.compile(r'\b(painting|film|song|book|album|photograph|person|surname|disambiguation)\b', re.I)
        structure = re.compile(r'\b(cathedral|church|abbey|building|structure|mosque|palace|tower|temple|monument|mausoleum|castle|bridge|landmark|basilica|shrine|fortress|opera house|skyscraper|tomb|arch|gate|amphitheat(?:re|er)|theat(?:re|er)|stadium|museum|statue|chapel|minster|lighthouse|pyramid|venue|hall|library|monastery|priory|synagogue|pagoda|observatory|obelisk|aqueduct|villa|mansion|citadel|fort|fortification|house|ch[aâ]teau|hotel|fountain|dam|windmill|capitol|ruins?|archaeological)\b', re.I)
        place = re.compile(r'\b(district|place|airport|state|kingdom|city|town|village|hamlet|municipality|commune|suburb|neighbou?rhood|ward|parish|borough|county|region|province|country|island|river|lake|street|road|square|station|stop|school|company|settlement|locality|community|area|territory|constituency|capital|mountain|hill|valley|park)\b', re.I)
        # The words before the first place say what the thing is: a "human settlement in Tower Hamlets" is no tower.
        kind = re.compile(r'\b(?:in|of|on|at|near|by|from|within|between|for|to|with|known|serving|named)\b|[,;(]', re.I)
        candidates = []
        for order, hit in enumerate(hits):
            entity = entities.get(hit['id'], {})
            if not _value(entity, 'P625'):
                continue
            description = hit.get('description', '')
            if forbidden.search(description):
                continue
            # An exact name counts first only with evidence that this is a building: its own kind says so,
            # or it has an architectural style, an architect or a count of floors.
            named = any(' '.join(label.casefold().split()) == normalized for label in
                        (hit.get('label', ''), hit.get('match', {}).get('text', '')))
            what = kind.split(re.sub(r'^\s*\([^)]*\)', '', description), maxsplit=1)[0].strip()
            designed = any(_value(entity, claim) for claim in ('P149', 'P84', 'P1101'))
            words = [word.group().casefold() for word in place.finditer(what)]
            # A "cathedral city" is a city and an "island off the coast" an island; a "parish church" ends in its kind.
            placed = bool(words) and not any(m.end() == len(what) for m in structure.finditer(what))
            # A station or a school is a building when it has an architect; a town of one style is still a town.
            if placed and designed and set(words) <= {'station', 'school', 'airport'}:
                placed = False
            building = not placed and bool(structure.search(what) or designed)
            rank = 2 * named + building if named and not placed and (what or building) else int(building)
            candidates.append(((rank, bool(structure.search(description)), named, -order), hit, entity))
        if not candidates:
            raise LandmarkProblem(f'No building with coordinates found for {name}.')
        _, hit, entity = max(candidates, key=lambda x: x[0])
        entity_id = hit['id']
        source = f'https://www.wikidata.org/wiki/{entity_id}'
        coordinate = _value(entity, 'P625')
        ref = {'id': entity_id, 'label': hit.get('label', name), 'matched_name': normalized,
               'latitude': coordinate['latitude'], 'longitude': coordinate['longitude'],
               'height': _quantity(_value(entity, 'P2048')),
               'length': _quantity(_value(entity, 'P2043')),
               'width': _quantity(_value(entity, 'P2049')),
               'image': _value(entity, 'P18'), 'source': source,
               'sources': {key: source for key in ('latitude', 'longitude', 'height', 'length', 'width')
                           if key in ('latitude', 'longitude') or _value(entity, {'height': 'P2048', 'length': 'P2043', 'width': 'P2049'}.get(key))}}
        styles = []
        for claim in entity.get('claims', {}).get('P149', []):
            value = claim.get('mainsnak', {}).get('datavalue', {}).get('value', {})
            if value.get('id'):
                styles.append(value['id'])
        if styles:
            style_entities = _wiki({'action': 'wbgetentities', 'ids': '|'.join(styles), 'props': 'labels', 'languages': 'en'}).get('entities', {})
            ref['style'] = [style_entities.get(s, {}).get('labels', {}).get('en', {}).get('value', s) for s in styles]
        else:
            ref['style'] = []
        title = entity.get('sitelinks', {}).get('enwiki', {}).get('title')
        ref['wikipedia_url'] = ('https://en.wikipedia.org/wiki/' + urllib.parse.quote(title.replace(' ', '_'))) if title else None
        ref['osm_way'] = _value(entity, 'P10689')
        ref['osm_relation'] = _value(entity, 'P402')
        for key in ('style', 'image', 'osm_way', 'osm_relation'):
            if ref[key]:
                ref['sources'][key] = source
        ref['wikidata_raw'] = entity
        if title:
            try:
                params = {'action': 'query', 'prop': 'pageimages|extracts', 'titles': title,
                          'pithumbsize': '1000', 'exintro': '1', 'explaintext': '1', 'format': 'json'}
                wiki = _request(WIKIPEDIA + '?' + urllib.parse.urlencode(params))
                pages = wiki.get('query', {}).get('pages', {})
                page = next(iter(pages.values()), {})
                ref['wikipedia_extract'] = page.get('extract', '')
                ref['wikipedia_image'] = page.get('thumbnail', {}).get('source')
                if any(ref[key] is None for key in ('height', 'length', 'width')):
                    params = {'action': 'parse', 'page': title, 'prop': 'wikitext', 'format': 'json'}
                    parsed = _request(WIKIPEDIA + '?' + urllib.parse.urlencode(params))
                    wikitext = parsed.get('parse', {}).get('wikitext', {}).get('*', '')
                    ref['wikipedia_infobox'] = wikitext[:wikitext.find('\n}}') + 3] if '\n}}' in wikitext else ''
                    for key in ('height', 'length', 'width'):
                        if ref[key] is not None:
                            continue
                        field = re.search(r'^\s*\|\s*' + key + r'(?:_m)?\s*=\s*([^\n]+)',
                                          ref['wikipedia_infobox'], re.I | re.M)
                        if field:
                            value = re.search(r'(?:\{\{convert\|\s*)?(\d+(?:\.\d+)?)\s*(?:\|\s*)?(?:m(?:et(?:re|er)s?)?\b)', field.group(1), re.I)
                            if value:
                                ref[key] = float(value.group(1))
                                ref['sources'][key] = ref['wikipedia_url']
            except Exception:
                pass
        ref_dir = Path(job_root) / 'refs'
        ref_dir.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(ref, indent=2, ensure_ascii=False) + '\n'
        _write_atomic(ref_dir / 'landmark.json', encoded)
        _write_atomic(cache, encoded)
        return ref
    except LandmarkProblem:
        raise
    except Exception as exc:
        raise LandmarkProblem(f'Could not resolve {name}: {exc}') from exc


def _inside(point, ring):
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2-x1)*(y-y1)/(y2-y1)+x1:
            inside = not inside
    return inside


def _area(ring):
    return abs(sum(a[0]*b[1] - b[0]*a[1] for a, b in zip(ring, ring[1:] + ring[:1]))) / 2


def _centroid(ring):
    terms = [a[0]*b[1]-b[0]*a[1] for a, b in zip(ring, ring[1:]+ring[:1])]
    signed = sum(terms)
    if abs(signed) < 1e-9:
        return (sum(p[0] for p in ring)/len(ring), sum(p[1] for p in ring)/len(ring))
    return (sum((a[0]+b[0])*t for a,b,t in zip(ring, ring[1:]+ring[:1], terms))/(3*signed),
            sum((a[1]+b[1])*t for a,b,t in zip(ring, ring[1:]+ring[:1], terms))/(3*signed))


def _join(segments):
    segments = [s[:] for s in segments if len(s) >= 2]
    rings = []
    while segments:
        ring = segments.pop(0)
        while ring[0] != ring[-1] and segments:
            found = False
            for i, segment in enumerate(segments):
                if ring[-1] == segment[0]:
                    ring += segment[1:]
                elif ring[-1] == segment[-1]:
                    ring += segment[-2::-1]
                else:
                    continue
                segments.pop(i)
                found = True
                break
            if not found:
                break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring[:-1])
    return rings


def parse_osm(data: dict, refs: dict) -> dict:
    """Project ways and multipolygon relations; keep parts within the chosen outline."""
    lat0, lon0 = refs['latitude'], refs['longitude']
    def project(p):
        return ((p['lon']-lon0)*111320*math.cos(math.radians(lat0)), (p['lat']-lat0)*111320)
    def polygons(el):
        if el['type'] == 'way':
            geom = el.get('geometry', [])
            rings = _join([[project(p) for p in geom]])
            return [[ring] for ring in rings]
        members = el.get('members', [])
        outer = _join([[project(p) for p in m.get('geometry', [])] for m in members if m.get('role') in ('outer', '')])
        inner = _join([[project(p) for p in m.get('geometry', [])] for m in members if m.get('role') == 'inner'])
        return [[ring] + [hole for hole in inner if _inside(_centroid(hole), ring)] for ring in outer]
    candidates, pieces = [], []
    for el in data.get('elements', []):
        if el.get('type') not in ('way', 'relation'):
            continue
        tags = el.get('tags', {})
        if not ('building' in tags or 'building:part' in tags):
            continue
        for poly in polygons(el):
            item = {'id': el['id'], 'type': el['type'], 'footprint': poly, 'tags': tags,
                    'source': f"https://www.openstreetmap.org/{el['type']}/{el['id']}"}
            is_part = tags.get('building:part', 'no') != 'no'
            if is_part:
                pieces.append(item)
            if tags.get('building', 'no') != 'no' and not is_part:
                candidates.append(item)
    selected = None
    for candidate in candidates:
        if ((refs.get('osm_way') and candidate['type'] == 'way' and str(candidate['id']) == str(refs['osm_way'])) or
            (refs.get('osm_relation') and candidate['type'] == 'relation' and str(candidate['id']) == str(refs['osm_relation']))):
            selected = candidate
            break
    if selected is None and refs.get('id'):
        selected = next((c for c in candidates if c['tags'].get('wikidata') == refs['id']), None)
    if selected is None:
        containing = [c for c in candidates if _inside((0, 0), c['footprint'][0]) and
                      not any(_inside((0, 0), h) for h in c['footprint'][1:])]
        if containing:
            selected = min(containing, key=lambda c: _area(c['footprint'][0]))
    if selected is None:
        raise LandmarkProblem('OpenStreetMap has no building outline containing the coordinates.')
    boundary = selected['footprint']
    parts = [p for p in pieces if _inside(_centroid(p['footprint'][0]), boundary[0]) and
             not any(_inside(_centroid(p['footprint'][0]), h) for h in boundary[1:])]
    components = set(_item_ids(refs.get('wikidata_raw', {}), 'P527'))
    linked_towers = [c for c in candidates if c is not selected
                     and c['tags'].get('wikidata') in components
                     and (c['tags'].get('tower:type') == 'bell_tower' or c['tags'].get('building') == 'bell_tower')
                     and not _inside(_centroid(c['footprint'][0]), boundary[0])]
    return {'outline': boundary, 'parts': parts, 'source': selected['source'], 'tags': selected['tags'],
            'linked_towers': linked_towers, 'response_url': data.get('_smoothstone_response_url', OVERPASS)}


def load_pack(name, path=None, *, label=None):
    """Read one source URL per fact; a supplied pack overlays the bundled facts."""
    def bundled_pack(title):
        slug = re.sub(r'[^a-z0-9]+', '-', title.casefold().replace("'", '').replace('’', '')).strip('-')
        return Path(__file__).with_name('landmarks') / f'{slug}.json'

    bundled = bundled_pack(name)
    if label and not bundled.is_file():
        bundled = bundled_pack(label)
    facts = {}
    for candidate in (bundled if bundled.is_file() else None, path):
        if candidate is None:
            continue
        try:
            supplied = json.loads(Path(candidate).read_text())
            if not isinstance(supplied, dict) or not all(
                isinstance(fact, dict) and 'value' in fact and isinstance(fact.get('source'), str)
                and urllib.parse.urlparse(fact['source']).scheme in ('http', 'https')
                and urllib.parse.urlparse(fact['source']).netloc for fact in supplied.values()
            ):
                raise ValueError('use an object of facts with value and source URL on each fact')
            facts.update(supplied)
        except (OSError, ValueError) as exc:
            raise LandmarkProblem(f'Could not read landmark reference pack {candidate}: {exc}') from exc
    return facts


def _map_as_overpass(data):
    """Convert the OSM map API's node references into Overpass out geom."""
    elements = data.get('elements', [])
    nodes = {e['id']: e for e in elements if e.get('type') == 'node'}
    ways = {e['id']: e for e in elements if e.get('type') == 'way'}

    def geometry(way):
        ids = way.get('nodes', [])
        if any(n not in nodes for n in ids):
            return []
        return [{'lat': nodes[n]['lat'], 'lon': nodes[n]['lon']} for n in ids]

    converted = []
    for e in elements:
        if e.get('type') not in ('way', 'relation'):
            continue
        if not any(k in e.get('tags', {}) for k in ('building', 'building:part')):
            continue
        result = {k: v for k, v in e.items() if k in ('type', 'id', 'tags')}
        if e['type'] == 'way':
            result['geometry'] = geometry(e)
        else:
            result['members'] = [{'role': m.get('role', ''), 'geometry': geometry(ways[m['ref']])}
                                 for m in e.get('members', [])
                                 if m.get('type') == 'way' and m['ref'] in ways]
        converted.append(result)
    return {'elements': converted}


def _write_atomic(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(content)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def fetch(refs: dict, job_root: Path) -> dict:
    """Fetch and cache OSM responses in the job and shared cache."""
    lat, lon = refs['latitude'], refs['longitude']
    # The radius includes half the known span and is capped to bound public requests.
    span = max(refs.get('length') or 0, refs.get('width') or 0)
    radius = min(1000, max(220, math.ceil(span * 0.6)))
    nearby = ''.join(f'{kind}["{tag}"](around:{radius},{lat},{lon});'
                     for tag in ('building', 'building:part') for kind in ('way', 'relation'))
    explicit = ''
    for kind, key_name in (('way', 'osm_way'), ('relation', 'osm_relation')):
        identifier = str(refs.get(key_name) or '')
        if identifier.isdecimal():
            explicit += f'{kind}({identifier});'
    query = f'[out:json][timeout:40];({nearby}{explicit});out geom;'
    key = hashlib.sha256(query.encode()).hexdigest()
    cache = Path.home() / '.cache' / 'smoothstone' / 'osm' / (key + '.json')
    raw_cache = cache.parent / (key + '-map.json')
    overpass_cache = cache.parent / (key + '-overpass.json')
    ref_dir = Path(job_root) / 'refs'
    job_cache = ref_dir / 'overpass.json'
    try:
        if cache.exists():
            data = json.loads(cache.read_text())
            if raw_cache.exists():
                _write_atomic(ref_dir / 'osm-map.json', raw_cache.read_text())
            if overpass_cache.exists():
                _write_atomic(ref_dir / 'overpass-raw.json', overpass_cache.read_text())
        else:
            try:
                data = _request(OVERPASS, urllib.parse.urlencode({'data': query}).encode())
                data['_smoothstone_response_url'] = OVERPASS
                data['_smoothstone_query'] = query
                # Preserve a successful response even when it contains no geometry.
                _write_atomic(ref_dir / 'overpass-raw.json', json.dumps(data, ensure_ascii=False))
                _write_atomic(overpass_cache, json.dumps(data, ensure_ascii=False))
                if not data.get('elements'):
                    raise LandmarkProblem('Overpass returned no elements')
            except (OSError, ValueError, LandmarkProblem):
                # OSM's map API supplies the same primitives when Overpass is unavailable.
                dx = radius / (111320 * math.cos(math.radians(lat)))
                dy = radius / 111320
                bbox = ','.join(str(v) for v in (lon-dx, lat-dy, lon+dx, lat+dy))
                url = 'https://api.openstreetmap.org/api/0.6/map.json?' + urllib.parse.urlencode({'bbox': bbox})
                raw = _request(url)
                raw_text = json.dumps(raw, ensure_ascii=False)
                _write_atomic(ref_dir / 'osm-map.json', raw_text)
                _write_atomic(raw_cache, raw_text)
                data = _map_as_overpass(raw)
                data['_smoothstone_response_url'] = url
                data['_smoothstone_query'] = query
            _write_atomic(cache, json.dumps(data, ensure_ascii=False))
        _write_atomic(job_cache, json.dumps(data, ensure_ascii=False))
        return parse_osm(data, refs)
    except LandmarkProblem:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LandmarkProblem(f'OpenStreetMap lookup failed: {exc}') from exc
