import inspect
import re
import six

from six.moves.urllib.parse import urljoin, urlparse, urlunparse

from copy import deepcopy
from itertools import chain
try:
    from itertools import izip_longest
except ImportError:
    from itertools import zip_longest as izip_longest

from dateparser.date import DateDataParser
from scrapy.loader.processors import Identity as _Identity
from scrapy.utils.markup import unquote_markup
from w3lib.html import remove_tags
from .parser import SafeHtmlParser


# Regeps from Scrapely_CSS_IMAGERE.pattern
_CSS_IMAGERE = re.compile(r'background(?:-image)?\s*:\s*url\((.*?)\)')
_GENERIC_PATH_RE = re.compile('/?(?:[^/]+/)*(?:.+)')
_IMAGE_PATH_RE = re.compile(r'/?(?:[^/]+/)*(?:.+\.(?:mng|pct|bmp|gif|jpg|jpeg|'
                            r'png|pst|psp|tif|tiff|ai|drw|dxf|eps|ps|svg))')
_NUMERIC_ENTITIES = re.compile(r'&#([0-9]+)(?:;|\s)', re.U)
_PRICE_NUMBER_RE = re.compile(r'(?:^|[^a-zA-Z0-9])(\d+(?:\.\d+)?)'
                              r'(?:$|[^a-zA-Z0-9])')
_NUMBER_RE = re.compile(r'(-?\d+(?:\.\d+)?)')
_DECIMAL_RE = re.compile(r'(\d[\d\,]*(?:(?:\.\d+)|(?:)))', re.U | re.M)
_VALPARTS_RE = re.compile(r'([\.,]?\d+)')
_SENTINEL = object()


def _strip_url(text):
    if text:
        return text.strip("\t\r\n '\"")


def extract_image_url(text):
    text = _strip_url(text)
    imgurl = None
    if text:
        # check if the text is style content
        match = _CSS_IMAGERE.search(text)
        text = match.groups()[0] if match else text
        parsed = urlparse(text)
        path = None
        match = _IMAGE_PATH_RE.search(parsed.path)
        if match:
            path = match.group()
        elif parsed.query:
            match = _GENERIC_PATH_RE.search(parsed.path)
            if match:
                path = match.group()
        if path is not None:
            parsed = list(parsed)
            parsed[2] = path
            imgurl = urlunparse(parsed)
        if not imgurl:
            imgurl = text
    return imgurl


class BaseProcessor(object):
    def __init__(self):
        super(BaseProcessor, self).__init__()

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, str(self))

    def __str__(self):
        argspec = inspect.getargspec(self.__init__)
        args = argspec.args
        defaults = argspec.defaults or []
        joined = reversed(list(izip_longest(reversed(args), reversed(defaults),
                                            fillvalue=_SENTINEL)))
        next(joined)  # Skip self
        values = []
        skipped = False
        for attribute, default in joined:
            value = getattr(self, attribute)
            if value == default:
                skipped = True
                continue
            if skipped:
                values.append('{}={}'.format(attribute, repr(value)))
            else:
                values.append(repr(value))

        return ', '.join(values)

    def __eq__(self, other):
        return repr(self) == repr(other)

    def __hash__(self):
        return hash(str(self))


class Field(BaseProcessor):
    def __init__(self, name, selector, processors=None, required=False,
                 type='css'):
        if processors is None:
            processors = []
        self.name = name
        self.selector = selector
        self.processors = processors
        self.required = required
        self.type = type


class Item(BaseProcessor):
    def __init__(self, item, name, selector, fields, type='css'):
        self.item = item
        self.name = name
        self.selector = selector
        self.fields = fields
        self.type = type


class Identity(BaseProcessor, _Identity):
    pass


class Text(BaseProcessor):
    def __call__(self, values):
        return [remove_tags(v).strip()
                if v and isinstance(v, six.string_types) else v
                for v in values]


class Number(BaseProcessor):
    def __call__(self, values):
        numbers = []
        for value in values:
            if isinstance(value, (dict, list)):
                numbers.append(value)
            txt = _NUMERIC_ENTITIES.sub(lambda m: unichr(int(m.groups()[0])),
                                        value)
            numbers.append(_NUMBER_RE.findall(txt))
        return list(chain(*numbers))


class Price(BaseProcessor):
    def __call__(self, values):
        prices = []
        for value in values:
            if isinstance(value, (dict, list)):
                prices.append(value)
            txt = _NUMERIC_ENTITIES.sub(lambda m: unichr(int(m.groups()[0])),
                                        value)
            m = _DECIMAL_RE.search(txt)
            if m:
                value = m.group(1)
                parts = _VALPARTS_RE.findall(value)
                decimalpart = parts.pop(-1)
                if decimalpart[0] == "," and len(decimalpart) <= 3:
                    decimalpart = decimalpart.replace(",", ".")
                value = "".join(parts + [decimalpart]).replace(",", "")
                prices.append(value)
        return prices


class Date(Text):
    def __init__(self, format='%Y-%m-%dT%H:%M:%S'):
        self.format = format

    def __call__(self, values):
        values = super(Date, self).__call__(values)
        dates = []
        for text in values:
            if isinstance(text, (dict, list)):
                dates.append(text)
            try:
                date = DateDataParser().get_date_data(text)['date_obj']
                dates.append(date.strftime(self.format))
            except ValueError:
                pass
        return dates


class Url(Text):
    def __call__(self, values, loader_context=None):
        values = super(Url, self).__call__(values)
        urls = []
        for value in values:
            if isinstance(value, (dict, list)):
                urls.append(value)
            value = _strip_url(unquote_markup(value))
            base = loader_context.get('baseurl', '')
            urls.append(urljoin(base, value))
        return urls


class Image(Text):
    def __call__(self, values):
        return super(Image, self).__call__([
            val if isinstance(val, (dict, list)) else extract_image_url(val)
            for val in values
        ])


class SafeHtml(Text):

    def __init__(self, parser=None):
        if parser is None:
            parser = SafeHtmlParser()
        self.parser = parser

    def __call__(self, values):
        results = []
        for val in values:
            if isinstance(val, (dict, list)):
                results.append(val)
            results.append(self.parser.feed(str(val)))
        return results


class Regex(BaseProcessor):
    def __init__(self, regexp):
        if isinstance(regexp, six.string_types):
            regexp = re.compile(regexp)
        self.regexp = regexp.pattern
        self._regexp = regexp

    def __call__(self, values):
        results = []
        for value in values:
            if isinstance(value, (dict, list)):
                results.append(value)
            if not value:
                continue
            match = self._regexp.search(value)
            if not match:
                continue
            results.append(
                u"".join([g for g in match.groups() or match.group() if g])
            )
        return results

    def __deepcopy__(self, memo):
        """Overwrite deepcopy so that the regexp is recalculated."""
        return type(self)(deepcopy(self.regexp, memo))
