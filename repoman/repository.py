from simplejson import dumps, loads
from gnupg import GPG
from webob import Response
from common import RequestHandler

from subprocess import Popen, PIPE
from base64 import b64decode
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

    def backup_package(self, dist, backupdist, package):
        logging.info('Backing up %s from %s to %s' % (package, dist, backupdist))
        self.remove_package(backupdist, package)
        self.copy_package(dist, backupdist, package)

    def rollback_package(self, dist, backupdist, package):
        logging.info('Rolling back %s from %s to %s' % (package, backupdist, dist))
        if not self.get_package(backupdist, package):
            logging.error('%s does not exist in %s, unable to rollback' % (package, backupdist))
            return False
        self.remove_package(dist, package)
        self.copy_package(backupdist, dist, package)

class RepoHandler(RequestHandler):
    def get(self):
        repo = Repository(conf('repository.path'))
        return Response(body=dumps(repo.get_dists()))

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
        return Response(body=dumps(repo.get_packages(dist).keys()))

    def post_copy(self, dist, package, srcdist):
        dstdist = dist
        if dstdist in conf('repository.backup'):
            repo.backup_package(dstdist, conf('repository.backup')[dstdist], package)
        repo.copy_package(srcdist, dstdist, package)
        return Response(status=200)

    def post_rollback(self, dist, package):
        if dist in conf('repository.backup'):
            backupdist = conf('repository.backup')[dist]
        else:
            errormsg = 'Attempt to rollback in a dist not defined by repository.backup. Refusing to do it.'
            logging.error(errormsg)
            return Response(status=400, body=errormsg + '\n')
        repo.rollback_package(dist, backupdist, package)
        return Response(status=200)

    def post(self, dist):
        repo = Repository(conf('repository.path'))

        body = self.request.body.read()
        for query in re.split('\s+', body):
            query = dict([(k, v[0]) for k,v in list(parse_qs(query))])
            for field in ('package', 'action'):
                if not field in query:
                    return Response(status=400, body='Required field %s is missing from POST body\n' % field)

        if hasattr('post_' + query['action'], self):
            func = getattr('post_' + query['action'], self)
            del query['action']
            return func(dist, **query)

        if not dist or not package or not action:
            return Response(status=405)

    def put(self, dist):
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
        response = Response(status=200, body=dumps(packages))

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
                return Response(status=404, body=dumps([]))

            return Response(status=200, body=dumps(pkg))

        if dist and not package:
            result = repo.get_packages(dist).keys()
            if not result:
                return Response(status=404, body=dumps([]))
            return Response(status=200, body=dumps(result))

        if not dist:
            result = repo.get_dists()
            if not result:
                return Response(status=404, body=dumps([]))
            return Response(status=200, body=dumps(result))

    def delete(self, dist, package):
        repo = Repository(conf('repository.path'))

        result = repo.remove_package(dist, package)
        if result:
            return Response(status=404, body=result)
        return Response(status=200)
