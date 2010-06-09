# -*- coding: utf-8 -*-
#
# © 2010 SimpleGeo, Inc. All rights reserved.
# Author: Ian Eure <ian@simplegeo.com>
#

"""Unit tests for the repoman client."""

import os
import repoman.client as client


def check_parsing(changefile, expected):
    """Verify that parsing succeds with problematic .changes files."""
    with open("%s/changefiles/%s" % (os.path.dirname(__file__), changefile),
                                     'r') as change:
        changes = change.read()
        parsed = client._parse_changes(changes)
        assert len(parsed) == 2
        assert set(parsed[1]) == set(expected), \
            "Incorrect result: %r" % \
            set(parsed[1]).symmetric_difference(set(expected))

        for file_ in parsed[1]:
            assert file_ in expected


def test_parsing():
    expected = ("puppet_0.25.5-sg1.dsc",
                "puppet_0.25.5.orig.tar.gz",
                "puppet_0.25.5-sg1.debian.tar.gz",
                "puppet_0.25.5-sg1_all.deb",
                "puppetmaster_0.25.5-sg1_all.deb",
                "puppet-common_0.25.5-sg1_all.deb",
                "vim-puppet_0.25.5-sg1_all.deb",
                "puppet-el_0.25.5-sg1_all.deb",
                "puppet-testsuite_0.25.5-sg1_all.deb")

    fixture_dir = os.path.dirname(__file__) + '/changefiles/'
    for change in (os.listdir(fixture_dir)):
        yield (check_parsing, change, expected)
