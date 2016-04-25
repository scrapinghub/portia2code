SPIDER_FILE = """\
from __future__ import absolute_import

from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.loader.processors import Identity
from scrapy.spiders import Rule

from ..utils.spiders import BasePortiaSpider
from ..utils.starturls import UrlGenerator
from ..utils.processors import Item, Field, Text, Number, Price, Date, Url, \
Image, Regex{item_classes}


""".format
SPIDER_CLASS = """
class {class_name}(BasePortiaSpider):
    name = "{name}"
    allowed_domains = {allowed_domains}
    start_urls = {start_urls}
    {rules}
    items = {items}
""".format
ITEMS_IMPORTS = """
from __future__ import absolute_import

import scrapy
from collections import defaultdict
from scrapy.loader.processors import Join, MapCompose, Identity
from w3lib.html import remove_tags
from .utils.processors import Text, Number, Price, Date, Url, Image


class PortiaItem(scrapy.Item):
    fields = defaultdict(
        lambda: scrapy.Field(
            input_processor = Identity(),
            output_processor = Identity()
        )
    )
    def __setitem__(self, key, value):
        self._values[key] = value

    def __repr__(self):
        data = str(self)
        if not data:
            return '%s' % self.__class__.__name__
        return '%s(%s)' % (self.__class__.__name__, data)

    def __str__(self):
        if not self._values:
            return ''
        string = super(PortiaItem, self).__repr__()
        return string

"""
ITEM_CLASS = """\
class {name}Item(PortiaItem):
{fields}
""".format
ITEM_FIELD = """\
    {name} = scrapy.Field(
        input_processor={input},
        output_processor={output},
    )
""".format
RULES = """\
rules = [
        Rule(
            LinkExtractor(
                allow=({allow}),
                deny=({deny})
            ),
            callback='parse_item',
            follow=True
        )
    ]\
""".format
