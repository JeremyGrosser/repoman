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
    scripts=['scripts/repoman'],
    packages=['repoman'],
    install_requires=['ncore>=1.6',
                      'pycurl',
                      'webob',
                      'simplejson'],
    dependency_links=['http://github.com/synack/ncore/downloads'],
    )
