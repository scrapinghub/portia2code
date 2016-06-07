#!/usr/bin/env python

from setuptools import setup, find_packages
from portia2code import __version__ as version

install_requires = ['Scrapy', 'slybot', 'dateparser', 'six', 'w3lib',
                    'scrapely', 'autoflake', 'autopep8']

setup(
    name='portia2code',
    version=version,
    license='BSD',
    description='Convert portia spider definitions to python scrapy spiders',
    author='Scrapinghub',
    author_email='info@scrapinghub.com',
    maintainer='Ruairi Fahy',
    maintainer_email='ruairi@scrapinghub.com',
    packages=find_packages(exclude=('tests', 'tests.*')),
    platforms=['Any'],
    scripts=['bin/portia_porter'],
    install_requires=install_requires,
    url='https://github.com/scrapinghub/portia2code',
    download_url = 'https://github.com/scrapinghub/portia2code/tarball/portia2code-{}'.format(version),
    classifiers=[
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7'
    ]
)
