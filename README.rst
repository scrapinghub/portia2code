Installation
============

To install ``portia_porter``:

::

    pip install portia2code

Purpose
=======

The purpose of this project is to give more options to users of Portia
and Scrapy.

In some cases when a spider is created with Portia it doesn't extract
the data correctly or some custom logic is needed to join different
pages together. This project allows you to get around those issues by
converting spiders from the JSON format used by Portia to Scrapy spiders
written in Python. With the Python code it can allow users to create
their own custom logic for extracting data.

For scrapy users it can give you the ability to bootstrap a spider using
Portia. Rather than going to a site in your browser and manually finding
the CSS/XPath selectors you can use the Portia tool to do that work for
you and export the spider as python code ready to be customised.

Port your project
=================

Once You have installed the tool you can port your project using the
command:

::

    portia_porter PROJECT_DIR OUT_DIR

You can download your portia project as python using

::

    export PROJECT_ID="PROJECT_ID"
    curl https://portia/api/projects/$PROJECT_ID/download?format=code



How it works
============

Spiders built with Portia consist of JSON definitions of which urls a
spider should crawl and how it should extract data from the data at
those urls. When running these spiders the JSON definitions are compiled
into a custom Scrapy spider with trained samples used for extraction.
The trained samples are used with the ``scrapely`` library to extract
data from similar pages. To build one of these trained samples an
annotated page must be passed to scrapely so it knows what data to
extract. In older versions of Portia these annotations were found in the
page by adding an attribute to each element called ``data-tagid=N``
where ``N`` is a unique incrementing integer for each open or self
closing tag on the page. Newer versions of Portia have changed this and
now use unique selectors for each annotated element on the page. Using
these unique selectors we are able to build an extraction tree that can
use item loaders on a page to extract the annotated data.

Customising Your Spiders
========================

If you want to change the functionality you can do so as you would with
any other scrapy spider. The spiders produced by Portia2Code are a
custom ``scrapy.CrawlSpider``, the code for which is included in the
downloaded project.

The example below demonstrates how to make an additional API request to
a metrics site when there is a meta property with the name ``metrics``
on the page.

    In the example the extended spider is separated out from the
    original spider, this is just to demonstrate the changes that you
    need to make when modifying the spider. In practice you would make
    changes to the spider in the same class.

.. code:: python

    from scrapy.linkextractors import LinkExtractor
    from scrapy.spiders import Rule

    from ..utils.spiders import BasePortiaSpider
    from ..utils.processors import Field
    from ..utils.processors import Item
    from ..items import ArticleItem


    class ExampleCom(BasePortiaSpider):
        name = "www.example.com"
        start_urls = [u'http://www.example.com/search/?q=articles']
        allowed_domains = [u'www.example.com']
        rules = [
            Rule(LinkExtractor(allow=(ur'\d{6}'), deny=()), callback='parse_item',
                 follow=True)
        ]
        items = [
            [Item(ArticleItem, None, u'#content', [
                  Field(u'title', u'.page_title *::text', []),
                  Field(u'Article', u'.article *::text', []),
                  Field(u'published', u'.date *::text', []),
                  Field(u'Authors', u'.authors *::text', []),
                  Field(u'pdf', u'#pdf-link::attr(href)', [])])]
        ]


    import json
    from scrapy import Request
    from six.moves.urllib.parse import urljoin


    class ExtendedExampleCom(ExampleCom):
        base_api_url = 'https://api.examplemetrics.com/v1/metrics/'
        allowed_domains = [u'www.example.com', u'api.examplemetrics.com']

        def parse_item(self, response):
            for item in super(ExtendedExampleCom, self).parse_item(response):
                score = response.css('meta[name="metrics"]::attr(content)')
                if score:
                    yield Request(
                        url=urljoin(self.base_api_url, score.extract()[0]),
                        callback=self.add_score, meta={'item': item})
                else:
                    yield item

        def add_score(self, response):
            item = response.meta['item']
            item['score'] = json.loads(response.body)['score']
            return item

What's happening here?
----------------------

Here is an example meta tag
``<meta name="metrics" content="area/1234">`` on this site. The content
attribute needs to be joined with a ``base_api_url`` to produce the full
url where the metrics are hosted.

The ``base_api_url`` is hosted at a different domain to the rest of the
site so we need to add the domain to ``allowed_domains`` so that it
doesn't get filtered by the offsite middleware.

Since the goal here is to add an additional field to the items that are
extracted from the definitons the first step is to overwrite the
``parse_item`` function for this class. The most important part of this
is to loop over the ``parse_item`` function in the superclass,
``for item in super(ClassName, self).parse_item(response):``. After this
the custom logic is added. First, checking if the meta property metrics
is present. If it is present then another request is sent with the
current item stored in the request meta, after the request is resolved
the ``score`` property is added to the item in the ``add_score`` method
from the json response and the item is returned. If the property is not
present then the item itself is returned.

    The ``parse_item`` method uses the ``items`` definitions to extract
    data from the response. The ``parse_item`` function from
    ``BasePortiaSpider`` only outputs ``scrapy.Item`` items so you don't
    need to handle ``scrapy.Request`` or other types of items when
    calling the function.

This pattern is quite common in spiders built with Portia. There are
some pages where to get some data like this the page would need to be
loaded in Splash which will greatly increase the time it takes to crawl
a site. Using this approach the additional data can be received using a
single small request rather than needing to load all additional
javascript and CSS just to have this data stored in the page.

Missing Features
================

Some features from Portia are still not available though this porting
mechanism but will hopefully be added in the future:

-  Load pages using Splash depending on crawl rules
-  Follow links automatically
-  Text data extractors (annotations generated by highlighting text)

Future Improvements
===================

-  Only Portia 2.0 spiders are supported for now but we will be adding
   support for Portia 1.0 spiders.

