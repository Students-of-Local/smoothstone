"""Read a landmark's public facts and building geometry, keeping the sources."""
from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import os
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WIKIDATA = 'https://www.wikidata.org/w/api.php'
OVERPASS = 'https://overpass-api.de/api/interpreter'
WIKIPEDIA = 'https://en.wikipedia.org/w/api.php'


class LandmarkProblem(Exception):
    """A reference could not be resolved or contains insufficient geometry."""


class PlainShape(LandmarkProblem):
    """The map has one plain shape and no more: an open model is better, and this is better than nothing."""


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


def _wikipedia(params):
    return _request(WIKIPEDIA + '?' + urllib.parse.urlencode({'action': 'query', 'format': 'json', 'prop': 'pageprops',
                                                              'ppprop': 'wikibase_item', **params}))


def _words(text):
    """A name's words, without accents or punctuation: "Sacr\u00e9-C\u0153ur" and "Sacre Coeur" are one name."""
    text = unicodedata.normalize('NFKD', text.casefold().replace('\u0153', 'oe')).replace("'", '').replace('\u2019', '')
    words = re.findall(r'[^\W_]+', ''.join(c for c in text if not unicodedata.combining(c)))
    return tuple('st' if w == 'saint' else w for w in (words[1:] if words[:1] == ['the'] and len(words) > 1 else words))


def _matches(name):
    """What Wikidata and Wikipedia find for a name: hits, their entities, and whether Wikipedia answered."""
    def told(reply):
        if 'error' in reply:  # a busy server says so in a page that loads
            raise ValueError(reply['error'])
        return reply
    hits = {hit['id']: hit for hit in told(_wiki({'action': 'wbsearchentities', 'search': name, 'language': 'en',
                                                  'limit': 15})).get('search', [])}
    answered = True
    for params in ({'titles': name, 'redirects': 1}, {'generator': 'search', 'gsrsearch': name, 'gsrlimit': 6}):
        try:
            pages = told(_wikipedia(params)).get('query', {}).get('pages', {}).values()
        except (OSError, ValueError, http.client.HTTPException):
            answered = False  # Wikidata's own search still answers
            continue
        for page in pages:
            item = page.get('pageprops', {}).get('wikibase_item')
            if item:
                hit = hits.setdefault(item, {'id': item, 'label': page.get('title', ''), 'description': ''})
                hit['article'] = hit.get('article') or 'titles' in params
    if not hits:
        raise LandmarkProblem(f'No Wikidata entity found for {name}.')
    entities = told(_wiki({'action': 'wbgetentities', 'ids': '|'.join(hits), 'languages': 'en',
                           'props': 'labels|descriptions|aliases|claims|sitelinks'})).get('entities', {})
    return list(hits.values()), entities, answered


FORBIDDEN = re.compile(r'\b(painting|film|song|book|album|photograph|person|surname|disambiguation)\b', re.I)
EVENT = re.compile(r'\b(battle|siege|attack|protests?|riots?|election|earthquake|fire|bombing|shooting|collapse|crash|massacre)\b', re.I)
STRUCTURE = re.compile(r'\b(cathedral|church|abbey|building|structure|mosque|palace|tower|temple|monument|memorial|mausoleum|castle|bridge|landmark|basilica|shrine|fortress|opera house|skyscraper|tomb|arch|gate|amphitheat(?:re|er)|theat(?:re|er)|stadium|museum|statue|chapel|minster|lighthouse|pyramid|venue|hall|library|monastery|priory|synagogue|pagoda|observatory|obelisk|aqueduct|villa|mansion|citadel|fort|fortification|house|ch[a\u00e2]teau|hotel|fountain|dam|windmill|capitol|prison|penitentiary|residence|ruins?|archaeological)\b', re.I)
PLACE = re.compile(r'\b(district|(?:designated|populated|inhabited) place|airport|state|kingdom|city|town|village|hamlet|municipality|commune|suburb|neighbou?rhood|ward|parish|borough|county|region|province|country|islands?|river|lake|street|road|square|station|stop|school|university|company|settlement|locality|community|area|territory|constituency|capital|mountain|hill|valley|park)\b', re.I)
# The words before the first preposition say what a thing is: a "human settlement in Tower Hamlets" is no tower.
KIND = re.compile(r'\b(?:in|of|on|at|near|by|from|within|between|for|to|with|known|serving|named|after|during|commemorating)\b|[,;(]', re.I)


def _lived_in(entity):
    """A population counted since 1900. Ancient cities carry estimates dated to their own time."""
    for claim in entity.get('claims', {}).get('P1082', []):
        amount = claim.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('amount', 0)
        when = [q.get('datavalue', {}).get('value', {}).get('time', '') for q in claim.get('qualifiers', {}).get('P585', [])]
        if claim.get('rank') != 'deprecated' and float(amount) and (not when or any(re.match(r'\+(19|2\d)\d\d-', w) for w in when)):
            return not entity['claims'].get('P576')
    return False


def _what(hit, entity):
    """What a hit is, from the first words of its description."""
    description = hit.get('description') or entity.get('descriptions', {}).get('en', {}).get('value', '')
    return KIND.split(re.sub(r'^\s*\([^)]*\)', '', description), maxsplit=1)[0].strip(), description


def _names(hit, entity):
    return [_words(text) for text in (hit.get('label', ''), hit.get('match', {}).get('text', ''),
                                      entity.get('labels', {}).get('en', {}).get('value', ''),
                                      *(a['value'] for a in entity.get('aliases', {}).get('en', [])))]


def _made(what, entity):
    """True for something built, False for a place people live in or go through, None when nothing says."""
    # A "siege castle" or a "fire station" ends in its kind, as a "parish church" does.
    ends = any(m.end() == len(what) for m in STRUCTURE.finditer(what))
    # An archaeological site, whatever it once was, unless people still live there.
    if 'Q839954' in _item_ids(entity, 'P31') and not _lived_in(entity):
        return True
    designed = any(_value(entity, claim) for claim in ('P149', 'P84', 'P1101'))
    places = {word.group().casefold() for word in PLACE.finditer(what)}
    # A "cathedral city" is a city and an "island off the coast" an island; a "parish church" ends in its kind.
    # A station or a school is a building when it has an architect; a town of one style is still a town.
    if places and not ends and not (designed and places <= {'station', 'school', 'airport'}):
        return False
    return True if designed or STRUCTURE.search(what) else None


def _choose(name, hits, entities):
    """The hit a person most likely means: its name, what kind of thing it is, and how widely it is written about."""
    wanted, best = _words(name), None
    for hit in hits:
        entity = entities.get(hit['id'], {})
        what, description = _what(hit, entity)
        if not _value(entity, 'P625') or FORBIDDEN.search(description):
            continue
        names = _names(hit, entity)
        named = wanted in names
        # A page Wikipedia only thinks related is no answer. Wikidata's own hits match the start of a name.
        near = hit.get('article') or any(set(wanted) <= set(n) for n in names)
        # "Example Tower Paris" is the Example Tower whose description says Paris.
        told = set(_words(description))
        near = near or any(n and set(n) < set(wanted) and set(wanted) - set(n) <= told for n in names)
        ends = any(m.end() == len(what) for m in STRUCTURE.finditer(what))
        if (EVENT.search(what) and not ends and not what.casefold().endswith('station')) \
                or not (named or near or 'match' in hit):
            continue
        made = _made(what, entity)
        score = 1 + len(entity.get('sitelinks', {}))
        score *= 8 if named else 1 if near else .05
        score *= 2 if hit.get('article') else 1
        score *= 4 if made else .02 if made is False else 1 if what else .5
        if best is None or score > best[0]:
            best = score, {**hit, 'description': description}, entity
    if best is None:
        raise LandmarkProblem(f'No building with coordinates found for {name}.')
    return best[1:]


FAMOUS = 40  # the wikis that write about a place anyone means by its name, whatever it is
KNOWN = 5  # the wikis that write about a structure someone asks for by its bare name
NATURAL = re.compile(r'\bnatural (?!history)|\bgeological (?:feature|formation|structure|site)|\brock formation'
                     r'|\bnational monument|\b(?:ship|submarine|aircraft)$', re.I)
SCULPTURE = re.compile(r'\b(?:statue|sculpture|bust)$', re.I)


def is_structure(name: str) -> bool:
    """True when a shipped pack or Wikidata knows this exact name best as a building, a monument, a ruin that stands or a famous place."""
    cache = Path.home() / '.cache' / 'smoothstone' / 'structure' / (
        hashlib.sha256(f'2 {" ".join(_words(name))}'.encode()).hexdigest() + '.json')
    try:
        if load_pack(name):
            return True
        try:
            kept = json.loads(cache.read_text())  # null: the lookup failed, and is not repeated for ten minutes
            if time.time() - cache.stat().st_mtime < (600 if kept is None else 7 * 86400):
                return kept is True
        except (OSError, ValueError):
            pass
        try:
            hits, entities, answered = _matches(name)
            known = _known_structure(name, hits, entities) if answered else None  # the ranking needs Wikipedia too
        except LandmarkProblem:  # nothing has this name
            known = False
        except (OSError, ValueError, http.client.HTTPException):  # offline or busy
            known = None
        try:
            _write_atomic(cache, json.dumps(known))
        except OSError:
            pass
        return known is True
    except Exception:  # nobody can say it is one
        return False


def _is_sculpture(refs):
    what, _ = _what({}, refs.get('wikidata_raw') or {})
    return bool(SCULPTURE.search(what))


def _known_structure(name, hits, entities):
    try:
        hit, entity = _choose(name, hits, entities)
    except LandmarkProblem:
        return False
    what, _ = _what(hit, entity)
    wikis = len(entity.get('sitelinks', {}))
    if _words(name) not in _names(hit, entity):
        return False
    # Another thing of this name, a god or a film, may be the one people mean: it has no place on a map.
    best = max(len(entities.get(h['id'], {}).get('sitelinks', {})) for h in hits
               if h['id'] == hit['id'] or _words(name) == _words(
                   entities.get(h['id'], {}).get('labels', {}).get('en', {}).get('value', ''))
               and 'Q4167410' not in _item_ids(entities.get(h['id'], {}), 'P31'))  # a disambiguation page
    listed = any(c.get('rank') != 'deprecated' and 'P582' not in c.get('qualifiers', {})
                 for c in entity.get('claims', {}).get('P1435', []))
    gone = _value(entity, 'P576') and not listed  # an ended place still listed as heritage is a ruin that stands
    # Mount Rushmore is a mountain to Wikidata. One word can be a part ("Hook"), and a city of two is no part either.
    famous = wikis >= FAMOUS and len(_words(name)) > 1
    built = not NATURAL.search(what) and _made(what, entity) is True
    return wikis >= max(KNOWN, best) and not gone and (built or famous)


def resolve(name: str, job_root: Path) -> dict:
    """Return sourced facts for the closest structure found by name."""
    normalized = ' '.join(name.casefold().split())
    key = hashlib.sha256(f'4 {normalized}'.encode()).hexdigest()  # 4: the ranking that chose the answer
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
        hits, entities, answered = _matches(name)
        hit, entity = _choose(name, hits, entities)
        entity_id = hit['id']
        source = f'https://www.wikidata.org/wiki/{entity_id}'
        coordinate = _value(entity, 'P625')
        label = entity.get('labels', {}).get('en', {}).get('value') or hit.get('label', name)
        ref = {'id': entity_id, 'label': label, 'matched_name': normalized,
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
        if answered:
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


WHOLE = ('pyramidal', 'cone', 'dome', 'onion')  # a roof that can be the shape of the whole; a gable is not a cathedral
UPRIGHT = ('obelisk', 'tower', 'chimney', 'lighthouse', 'column', 'water_tower')


def _own(el, refs):
    """Wikidata names this map object, or it names the Wikidata item."""
    wanted = refs.get('osm_way' if el['type'] == 'way' else 'osm_relation')
    return str(el['id']) == str(wanted) or bool(refs.get('id')) and el.get('tags', {}).get('wikidata') == refs['id']


def _is_site(tags):
    """A castle, fort or bridge mapped as an area and not as one building."""
    return not ('building' in tags or 'building:part' in tags) and (
        tags.get('historic') in ('castle', 'fort', 'citadel') or tags.get('man_made') == 'bridge')


def _named(tags, refs):
    """A building that carries the landmark's whole name is the landmark."""
    words = set(re.findall(r'\w+', (refs.get('label') or '').casefold()))
    return bool(words) and words <= set(re.findall(r'\w+', tags.get('name', '').casefold()))


def _share(parts, boundary):
    """The share of an outline's ground that has a part over it."""
    import manifold3d as m3
    from .landmark import _section
    ground = _section(boundary)
    if ground.is_empty() or not parts:
        return 0
    over = m3.CrossSection.batch_boolean([_section(p['footprint']) for p in parts], m3.OpType.Add)
    return (over ^ ground).area() / ground.area()


def _body(selected, parts, boundary):
    """The outline, where its own height is the walls around a mapped dome or tower."""
    from .landmark import length
    walls = length(selected['tags'].get('height'))
    tops = [length(p['tags'].get('height')) or 0 for p in parts]
    # Parts well under the top of the walls are the building itself, though they hang in the air as the Atomium's do.
    low = [p for p in parts if (length(p['tags'].get('min_height')) or 0) < .75 * walls
           and (p['tags'].get('min_height') or not length(p['tags'].get('building:min_level')))] if walls else []
    return [selected] if walls and max(tops, default=0) > walls and _share(low, boundary) < .5 else []


def _site(site, candidates, pieces, data):
    """Every part on a site, and each building there that is not mapped in parts."""
    def on(item, boundary):
        point = _centroid(item['footprint'][0])
        return _inside(point, boundary[0]) and not any(_inside(point, h) for h in boundary[1:])

    boundary = site['footprint']
    buildings = [c for c in candidates if on(c, boundary)]
    areas = [boundary, *(b['footprint'] for b in buildings)]
    parts = [p for p in pieces if any(on(p, a) for a in areas)]
    mapped = list(parts)
    for b in buildings:
        own = [p for p in mapped if on(p, b['footprint'])]
        parts += _body(b, own, b['footprint']) if own else [b]
    return {'outline': [], 'site': boundary, 'parts': parts, 'source': site['source'], 'tags': site['tags'],
            'linked_towers': [], 'response_url': data.get('_smoothstone_response_url', OVERPASS)}


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
    if _is_sculpture(refs):  # and never the pedestal or the building it stands on
        raise LandmarkProblem('A statue is a sculpture, and building maps do not have its shape.')
    candidates, pieces, sites = [], [], []
    for el in data.get('elements', []):
        if el.get('type') not in ('way', 'relation'):
            continue
        tags = el.get('tags', {})
        own = _own(el, refs)
        if own and (tags.get('artwork_type') in ('statue', 'sculpture', 'bust') or tags.get('monument') == 'statue'):
            raise LandmarkProblem('A statue is a sculpture, and building maps do not have its shape.')
        site = own and _is_site(tags)
        if not (site or 'building' in tags or 'building:part' in tags):
            continue
        # A room, or anything under the ground, has no outside to model.
        if tags.get('indoor', 'no') != 'no' or 'room' in tags or tags.get('location') == 'underground':
            continue
        for poly in polygons(el):
            item = {'id': el['id'], 'type': el['type'], 'footprint': poly, 'tags': tags,
                    'source': f"https://www.openstreetmap.org/{el['type']}/{el['id']}"}
            is_part = tags.get('building:part', 'no') != 'no'
            if site:
                sites.append(item)
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
        # A castle is all of its buildings, not the tower that happens to stand at its coordinates.
        if sites and not (selected and _named(selected['tags'], refs)):
            return _site(max(sites, key=lambda c: _area(c['footprint'][0])), candidates, pieces, data)
    if selected is None:
        raise LandmarkProblem('OpenStreetMap has no building outline containing the coordinates.')
    boundary = selected['footprint']
    parts = [p for p in pieces if _inside(_centroid(p['footprint'][0]), boundary[0]) and
             not any(_inside(_centroid(p['footprint'][0]), h) for h in boundary[1:])]
    parts += _body(selected, parts, boundary)
    form = selected['tags']
    if not parts and form.get('height') and (
            form.get('roof:shape') in WHOLE or form.get('man_made') in UPRIGHT or form.get('building') == 'tower'):
        parts = [selected]  # an obelisk or a tower is its own one part
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


def _map_as_overpass(data, refs):
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
        if not any(k in e.get('tags', {}) for k in ('building', 'building:part')) \
                and not _own(e, refs):
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


def fetch(refs: dict, job_root: Path, reach: float = 0) -> dict:
    """Fetch and cache OSM responses in the job and shared cache, again when a site reaches past the search."""
    lat, lon = refs['latitude'], refs['longitude']
    # The radius includes half the known span and is capped to bound public requests.
    span = max(refs.get('length') or 0, refs.get('width') or 0)
    radius, small = min(1000, max(220, math.ceil(span * 0.6), math.ceil(reach))), False
    nearby = ''.join(f'{kind}["{tag}"](around:{radius},{lat},{lon});'
                     for tag in ('building', 'building:part') for kind in ('way', 'relation'))
    explicit = ''
    if re.fullmatch(r'Q\d+', refs.get('id') or ''):
        # `around` measures to the line of an area, and a castle's line can be far from its middle.
        explicit += ''.join(f'{kind}["wikidata"="{refs["id"]}"](around:1000,{lat},{lon});' for kind in ('way', 'relation'))
    for kind, key_name in (('way', 'osm_way'), ('relation', 'osm_relation')):
        identifier = str(refs.get(key_name) or '')
        if identifier.isdecimal():
            explicit += f'{kind}({identifier});'
    query = f'[out:json][timeout:40];({nearby}{explicit});out geom;'
    key = hashlib.sha256(('2 ' + query).encode()).hexdigest()  # 2: the map answer keeps sites
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
                while True:
                    dx = radius / (111320 * math.cos(math.radians(lat)))
                    dy = radius / 111320
                    bbox = ','.join(str(v) for v in (lon-dx, lat-dy, lon+dx, lat+dy))
                    url = 'https://api.openstreetmap.org/api/0.6/map.json?' + urllib.parse.urlencode({'bbox': bbox})
                    try:
                        raw = _request(url)
                        break
                    except urllib.error.HTTPError as exc:  # it answers 400 for an area with over 50,000 nodes
                        if exc.code != 400 or radius <= 220:
                            raise
                        radius = max(220, radius // 2)
                        small = True
                raw_text = json.dumps(raw, ensure_ascii=False)
                _write_atomic(ref_dir / 'osm-map.json', raw_text)
                _write_atomic(raw_cache, raw_text)
                data = _map_as_overpass(raw, refs)
                data['_smoothstone_response_url'] = url
                data['_smoothstone_query'] = query
            if not small:
                _write_atomic(cache, json.dumps(data, ensure_ascii=False))
        _write_atomic(job_cache, json.dumps(data, ensure_ascii=False))
        parsed = parse_osm(data, refs)
        far = max((math.hypot(*point) for point in parsed.get('site', [[]])[0]), default=0)
        around = max([far, *(math.hypot(*point) for ring in parsed['outline'] for point in ring)])
        if small and around > radius:
            raise LandmarkProblem('OpenStreetMap is too busy to answer for all of this landmark. Try again in a few minutes.')
        if far > 1000:
            raise LandmarkProblem('The landmark reaches more than 1 km from its coordinates.')
        if far > radius:
            return fetch(refs, job_root, far)
        if parsed.get('site') and parsed['tags'].get('man_made') == 'bridge' and _share(parsed['parts'], parsed['site']) < .5:
            raise LandmarkProblem('The map has the place of this bridge, and not the shape of its deck.')
        return parsed
    except LandmarkProblem:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LandmarkProblem(f'OpenStreetMap lookup failed: {exc}') from exc
