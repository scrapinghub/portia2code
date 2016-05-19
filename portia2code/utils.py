import ast
import re

from collections import defaultdict
from copy import deepcopy
from itertools import chain, groupby
from slybot.plugins.scrapely_annotations.extraction import (
    RepeatedContainerExtractor
)
from .processors import (
    Item, Field, Text, Number, Price, Date, Url, Image, Regex, Identity
)
_NTH_CHILD_RE = re.compile('(:nth-child\((\d+)\))')


def _validate_identifier(name):
    try:
        mod = ast.parse('%s = 1' % name)
    except SyntaxError:
        return False
    else:
        if (isinstance(mod, ast.Module) and len(mod.body) == 1 and
                isinstance(mod.body[0], ast.Assign) and
                len(mod.body[0].targets) == 1 and
                isinstance(mod.body[0].targets[0], ast.Name)):
            return True
    return False


def _clean(name):
    if name.startswith('www.') and len(name) > 4:
        name = name[4:]
    name = re.sub(r'[\s\.-]', '_', name.strip()).strip('_')
    return name


def class_name(name):
    """Create class name from resource name."""
    # Remove leading 'www' and replace all '.' with '_'
    name = _clean(name)
    # Remove trailing '_com'
    name = re.sub('_com$', '', name)
    # Replace all whitespace and '-' with '_'
    name = re.sub(r'[\s-]', '_', name.title().strip()).strip('_')
    # Conform to python 2 allowed variable name
    name = re.sub('^[^_a-zA-Z]', '', name)
    name = re.sub('[^_a-zA-Z0-9]', '', name)
    # Normalize underscores
    name = re.sub('_(_+)', '', name)
    return re.sub('(_[a-zA-Z])', lambda x: x.group()[-1].upper(), name)


def item_field_name(name):
    """Clean field names."""
    return _clean(name)


PROCESSOR_TYPES = {
    'text': Text(),
    'number': Number(),
    'price': Price(),
    'date': Date(),
    'url': Url(),
    'image': Image(),
    'geopoint': Identity(),
    'raw html': Identity(),
    'safe html': Identity()
}


def get_field(container, schema):
    parent_field = None
    if hasattr(container, 'parent_annotation'):
        parent_field = container.parent_annotation.metadata.get('field')
    field = container.annotation.metadata.get('field') or parent_field
    if field is not None and schema is not None:
        return field_name(field, schema)


def field_name(field, schema):
    try:
        return item_field_name(schema['fields'][field]['name'])
    except (KeyError, NameError):
        return field


def build_selector(selector, attribute):
    if attribute == '#content':
        return '%s *::text' % selector
    return '%s::attr(%s)' % (selector, attribute)


def extractor_to_field(extractor, schema, extractors):
    anno = extractor.annotation
    selector = anno.metadata.get('selector')
    if not selector:
        return []
    content = (('#content', c) for c in anno.surrounds_attribute or [])
    attributes = chain(*([(k, v) for v in values]
                         for k, values in anno.tag_attributes))
    fields = []
    for attribute, field in chain(content, attributes):
        fields.append(Field(field_name(field['field'], schema),
                            build_selector(selector, attribute),
                            build_processors(field, extractors),
                            bool(field.get('required'))))
    return fields


def shrink_selector(selectors, parent_selector):
    new_selectors = []
    parent_selector_len = len(parent_selector)
    for selector in selectors:
        if selector.startswith(parent_selector):
            sel = selector[parent_selector_len:].strip()
            if sel.startswith('>'):
                sel = sel[1:].strip()
            new_selectors.append(sel)
    return new_selectors


def container_to_item(extractor, fields, schema, item):
    anno = extractor.annotation
    selector = anno.metadata.get('selector')
    if not selector:
        return None
    if isinstance(extractor, RepeatedContainerExtractor):
        return build_repeating_items(extractor, schema, item, selector,
                                     fields)
    new_fields = []
    for field in fields:
        sel = shrink_selector([field.selector], selector)
        if sel:
            field.selector = sel[0]
        new_fields.append(field)
    return [Item(item(), get_field(extractor, schema), selector, new_fields)]


def build_repeating_items(extractor, schema, item, selector, fields):
    containers = [s.strip() for s in selector.split(',')]
    sel = sorted(set(generalise(containers)))
    item_fields = []
    for field in fields:
        selectors = [s.strip() for s in field.selector.split(',')]
        generalised = sorted(set(generalise(selectors)))
        sels = set(chain(*(shrink_selector(generalised, s) for s in sel)))
        if len(sels) > 1:
            sels = [s for s in sels if '::attr' in s or '::text' in s]
        elif sels and '::attr' not in sels[0] and '::text' not in sel[0]:
            sels = [build_selector(sels[0], '#content')]
        field.selector = ', '.join(sorted(sels))
        item_fields.append(field)
    name = get_field(extractor, schema)
    return [Item(item(), name, ', '.join(sel), item_fields)]


def generalise(selectors):
    """
    Find the most likely nth-child selector that's changing and generalise it.

    >>> base = [
    ...     u'.a > .sr_item:nth-child(%s) > .sr_item_content > p:nth-child(2)',
    ...     u'.rr_item:nth-child(%s) > .sr_item_content',
    ...     u'.sr_item:nth-child(%s) > .sr_item_content'
    ... ]
    >>> selectors = [s % i for s in base for i in range(0, 30, 5)]
    >>> generalised = sorted(set(generalise(selectors).values()))
    >>> generalised[0]
    u'.a > .sr_item > .sr_item_content > p:nth-child(2)'
    >>> generalised[1]
    u'.rr_item > .sr_item_content'
    >>> generalised[2]
    u'.sr_item > .sr_item_content'
    """
    def starts(results):
        return [s[-1][:s[0]] for s in results]

    def start_positions(results):
        return [s[0] for s in results]

    parsed = [[(r.start(), r.groups()[-1], r.string)
               for r in _NTH_CHILD_RE.finditer(s)]
              for s in selectors]
    grouped = groupby(sorted(parsed, key=starts), starts)
    ogrouped = groupby(sorted(parsed, key=start_positions), start_positions)
    groups = [list(v) for _, v in grouped] + [list(v) for _, v in ogrouped]
    selectors_map = {}
    for group in groups:
        if len(group) == 1:
            continue
        similar = defaultdict(set)
        selectors = set()
        for section in group:
            for start, value, selector in section:
                selectors.add(selector)
                similar[start].add(value)
        try:
            changing_element = max((k for k, v in similar.items()
                                   if len(v) > 1))
        except ValueError:
            selectors_map.update({k: k for k in selectors})
            continue
        for selector in selectors:
            generalised = re.sub(
                selector[:changing_element] + ':nth-child\(\d+\)',
                selector[:changing_element],
                selector)
            selectors_map[generalised] = selector
    return selectors_map


def build_processors(field, extractors):
    processors = []
    # TODO: initialize with initial field type
    for extractor_id in field.get('extractors', []):
        if extractor_id not in extractors:
            continue
        extractor = extractors[extractor_id]
        if 'regular_expression' in extractor:
            processors.append(Regex(extractor['regular_expression']))
        elif extractor.get('type_extractor') in PROCESSOR_TYPES:
            processors.append(PROCESSOR_TYPES[extractor['type_extractor']])
    return processors
