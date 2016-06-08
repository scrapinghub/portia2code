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

from six import StringIO

from autoflake import fix_code
from autopep8 import fix_lines
from scrapy.settings import Settings
from scrapy.utils.template import string_camelcase
from slybot.utils import _build_sample
from slybot.spider import IblSpider
from slybot.starturls import generator

from .samples import ItemBuilder
from .templates import (
    ITEM_CLASS, ITEM_FIELD, ITEMS_IMPORTS, RULES, SPIDER_CLASS, SPIDER_FILE
)
from .utils import (PROCESSOR_TYPES, _validate_identifier, _clean, class_name,
                    item_field_name)
log = logging.getLogger(__name__)
TEMPLATES_PATH = (scrapy.__path__[0], 'templates', 'project')


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
            self._writestr(zinfo, contents, compress_type)
        self._files = {}


class Options(object):
    """Settings for autopep8."""

    version = '1.0.0'
    verbose = None
    diff = False
    in_place = False
    global_config = False
    ignore_local_config = False
    recursive = False
    jobs = 1
    pep8_passes = -1
    aggressive = 3
    experimental = False
    exclude = ''
    list_fixes = False
    ignore = ''
    select = ''
    max_line_length = 79
    line_range = None
    indent_size = 4
    files = []


def load_project_data(open_func, spiders_list_func, project_dir):
    """Load project data using provided open_func and project directory."""
    # Load items and extractors from project
    schemas = open_func(project_dir, 'items')
    extractors = open_func(project_dir, 'extractors')

    # Load spiders and templates
    spiders = {}
    spiders_list = spiders_list_func(project_dir)
    for spider_name in spiders_list:
        spider = open_func(project_dir, 'spiders', spider_name)
        if not spider:
            log.warning(
                'Skipping "%s" spider as there is no data', spider_name
            )
            continue
        if 'template_names' in spider:
            samples = spider.get('template_names', [])
            spider['templates'] = []
            for sample_name in samples:
                sample = open_func(project_dir, 'spiders', spider_name,
                                   sample_name)
                _build_sample(sample)
                spider['templates'].append(sample)
        else:
            for sample in spider.get('templates', []):
                _build_sample(sample)
        spiders[spider_name] = (IblSpider(spider_name, spider, schemas,
                                          extractors, Settings()),
                                spider)
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
    files = find_files(project_name)
    out_files = {}
    for path, contents in files.items():
        contents = string.Template(contents).substitute(
            project_name=project_name,
            ProjectName=string_camelcase(project_name)
        )
        if path.endswith('.tmpl'):
            path = path[:-len('.tmpl')]
        out_files[path] = contents
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
        ('utils/starturls.py', getsource(generator))
    ]


def create_schemas(items):
    """Create and write schemas from definitions."""
    schema_classes, schema_names = create_schemas_classes(items)
    items_py = '\n'.join(chain([ITEMS_IMPORTS], schema_classes)).strip()
    items_py = fix_lines(fix_code(items_py.decode('utf-8')).splitlines(),
                         Options)
    return items_py, schema_names


def create_spider(name, spider, spec, schemas, extractors, items):
    """Convert a slybot spider into scrapy code."""
    cls_name = class_name(name)
    urls_type = getattr(spider, 'start_urls_type', 'start_urls')
    start_urls = []
    if urls_type == 'start_urls':
        urls = getattr(spider, 'start_urls', []) or spec.get('start_urls', [])
        if urls:
            start_urls = repr(urls)
    elif urls_type == 'generated_urls':
        urls_spec = (getattr(spider, 'generated_urls', []) or
                     spec.get('generated_urls', []))
        if urls_spec:
            start_urls = 'UrlGenerator()(%r)' % urls_spec

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
        schemas, extractors, items, items['_PortiaItem']).extract(
        spider.plugins[0].extractors
    )
    return SPIDER_CLASS(
        class_name=cls_name, name=name, allowed_domains=repr(allowed),
        start_urls=start_urls, rules=rules, items=item_imports
    )


def create_spiders(spiders, schemas, extractors, items):
    """Create all spiders from slybot spiders."""
    item_classes = ''
    if items:
        item_classes = '\nfrom ..items import {}'.format(
            ', '.join((v().__class__.__name__ for v in items.values()))
        )
    spider_data = []
    for name, (spider, spec) in spiders.items():
        log.info('Creating spider "%s"' % spider.name)
        spider = create_spider(name, spider, spec, schemas, extractors, items)
        cleaned_name = _clean(name)
        filename = 'spiders/{}.py'.format(cleaned_name)
        data = '\n'.join((SPIDER_FILE(item_classes=item_classes),
                          spider.strip()))
        code = fix_lines(fix_code(data.decode('utf-8')).splitlines(), Options)
        spider_data.append((filename, code))
    return spider_data


def port_project(dir_name, schemas, spiders, extractors):
    """Create project layout, default files and project specific code."""
    dir_name = class_name(dir_name)
    zbuff = StringIO()
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

    spider_data = create_spiders(spiders, schemas, extractors, schema_names)
    write_to_archive(archive, dir_name, spider_data)
    archive.finalize()
    archive.close()
    zbuff.seek(0)
    return zbuff
