#!/usr/bin/env python

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(name='repoman',
    version='1.3',
    description='RESTful Debian repo manageer and package builder',
    author='Jeremy Grosser',
    author_email='synack@digg.com',
    entry_points={
        'console_scripts': ['repomand = repoman.server:main',
                            'repoman = repoman.client:main'],
        },
    packages=['repoman'],
    install_requires=['ncore>=1.6',
                      'pycurl',
                      'webob',
                      'httplib2',
                      'simplejson'],
    dependency_links=['http://github.com/synack/ncore/downloads'],
    )
