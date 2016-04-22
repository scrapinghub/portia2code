from scrapely.extraction.regionextract import (
    RecordExtractor, BasicTypeExtractor
)
from slybot.plugins.scrapely_annotations.extraction import (
    BaseContainerExtractor
)
from .utils import extractor_to_field, container_to_item


class ItemBuilder(object):
    def __init__(self, schemas, extractors, items, default_item):
        self.schemas = schemas
        self.extractors = extractors
        self.items = items
        self.default_item = default_item
        self.numfields = 0

    def extract(self, samples):
        data = []
        for sample in samples:
            self.numfields = 0
            trees = sample.extraction_trees
            items = []
            for tree in trees:
                for extractor in tree.extractors:
                    if isinstance(extractor, BaseContainerExtractor):
                        items.extend(self.container(extractor, None) or [])
            data.append((self.numfields, items))
        data.sort(reverse=True)
        return [d[1] for d in data]

    def container(self, container, schema_id):
        if getattr(container, 'schema', None):
            descriptor = container.schema
            schema_id = descriptor.name
        extractors = container.extractors
        if (len(extractors) == 1 and
                isinstance(extractors[0], (BaseContainerExtractor,))):
            return self.container(extractors[0], schema_id)
        fields = []
        schema = self.schemas.get(schema_id, {})
        for ext in extractors:
            if isinstance(ext, RecordExtractor):
                fields.extend(self.record_extractor(ext, schema))
            elif isinstance(ext, BasicTypeExtractor):
                fields.extend(self.base_extractor(ext, schema))
            elif isinstance(ext, BaseContainerExtractor):
                fields.append(self.container(ext, schema_id))
        self.numfields += len(fields)
        return container_to_item(container, fields, schema,
                                 self.items.get(schema_id, self.default_item))

    def record_extractor(self, extractor, schema):
        items = []
        for ext in extractor.extractors:
            items.extend(extractor_to_field(ext, schema, self.extractors))
        return items

    def base_extractor(self, extractor, schema):
        return extractor_to_field(extractor, schema, self.extractors)
