# -*- coding: utf-8 -*-
#
# © 2010 SimpleGeo, Inc. All rights reserved.
# Author: Ian Eure <ian@simplegeo.com>
#

"""A command-line tool for interacting with repoman."""

from __future__ import with_statement
import sys
import time
import logging
import os.path
import tarfile
from textwrap import fill, dedent
from optparse import OptionParser
from itertools import imap, takewhile
from urllib import urlencode

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from decorator import decorator
import simplejson as json
from httplib2 import Http
from poster.encode import multipart_encode, MultipartParam

API_URL = os.getenv("REPOMAN_API_URL", "")


class ArgumentError(Exception):

    """Raised when invalid arguments are provided to a command."""


def format_dict(pkg):
    """Return a string containing a nicely formatted dict."""
    width = max(imap(len, pkg.iterkeys()))
    pkg['Description'] = fill(pkg['Description'], 79,
                              subsequent_indent=" " * (width + 2))

    return "\n".join("%*s: %s" % (width, field, val)
                     for (field, val) in pkg.iteritems())


@decorator
def explode_slashes(func, *args, **kwargs):
    """Explode slashes in args."""

    new_args = []
    for arg in args:
        if isinstance(arg, str):
            new_args.extend(arg.split("/"))
        else:
            new_args.append(arg)

    return func(*new_args, **kwargs)


def get_commands():
    """Return a list of commands and their descriptions."""
    out = ["%prog [OPTIONS] COMMAND [ARGS]", "", "Commands:"]

    width = max(imap(len, (name[4:] for name in globals()
                           if name.startswith('cmd_'))))

    for name in globals():
        item = globals()[name]
        if name.startswith('cmd_') and callable(item):
            out.append("  %*s - %s" % (width, name[4:],
                                       item.__doc__.split("\n")[0]))

    return "\n".join(out)


def get_parser():
    """Return an optionparser instance."""
    parser = OptionParser(get_commands())
    parser.add_option("-a", "--api", help="Base URL of the Repoman API.",
                      default=API_URL)
    parser.add_option("-d", "--debug", action="store_true",
                      help="Debug reqests & responses.")
    return parser


def request_internal(endpoint="", sub="repository", **kwargs):
    """Perform a request."""
    return Http().request(
        "%s/%s/%s" % (API_URL, sub, endpoint), **kwargs)


def request(endpoint="", sub="repository", **kwargs):
    """Perform a request."""
    (response, content) = request_internal(endpoint, sub, **kwargs)

    if response.status >= 500:
        raise Exception(content)

    try:
        return json.loads(content)
    except json.decoder.JSONDecodeError:
        return content or ""


def cmd_help(cmd):
    """Show command help."""
    return dedent(globals()['cmd_%s' % cmd].__doc__)


def _parse_changes(contents):
    """Return a tuple of (source_pkg, (changed_files)) from a .changes file."""
    return (
        contents.split("Source:")[1].strip().split("\n")[0],
        tuple(line.split(" ")[-1] for line in
              takewhile(lambda line: line.startswith(" "),
                        (contents.split("Files:")[1].split("\n"))[1:])))


def create_pack(changefile):
    """Return a tuple of (filename, StringIO)."""
    output = StringIO()

    with open(changefile, 'r') as change:
        (source_pkg, pkg_files) = _parse_changes(change.read())
    tarball = tarfile.open("%s.tar.gz" % source_pkg, 'w:gz',
                           fileobj=output)

    base_dir = os.path.dirname(changefile) or "."
    tarball.add(changefile, os.path.basename(changefile))
    for pkg_file in [line.split(" ")[-1] for line in file_lines]:
        tarball.add("%s/%s" % (base_dir, pkg_file), pkg_file)


    tarball.close()

    return (tarball.name, output)


def cmd_pack(*changefiles):
    """Create a packfile for uploading.

    pack FILE1 [FILE2 ... FILEN]
    """
    for changefile in changefiles:
        (name, contents) = create_pack(changefile)
        with open(name, 'w') as pack:
            pack.write(contents.getvalue())


def cmd_upload(dist, *pack_files):
    """Upload a package to the repo.

    upload DISTRIBUTION FILE1 [FILE2 ... FILEN]
    """

    if not pack_files:
        raise ArgumentError("No packfiles specified.")

    buf = ""
    for file_ in pack_files:
        print file_
        sys.stdout.flush()
        if file_.endswith(".changes"):
            (file_, pack) = create_pack(file_)
        else:
            pack = open(file_, 'r')

        print "Uploading %s" % file_
        try:
            (data, headers) = multipart_encode(
                (MultipartParam('package', filename=file_, fileobj=pack),))

            output = request(
                dist, method="POST", body="".join(data),
                headers=dict((key, str(val))
                             for (key, val) in headers.iteritems()))

            if isinstance(output, str):
                buf += "While uploading %s: %s" % (file_, output)
                continue

            buf += "\n\n".join(format_dict(pkg[0]) for pkg in output)
        finally:
            pack.close()

    return buf


@explode_slashes
def cmd_promote(dist, package, dest_dist):
    """Promote a package to another distribution.

    promote SOURCE_DIST/PACKAGE DEST_DIST
    """
    request("%s/%s/copy?dstdist=%s" % (dist, package, dest_dist),
            method="POST")
    return ""


@explode_slashes
def cmd_show(*path):
    """List known distributions or packages.

    List available distributions:
    show

    List packages in DISTRIBUTION:
    show DISTRIBUTION

    Show package details:
    show DISTRIBUTION/PACKAGE
    """
    output = request("/".join(path))
    if len(path) < 2:
        return "\n".join(sorted(output))

    return "\n\n".join(format_dict(pkg) for pkg in output)


@explode_slashes
def cmd_rm(dist, pkg):
    """Remove a package from a distribution.

    rm DIST/PACKAGE
    """
    request("%s/%s" % (dist, pkg), method="DELETE")


def _build(path, ref="origin/master"):
    """Perform a build."""
    return request(
        path, sub="buildbot", method="POST", body=urlencode({'ref': ref}),
        headers={'Content-Type': 'application/x-www-form-urlencoded'})


def _wait(build_id, poll_interval=1):
    """Wait until a build is complete."""
    resp = "not done"
    while "not done" in resp:
        time.sleep(poll_interval)
        resp = request("status/%s" % build_id, sub="buildbot")
        print ".",
        sys.stdout.flush()


def cmd_build(path, ref="origin/master"):
    """Build a package synchronously.

    This command works the same as build_async, except it doesn't
    return until the build is complete.
    """

    build_id = _build(path, ref)
    print "Building %s:%s, ID %s" % (path, ref, build_id)
    _wait(build_id)


def cmd_build_async(path, ref="origin/master"):
    """Build a package asynchronously.

    This will print a build identifier and return immediately; the
    package will build in the background.

    build REPO_PATH [REF]

    Example:

    build github.com/synack/repoman refs/tags/release-1.4.6-1
    """
    build_id = request(
        path, sub="buildbot", method="POST", body=urlencode({'ref': ref}),
        headers={'Content-Type': 'application/x-www-form-urlencoded'})
    return "Building %s:%s, ID %s" % (path, ref, build_id)


def cmd_status(build_id):
    """Return status of a build.

    status BUILD_ID
    """
    return request("status/%s" % build_id, sub="buildbot")


def cmd_wait(build_id):
    """Block until a build is complete.

    wait BUILD_ID
    """
    _wait(build_id)


def cmd_get(build_id):
    """Get the result of a build.

    get BUILD_ID
    """
    (resp, content) = request_internal("tarball/%s" % build_id, sub="buildbot")
    if resp.status != 200:
        return content

    with open('%s.tar' % build_id, 'w') as tarball:
        tarball.write(content)


def cmd_refs(repo):
    """Show refs we can build in a repo.

    refs github/synack/repoman
    """

    return "\n".join("%s %s" % tuple(pair)
                     for pair in request(repo, sub="buildbot"))


def cmd_policy(package):
    """Return available versions of a package in all dists.

    policy PACKAGE
    """
    dists = request()

    out = []
    width = max(imap(len, dists))
    for dist in sorted(dists):
        try:
            for version in request("%s/%s" % (dist, package)):
                out.append("%*s: %s (%s)" % (width, dist, version['Version'],
                                             version['Architecture']))
        except:
            pass
    return "\n".join(out)


def main():
    """The main entrypoint for the repoman CLI."""
    parser = get_parser()

    (opts, args) = parser.parse_args()

    if not args:
        parser.print_help()
        sys.exit(-1)

    globals()['API_URL'] = opts.api

    if opts.debug:
        logging.basicConfig(level=logging.DEBUG)

    func = 'cmd_%s' % args[0]
    if func not in globals():
        print "No such command: %s" % args[0]
        sys.exit(-1)

    try:
        output = globals()[func](*args[1:])

        if output:
            print output
    except (TypeError, ArgumentError), ex:
        print "Error: %s\n" % ex
        print cmd_help(args[0])
    except ValueError, ex:
        print ex
        if ex.args and 'argument' in ex.args[0]:
            print "Invalid argument:"
            print cmd_help(args[0])
        else:
            raise
