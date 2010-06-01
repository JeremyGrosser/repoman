#!/usr/bin/env python

import sys
from traceback import format_exc
from multiprocessing import Process

from wsgiref.simple_server import make_server
import daemon

from repoman.config import conf
from repoman.wsgi import get_server
from repoman import repository
from repoman import buildbot



def main():
    server = get_server()

    try:
        if conf('server.daemonize'):
            become_daemon(out_log=conf('server.daemon_log'),
                          err_log=conf('server.daemon_log'))

        p = Process(target=buildbot.build_worker)
        p.start()

        server = make_server(conf('server.bind_address'),
                             conf('server.bind_port'), app,
                             handler_class=CustomWSGIRequestHandler)
        server.serve_forever()
    except:
        sys.stderr.write(format_exc() + '\n')
        if 'p' in locals():
            p.terminate()
