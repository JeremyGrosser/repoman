#!/usr/bin/env python

from ez_setup import use_setuptools
use_setuptools()

from setuptools import setup

setup(name='repoman',
    version='1.5.1',
    description='RESTful Debian repo manageer and package builder',
    author='Jeremy Grosser',
    author_email='synack@digg.com',
    scripts=['scripts/repoman', 'scripts/repomand'],
    packages=['repoman'],
    dependency_links=['http://synack.me/files/dist/'],
    install_requires=['python-daemon>=1.5.0',
                      'pycurl',
                      'webob',
                      'httplib2',
                      'simplejson',
                      'poster'],
    tests_require=['nose'],
    )
