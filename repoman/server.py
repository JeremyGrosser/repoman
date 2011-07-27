#!/usr/bin/env python

import sys
import daemon

from optparse import OptionParser

from repoman.config import conf, set_log_conf, set_web_conf
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
    parser = OptionParser()
    parser.add_option("-l", "--logging-config", help="Logging config file", default="/etc/repoman/logging.conf")
    parser.add_option("-w", "--web-config", help="Web config file", default="/etc/repoman/web.conf")
    (options, args) = parser.parse_args()
    set_log_conf(options.logging_config)
    set_web_conf(options.web_config)
    with get_context():
        get_server().serve_forever()


