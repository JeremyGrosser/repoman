# -*- coding: utf-8 -*-
#
# © 2010 SimpleGeo, Inc. All rights reserved.
# Author: Ian Eure <ian@simplegeo.com>
#

import wsgiref.simple_server as wsgi_server
from repoman.config import conf

class RequestHandler(object):
    def __init__(self, app, request):
        self.app = app
        self.request = request


class StaticHandler(RequestHandler):
    def get(self, path):
        if path.strip('/') == '':
            path = 'index.html'
        root = conf('server.static_path')
        path = os.path.join(root, path)
        if not path.startswith(root):
            return Response(status=400, body='400 Bad Request')
        else:
            return Response(status=200, body=file(path, 'rb').read())


class WSGIRequestHandler(wsgi_server.WSGIRequestHandler):

    def address_string(self):
        return self.client_address[0]
