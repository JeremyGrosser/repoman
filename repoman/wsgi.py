from webob import Request, Response
import httplib
import os.path
import re

from config import conf

class RequestHandler(object):
    def __init__(self, app, request):
        self.app = app
        self.request = request

class StaticHandler(RequestHandler):
    def get(self, path):
        if path.strip('/') == '':
            path = '/index.html'
        root = conf('server.static_path')
        path = os.path.join(root, path)
        if not path.startswith(root):
            return Response(status=400, body='400 Bad Request')
        else:
            return Response(status=200, body=file(path, 'rb').read())

class Application(object):
    def __init__(self, urls):
        self.handlers = [(re.compile(pattern), handler) for pattern, handler in urls]

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

if __name__ == '__main__':
    from wsgiref.simple_server import make_server

    if conf('server.daemonize'):
        from ncore.daemon import become_daemon
        become_daemon(out_log=conf('server.daemon_log'), err_log=conf('server.daemon_log'))

    app = WSGIApp([
        ('/repository/(?P<dist>[-\w]+)/(?P<package>[a-z0-9][a-z0-9+-.]+)/(?P<action>\w+)/*',
            repository.PackageHandler),
        ('/repository/(?P<dist>[-\w]+)/(?P<package>[a-z0-9][a-z0-9+-.]+)/*',
            repository.PackageHandler),
        ('/repository/(?P<dist>[-\w]+)/*',
            repository.DistHandler),
        ('/repository/',
            repository.RepoHandler),
        ('/buildbot/tarball/(?P<buildid>[a-z0-9]{32})/*',
            buildbot.BuildStatusHandler),
        ('/buildbot/(?P<package>.+)/*',
            buildbot.PackageHandler),
    ])

    server = make_server(conf('server.bind_address'), conf('server.bind_port'), app)
    server.serve_forever()
