#!/usr/bin/env python

import sys
from traceback import format_exc
from multiprocessing import Process

from wsgiref.simple_server import make_server, WSGIRequestHandler
from ncore.daemon import become_daemon

from repoman.config import conf
from repoman.wsgi import Application, StaticHandler
from repoman import repository
from repoman import buildbot


class CustomWSGIRequestHandler(WSGIRequestHandler):

    def address_string(self):
        return self.client_address[0]


def main():
    app = Application([
        ('^/repository/(?P<dist>[-\w]+)/(?P<package>[a-z0-9][a-z0-9+-.]+)/(?P<action>\w+)/*$',
            repository.PackageHandler),
        ('^/repository/(?P<dist>[-\w]+)/(?P<package>[a-z0-9][a-z0-9+-.]+)/*$',
            repository.PackageHandler),
        ('^/repository/(?P<dist>[-\w]+)/*$',
            repository.DistHandler),
        ('^/repository/*$',
            repository.RepoHandler),
        ('^/buildbot/status/(?P<buildid>[a-z0-9]{32})/*$',
            buildbot.StatusHandler),
        ('^/buildbot/tarball/(?P<buildid>[a-z0-9]{32})/*$',
            buildbot.TarballHandler),
        ('^/buildbot/(?P<gitpath>[a-z]+)/(?P<gitrepo>.+)/*$',
            buildbot.PackageHandler),
        ('^/buildbot/(?P<gitpath>[a-z]+)/*$',
            buildbot.RepoListHandler),
        ('^/(?P<path>.*)/*$',
            StaticHandler),
    ])

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


if __name__ == '__main__':
    main()
