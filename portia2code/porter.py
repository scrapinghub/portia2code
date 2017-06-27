"""Convert a Portia project into a python scrapy project."""
import imp
import logging
import os
import string
import zipfile

from datetime import datetime
from inspect import getsource
from itertools import chain
from os.path import join

import portia2code.spiders
import scrapy

from six import BytesIO, PY2

from autopep8 import fix_code
from scrapy.settings import Settings
from scrapy.utils.template import string_camelcase
from slybot.utils import SpiderLoader
from slybot.spider import IblSpider
from slybot.starturls import fragment_generator, feed_generator
from slybot.utils import encode
from w3lib.util import to_unicode, to_bytes

from .samples import ItemBuilder
from .templates import (
    ITEM_CLASS, ITEM_FIELD, ITEMS_IMPORTS, RULES, SPIDER_CLASS, SPIDER_FILE,
    SETUP
)
from .utils import (PROCESSOR_TYPES, _validate_identifier, _clean, class_name,
                    item_field_name, merge_sources)
log = logging.getLogger(__name__)
TEMPLATES_PATH = (scrapy.__path__[0], 'templates', 'project')
OPTIONS = {
    'aggressive': 2
}


class UpdatingZipFile(zipfile.ZipFile):
    """ZipFile that buffers writes so that each file is only written once."""

    def __init__(self, file, mode="r", compression=zipfile.ZIP_STORED,
                 allowZip64=False):
        super(UpdatingZipFile, self).__init__(file, mode, compression,
                                              allowZip64)
        self._files = {}

    _writestr = zipfile.ZipFile.writestr

    def writestr(self, zinfo, bytes, compress_type=None):
        """Add provided file to buffer."""
        self._files[zinfo.orig_filename] = (zinfo, bytes, compress_type)

    def finalize(self):
        """Write all buffered files to archive."""
        for zinfo, contents, compress_type in self._files.values():
            self._writestr(zinfo, to_bytes(contents), compress_type)
        self._files = {}


def load_project_data(storage):
    """Load project data using provided open_func and project directory."""
    # Load items and extractors from project

    schemas = storage.open('items.json')
    extractors = storage.open('extractors.json')

    # Load spiders and templates
    spider_loader = SpiderLoader(storage)
    spiders = {}
    for spider_name in spider_loader.spider_names:
        spider = spider_loader[spider_name]
        crawler = IblSpider(spider_name, spider, schemas, extractors,
                            Settings())
        spiders[spider_name] = (crawler, spider)
    return schemas, extractors, spiders


def write_to_archive(archive, project_name, files):
    """Write files to the project_name folder of the archive."""
    tstamp = datetime.now().timetuple()[:6]
    for filepath, contents in files:
        if filepath is None or contents in (None, 'null'):
            log.debug('Skipping file "%s" with contents "%r"', filepath,
                      contents)
            continue
        filepath = join(project_name, filepath)
        fileinfo = zipfile.ZipInfo(filepath, tstamp)
        fileinfo.external_attr = 0o666 << 16
        archive.writestr(fileinfo, contents, zipfile.ZIP_DEFLATED)


def find_files(project_name):
    """Find files needed for scrapy project templates."""
    sep = os.sep
    read_files = {}
    for base, _, files in os.walk(join(*TEMPLATES_PATH)):
        basepath = base[len(TEMPLATES_PATH):]
        splitpath = basepath.partition('%smodule' % sep)[2:]
        basepath = join(project_name, *[p.lstrip(sep) for p in splitpath])
        for filename in files:
            if filename.endswith(('.pyc', '.pyo')):
                continue
            path = join(base, filename)
            with open(path) as f:
                out_path = join(basepath, filename)
                read_files[out_path] = f.read()
    return read_files


def start_scrapy_project(project_name):
    """Bootstrap a portia project with default scrapy files."""
    if PY2:
        project_name = encode(project_name)
    files = find_files(project_name)
    out_files = {}
    for path, contents in files.items():
        contents = string.Template(contents).substitute(
            project_name=project_name,
            ProjectName=string_camelcase(project_name)
        )
        if path.endswith('.tmpl'):
            path = path[:-len('.tmpl')]
        if path.endswith('scrapy.cfg'):
            path = 'scrapy.cfg'
        out_files[path] = contents
    out_files['setup.py'] = SETUP(project_name)

    return out_files


def create_schemas_classes(items):
    """Create schemas and fields from definitions."""
    item_classes, item_names = [], {}
    for item_id, item in items.items():
        item_name = class_name(item.get('name', item_id))
        if not _validate_identifier(item_name):
            log.warning(
                'Skipping item with id "%s", name "%s" is not a valid '
                'identifier' % (item_id, item_name))
            continue
        item_fields = ''.join(create_fields(item['fields']))
        if not item_fields:
            item_fields = 'pass\n'.rjust(9)
        item_classes.append(
            ITEM_CLASS(name=item_name, fields=item_fields))
        item_names[item_id] = item_name
    return item_classes, item_names


def create_fields(item_fields):
    """"Create fields from definitions."""
    fields = []
    for field_id, field in item_fields.items():
        name = item_field_name(field.get('name', field_id))
        if name and name[0].isdigit():
            name = '_{}'.format(name)
        if not _validate_identifier(name):
            log.warning(
                'Skipping field with id "%s", name "%s" is not a valid '
                'identifier', field_id, name)
            continue
        field_type = field.get('type', 'text')
        input_processor = repr(PROCESSOR_TYPES.get(field_type, 'lambda x: x'))
        output_processor = 'Join()'
        fields.append(ITEM_FIELD(name=name, input=input_processor,
                                 output=output_processor))
    return fields


def create_library_files():
    """Write utilities needed to run spiders."""
    return [
        ('utils/__init__.py', ''),
        ('utils/parser.py', getsource(portia2code.parser)),
        ('utils/processors.py', getsource(portia2code.processors)),
        ('utils/spiders.py', getsource(portia2code.spiders)),
        ('utils/starturls.py', merge_sources(fragment_generator,
                                             feed_generator))
    ]


def create_schemas(items):
    """Create and write schemas from definitions."""
    schema_classes, schema_names = create_schemas_classes(items)
    items_py = '\n'.join(chain([ITEMS_IMPORTS], schema_classes)).strip()
    items_py = fix_code(to_unicode(items_py), OPTIONS)
    return items_py, schema_names


def create_spider(name, spider, spec, schemas, extractors, items,
                  selector='css'):
    """Convert a slybot spider into scrapy code."""
    cls_name = class_name(name)
    start_urls = []
    for url in spider._start_urls.normalize():
        type_ = url.get('type')
        if type_ == 'url':
            start_urls.append('%r' % url['url'])
        else:
            start_urls.append('%r' % url)
    start_urls = '[%s]' % ',\n'.join(start_urls)

    allowed = spider.allowed_domains
    crawling_options = spec.get('links_to_follow')
    allow, deny = '', ''
    if crawling_options == 'patterns':
        if spec.get('follow_patterns'):
            allow = ', '.join((repr(s) for s in spec['follow_patterns']))
        if spec.get('exclude_patterns'):
            deny = ','.join((repr(s) for s in spec['exclude_patterns']))
    elif crawling_options == 'none':
        deny = "'.*'"
    else:
        allow = "'.*'"
    # TODO: Add support for auto
    rules = RULES(allow=allow, deny=deny)
    item_imports = ItemBuilder(
        schemas, extractors, items, items['_PortiaItem'], selector).extract(
        spider.plugins[0].extractors
    )
    return SPIDER_CLASS(
        class_name=cls_name, name=name, allowed_domains=repr(allowed),
        start_urls=start_urls, rules=rules, items=item_imports
    )


def create_spiders(spiders, schemas, extractors, items, selector='css'):
    """Create all spiders from slybot spiders."""
    item_classes = ''
    if items:
        item_classes = '\nfrom ..items import {}'.format(
            ', '.join((v().__class__.__name__ for v in items.values()))
        )
    spider_data = []
    for name, (spider, spec) in spiders.items():
        log.info('Creating spider "%s"' % spider.name)
        spider = create_spider(name, spider, spec, schemas, extractors, items,
                               selector)
        cleaned_name = _clean(name)
        filename = 'spiders/{}.py'.format(cleaned_name)
        data = '\n'.join((SPIDER_FILE(item_classes=item_classes),
                          spider.strip()))
        code = fix_code(to_unicode(data), OPTIONS)
        spider_data.append((filename, code))
    return spider_data


def port_project(dir_name, schemas, spiders, extractors, selector='css'):
    """Create project layout, default files and project specific code."""
    dir_name = class_name(dir_name)
    zbuff = BytesIO()
    archive = UpdatingZipFile(zbuff, "w", zipfile.ZIP_DEFLATED)
    write_to_archive(archive, '', start_scrapy_project(dir_name).items())
    items_py, schema_names = create_schemas(schemas)
    write_to_archive(archive, dir_name, [('items.py', items_py)])
    write_to_archive(archive, dir_name, create_library_files())

    # XXX: Hack to load items.py file
    items_no_relative = items_py.replace(
        'from .utils.processors import', 'from portia2code.processors import'
    )
    mod = imp.new_module('%s.%s' % (dir_name, 'items'))
    exec(items_no_relative, mod.__dict__)
    items = vars(mod)

    # Load schema objects from module
    schema_names = {}
    for _id, name in schema_names.items():
        schema_names[_id] = items['%sItem' % name]
    schema_names['_PortiaItem'] = items['PortiaItem']

    spider_data = create_spiders(spiders, schemas, extractors, schema_names,
                                 selector)
    write_to_archive(archive, dir_name, spider_data)
    archive.finalize()
    archive.close()
    zbuff.seek(0)
    return zbuff
