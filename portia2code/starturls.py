# Mock out starturls for ../spiders.py file
class MockGenerator(object):
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return []


class FeedGenerator(MockGenerator):
    pass


class FragmentGenerator(MockGenerator):
    pass
