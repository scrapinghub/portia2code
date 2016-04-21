from scrapy.spiders import CrawlSpider
from scrapy.loader import ItemLoader
from scrapy.utils.response import get_base_url


class RequiredFieldMissing(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg


class PortiaItemLoader(ItemLoader):
    def get_value(self, value, *processors, **kw):
        required = kw.pop('required', False)
        v = super(PortiaItemLoader, self).get_value(value, *processors, **kw)
        if required and not v:
            raise RequiredFieldMissing(
                'Missing required field "{value}" for "{item}"'.format(
                    value=value, item=self.item.__class__.__name__))
        return v


class BasePortiaSpider(CrawlSpider):
    def parse_item(self, response):
        for sample in self.items:
            items = []
            try:
                for definition in sample:
                    items.append(self.load_item(definition, response))
            except RequiredFieldMissing as e:
                self.logger.warning(str(e))
            if items:
                for item in items:
                    yield item

    def load_item(self, definition, response):
        l = PortiaItemLoader(item=definition.item(), response=response,
                             baseurl=get_base_url(response))
        for field in definition.fields:
            if hasattr(field, 'fields'):
                if field.name is not None:
                    l.add_value(field.name, self.load_item(field, response))
            else:
                l.add_css(field.name, field.selector, *field.processors,
                          required=field.required)
        return l.load_item()
