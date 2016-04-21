import ast
import re

from copy import deepcopy
from itertools import chain
from slybot.plugins.scrapely_annotations.extraction import (
    RepeatedContainerExtractor
)
from .processors import (
    Item, Field, Text, Number, Price, Date, Url, Image, Regex, Identity
)


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
    name = re.sub('[\s\.-]', '_', name.strip()).strip('_')
    return name


def class_name(name):
    """Create class name from resource name."""
    # Remove leading 'www' and replace all '.' with '_'
    name = _clean(name)
    # Remove trailing '_com'
    name = re.sub('_com$', '', name)
    # Replace all whitespace and '-' with '_'
    name = re.sub('[\s-]', '_', name.title().strip()).strip('_')
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
    a = extractor.annotation
    selector = a.metadata.get('selector')
    if not selector:
        return []
    content = (('#content', c) for c in a.surrounds_attribute or [])
    attributes = chain(*([(k, v) for v in values]
                         for k, values in a.tag_attributes))
    fields = []
    for attribute, field in chain(content, attributes):
        fields.append(Field(field_name(field['field'], schema),
                            build_selector(selector, attribute),
                            build_processors(field, schema, extractors),
                            bool(field.get('required'))))
    return fields


def container_to_item(extractor, fields, schema, item):
    a = extractor.annotation
    selector = a.metadata.get('selector')
    if not selector:
        return None
    if isinstance(extractor, RepeatedContainerExtractor):
        return build_repeating_items(extractor, schema, item, selector,
                                     fields)
    return [Item(item(), get_field(extractor, schema), selector, fields)]


def build_repeating_items(extractor, schema, item, selector, fields):
    containers = {s.strip(): [] for s in selector.split(',')}
    prefix_lengths = set(map(len, containers))
    for field in fields:
        for selector in (s.strip() for s in field.selector.split(',')):
            for prefix_len in prefix_lengths:
                prefix = selector[:prefix_len]
                if prefix in containers:
                    new_field = deepcopy(field)
                    new_field.selector = selector
                    containers[prefix].append(new_field)
                    break
    name = get_field(extractor, schema)
    return sorted([Item(item(), name, sel, item_fields)
                   for sel, item_fields in containers.items()],
                  key=lambda x: x.selector)


def build_processors(field, schema, extractors):
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
