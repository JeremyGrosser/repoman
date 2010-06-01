#!/usr/bin/env python

import sys

import daemon

from repoman.config import conf
from repoman.wsgi import get_server
from repoman import repository
from repoman import buildbot

def get_context():
    context = {'working_directory': '.',
               'detach_process': False}
    if conf('server.daemonize'):
        log_file = open(conf('server.daemon_log'), 'w+')
        context.update(detach_process=True,
                       stdout=log_file,
                       stderr=log_file)
    else:
        context.update(files_preserve=[sys.stdout, sys.stderr],
                       stdout=sys.stdout,
                       stderr=sys.stderr)

    return daemon.DaemonContext(**context)



def main():
    with get_context():
        get_server().serve_forever()


