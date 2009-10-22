from ncore.serialize import dumps, loads
from gnupg import GPG
from webob import Response
from wsgi import RequestHandler

from subprocess import Popen, PIPE
import logging
import os.path
import os

import tarfile
import uuid

from config import conf

try:
    import json
except ImportError:
    import simplejson as json

def unique(lst):
    s = {}
    [s.__setitem__(repr(p), p) for p in lst]
    return s.values()

class Repository(object):
    def __init__(self, path):
        self.path = path

    def _reprepro(self, args):
        os.chdir(self.path)
        p = Popen(['/usr/bin/reprepro', '-Vb.'] + args.split(' '), stdout=PIPE, stderr=PIPE)
        return (p.communicate(), p.returncode)

    def get_dists(self):
        results = []
        distdir = os.path.join(self.path, 'dists')
        for dist in os.listdir(distdir):
            distpath = os.path.join(distdir, dist)
            if os.path.islink(distpath) or not os.path.isdir(distpath):
                continue
            results.append(dist)
        return results

    def create_dist(self, distinfo):
        if distinfo['Codename'] in self.get_dists():
            raise ValueError('Cannot create distribution %s, it already exists' % label)

        dist = ['%s: %s' % (k, v) for k, v in distinfo.items() if k and v]
        dist.insert(0, '')
        dist = '\n'.join(dist)

        fd = file(os.path.join(self.path, 'conf/distributions'), 'a')
        fd.write(dist)
        fd.close()

        self._reprepro('export')

    def get_packages(self, dist):
        # This code is evil and ugly... Don't stare at it for too long
        results = {}
        distdir = os.path.join(self.path, 'dists/%s' % dist)
        for dirpath, dirnames, filenames in os.walk(distdir):
            for name in filenames:
                if name != 'Packages': continue
                path = os.path.join(dirpath, name)
                packages = file(path, 'r').read()
                packages = packages.split('\n\n')
                for pkg in packages:
                    fields = []
                    for field in pkg.split('\n'):
                        if not field: continue
                        if field[0].isalpha():
                            fields.append(field.split(': ', 1))
                        else:
                            fields[-1][1] += field
                    if not fields: continue
                    pkg = dict(fields)
                    pkgname = pkg['Package']
                    if not pkgname in results:
                        results[pkgname] = []
                    results[pkgname].append(pkg)
        return results

    def get_package(self, dist, package):
        p = self.get_packages(dist)
        return unique(p.get(package, []))

    def sign(self, dist):
        self._reprepro('export %s' % dist)

        gpg = GPG()
        filename = os.path.join(self.path, 'dists/%s/Release' % dist)
        detach_file = filename + '.gpg'
        try:
            os.unlink(detach_file)
        except: pass
        result = gpg.sign_file(file(filename, 'r'), keyid=conf('repository.signkey'), outputfile=detach_file)

    def copy_package(self, srcdist, dstdist, package):
        self._reprepro('copy %s %s %s' % (dstdist, srcdist, package))
        self.sign(dstdist)

    def add_package(self, dist, changes):
        result = self._reprepro('-Pnormal --ignore=wrongdistribution include %s %s' % (dist, changes))
        self.sign(dist)
        return result

    def remove_package(self, dist, package):
        output, retcode = self._reprepro('remove %s %s' % (dist, package))
        self.sign(dist)
        return output[1]

class RepoHandler(RequestHandler):
    def get(self):
        repo = Repository(conf('repository.path'))
        return Response(body=dumps(self.request.params, repo.get_dists()))

    def post(self):
        repo = Repository(conf('repository.path'))
        dist = {
            'Version': '5.0',
            'Architectures': 'amd64 source any',
            'Components': 'main contrib non-free',
            'Description': 'Default package repository',
        }
        dist.update(json.loads(self.request.body))
        for field in ['Origin', 'Label', 'Suite', 'Codename']:
            if not field in dist:
                return Response(status=400, body='Required field %s is missing.' % field)
        repo.create_dist(dist)

class DistHandler(RequestHandler):
    def get(self, dist=None, action=None):
        repo = Repository(conf('repository.path'))
        return Response(body=dumps(self.request.params, repo.get_packages(dist).keys()))

    def post(self, dist):
        repo = Repository(conf('repository.path'))
        response = None

        basedir = '/tmp/repoman.upload/%s' % uuid.uuid4().hex
        os.makedirs(basedir)
        os.chdir(basedir)

        field = self.request.params['package']

        name = os.path.basename(field.filename)
        if not name.endswith('tar.gz') and not name.endswith('tar.bz2'):
            return Response(status=400, body='Packages must be uploaded as .tar.gz or tar.bz2 files containing .changes, .dsc, and .deb files')

        fd = file(name, 'wb')
        fd.write(field.value)
        fd.close()

        tf = tarfile.open(name, 'r|*')
        tf.extractall()
        changesfile = [x for x in os.listdir(basedir) if x.endswith('.changes')]
        if not changesfile:
            return Response(status=400, body='Tarball does not contain a .changes file')

        packages = []
        for changes in changesfile:
            changes = os.path.join(basedir, changes)
            stderr, stdout = repo.add_package(dist, changes)[0]
            if stdout:
                logging.debug('add_package: %s' % stdout)
            if stderr:
                logging.warning('add_package: %s' % stderr)
            for p in [x.split(': ', 1)[1].rstrip('\r\n').split(' ') for x in file(changes, 'r').readlines() if x.startswith('Binary: ')]:
                for bin in p:
                    pkg = repo.get_package(dist, bin)
                    packages.append(pkg)
        response = Response(status=200, body=dumps(self.request.params, packages))

        for dirpath, dirnames, filenames in os.walk(basedir):
            for filename in filenames:
                filename = os.path.join(dirpath, filename)
                os.remove(filename)
        os.rmdir(basedir)
        
        if not response:
            response = Response(status=500)
        return response

class PackageHandler(RequestHandler):
    def get(self, dist, package):
        repo = Repository(conf('repository.path'))

        if dist and package:
            pkg = repo.get_package(dist, package)
            if not pkg:
                return Response(status=404, body=dumps(self.request.params, []))

            return Response(status=200, body=dumps(self.request.params, pkg))

        if dist and not package:
            result = repo.get_packages(dist).keys()
            if not result:
                return Response(status=404, body=dumps(self.request.params, []))
            return Response(status=200, body=dumps(self.request.params, result))

        if not dist:
            result = repo.get_dists()
            if not result:
                return Response(status=404, body=dumps(self.request.params, []))
            return Response(status=200, body=dumps(self.request.params, result))

    def post(self, dist=None, package=None, action=None):
        repo = Repository(conf('repository.path'))
        if not dist or not package or not action:
            return Response(status=405)

        if action == 'copy':
            if not 'dstdist' in self.request.params:
                return Response(status=400, body='A required parameter, dstdist is missing')
            repo.copy_package(dist, self.request.params['dstdist'], package)
            return Response(status=200)

    def delete(self, dist=None, package=None, action=None):
        repo = Repository(conf('repository.path'))
        if action:
            return Response(status=405, body='You cannot delete an action')
        if not dist or not package:
            return Response(status=400, body='You must specify a dist and package to delete from it')

        result = repo.remove_package(dist, package)
        if result:
            return Response(status=404, body=result)
        return Response(status=200)
