import re
import itertools
from psycopg2.extensions import QueryCanceledError
from mapit.postcodes.models import Postcode
from mapit.postcodes.utils import is_valid_postcode, is_valid_partial_postcode
from mapit.areas.models import Area, Generation
from mapit.shortcuts import output_json, get_object_or_404, output_error, set_timeout
from mapit.ratelimitcache import ratelimit
from django.template import loader
from django.http import HttpResponse
from django.shortcuts import render_to_response, redirect

# Stupid fixed IDs from old MaPit
WMP_AREA_ID = 900000
EUP_AREA_ID = 900001
LAE_AREA_ID = 900002
SPA_AREA_ID = 900003
WAS_AREA_ID = 900004
NIA_AREA_ID = 900005
LAS_AREA_ID = 900006
HOL_AREA_ID = 900007
HOC_AREA_ID = 900008
enclosing_areas = {
    'LAC': [ LAE_AREA_ID, LAS_AREA_ID ],
    'SPC': [ SPA_AREA_ID ],
    'WAC': [ WAS_AREA_ID ],
    'NIE': [ NIA_AREA_ID ],
    'WMC': [ WMP_AREA_ID ],
    'EUR': [ EUP_AREA_ID ],
}

def bad_request(format, message):
    return output_error(format, message, 400)

def check_postcode(format, postcode):
    postcode = re.sub('[^A-Z0-9]', '', postcode.upper())
    if not is_valid_postcode(postcode):
        return bad_request(format, "Postcode '%s' is not valid." % postcode)
    postcode = get_object_or_404(Postcode, format=format, postcode=postcode)
    return postcode

@ratelimit(minutes=3, requests=100)
def postcode(request, postcode, legacy=False, format='json'):
    postcode = check_postcode(format, postcode)
    if isinstance(postcode, HttpResponse): return postcode
    try:
        generation = int(request.REQUEST['generation'])
    except:
        generation = Generation.objects.current()
    areas = Area.objects.by_postcode(postcode, generation)

    # Shortcuts
    shortcuts = {}
    for area in areas:
        if area.type in ('COP','LBW','LGE','MTW','UTE','UTW'):
            shortcuts['ward'] = area.id
            shortcuts['council'] = area.parent_area_id
        elif area.type == 'CED':
            shortcuts.setdefault('ward', {})['county'] = area.id
            shortcuts.setdefault('council', {})['county'] = area.parent_area_id
        elif area.type == 'DIW':
            shortcuts.setdefault('ward', {})['district'] = area.id
            shortcuts.setdefault('council', {})['district'] = area.parent_area_id
        elif area.type in ('WMC'): # XXX Also maybe 'EUR', 'NIE', 'SPC', 'SPE', 'WAC', 'WAE', 'OLF', 'OLG', 'OMF', 'OMG'):
            shortcuts[area.type] = area.id

    # Add manual enclosing areas. 
    extra = []
    for area in areas:
        if area.type in enclosing_areas.keys():
            extra.extend(enclosing_areas[area.type])
    areas = itertools.chain(areas, Area.objects.filter(id__in=extra))
 
    if legacy:
        areas = dict( (area.type, area.id) for area in areas )
        return output_json(areas)

    if format == 'html':
        return render_to_response('postcode.html', {
            'postcode': postcode.as_dict(),
            'areas': areas,
            'json': '/postcode/',
        })

    out = postcode.as_dict()
    out['areas'] = dict( ( area.id, area.as_dict() ) for area in areas )
    if shortcuts: out['shortcuts'] = shortcuts
    return output_json(out)
    
@ratelimit(minutes=3, requests=100)
def partial_postcode(request, postcode, format='json'):
    postcode = re.sub('\s+', '', postcode.upper())
    if is_valid_postcode(postcode):
        postcode = re.sub('\d[A-Z]{2}$', '', postcode)
    if not is_valid_partial_postcode(postcode):
        return bad_request(format, "Partial postcode '%s' is not valid." % postcode)
    try:
        postcode = Postcode(
            postcode = postcode,
            location = Postcode.objects.filter(postcode__startswith=postcode).collect().centroid
        )
    except:
        return output_error(format, 'Postcode not found', 404)

    if format == 'html':
        return render_to_response('postcode.html', {
            'postcode': postcode.as_dict(),
            'json': '/postcode/partial/',
        })

    return output_json(postcode.as_dict())

@ratelimit(minutes=3, requests=100)
def example_postcode_for_area(request, area_id, legacy=False, format='json'):
    area = get_object_or_404(Area, format=format, id=area_id)
    if isinstance(area, HttpResponse): return area
    try:
        pc = Postcode.objects.filter(areas=area).order_by()[0]
    except:
        set_timeout(format)
        try:
            pc = Postcode.objects.filter_by_area(area).order_by()[0]
        except QueryCanceledError:
            return output_error(format, 'That query was taking too long to compute.', 500)
        except:
            pc = None
    if pc: pc = pc.get_postcode_display()
    if format == 'html':
        return render_to_response('example-postcode.html', { 'area': area, 'postcode': pc })
    return output_json(pc)

def form_submitted(request):
    pc = request.POST.get('pc', None)
    if not request.method == 'POST' or not pc:
        return redirect('/')
    return redirect('mapit.postcodes.views.postcode', postcode=pc, format='html')

# Legacy Views from old MaPit. Don't use in future.

@ratelimit(minutes=3, requests=100)
def get_location(request, postcode, partial):
    if partial:
        return partial_postcode(request, postcode)
    postcode = check_postcode('json', postcode)
    if isinstance(postcode, HttpResponse): return postcode
    return output_json(postcode.as_dict())

