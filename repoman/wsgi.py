from webob import Request, Response
import httplib
import os.path
import re
from wsgiref.simple_server import make_server

from config import conf

import buildbot
import repository
from common import StaticHandler, WSGIRequestHandler


class Application(object):
    def __init__(self, extra_urls=None):
        extra_urls = extra_urls or []
        self.handlers = [(re.compile(pattern), handler)
                         for pattern, handler in DEFAULT_URLS + extra_urls]

    def __call__(self, environ, start_response):
        request = Request(environ)
        response = None

        for pattern, handler in self.handlers:
            match = pattern.match(request.path_info)
            if not match: continue
            handler = handler(self, request)
            if hasattr(handler, request.method.lower()):
                f = getattr(handler, request.method.lower())
                response = f(**match.groupdict())
            else:
                response = Response(status=501)
            break

        if not response:
            response = Response(status=404)

        return response(environ, start_response)


def get_server():
    return make_server(conf('server.bind_address'),
                         conf('server.bind_port'), Application(),
                         handler_class=WSGIRequestHandler)


DEFAULT_URLS = [
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
    ]
