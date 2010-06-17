from poster.streaminghttp import register_openers
from poster.encode import multipart_encode
from simplejson import dumps
from webob import Response

from subprocess import Popen, PIPE, STDOUT
from multiprocessing import Process, Queue
from urllib2 import Request, urlopen
from traceback import format_exc
from urlparse import urljoin
from time import sleep
import logging
import tarfile
import os
import os.path
import urllib
import uuid
import sys
import os

from config import conf
from common import RequestHandler

register_openers()

class GitRepository(object):
    def __init__(self, path=None):
        self.path = path

    def _cmd(self, args, shell=False):
        try:
            os.chdir(self.path)
        except: pass
        logging.debug('cwd: %s    exec: %s' % (os.getcwd(), ' '.join(args)))
        p = Popen(args, stdout=PIPE, stderr=PIPE, shell=shell)
        ret = (p.communicate(), p.returncode)
        if ret[0][0]:
            logging.debug('\n'.join(ret[0]))
        return ret

    def _git(self, args):
        return self._cmd(['/usr/bin/git'] + args)

    def clone(self, gitpath):
        return self._git(['clone', gitpath, self.path])

    def checkout(self, ref):
        return self._git(['checkout', ref])

    def submodule_init(self):
        return self._git(['submodule', 'init'])

    def submodule_update(self):
        return self._git(['submodule', 'update'])

    def ls_remote(self, gitpath):
        output, retcode = self._git(['ls-remote', '--heads', '--tags', gitpath])
        stdout, stderr = output
        return [x.split('\t') for x in stdout.split('\n') if x]

    def show_ref(self):
        output, retcode = self._git(['show-ref', '--heads', '--tags'])
        stdout, stderr = output
        return [x.split(' ', 1) for x in stdout.split('\n') if x]

    def build(self, signkey, pbuilderrc, resultsdir):
        if 'refs/heads/upstream' in [x[1] for x in self.show_ref()]:
            cmd = ['/usr/bin/git-buildpackage', '--git-sign', '--git-cleaner="fakeroot debian/rules clean"', '--git-keyid="%s"' % signkey, '--git-builder="pdebuild --debsign-k %s --auto-debsign --configfile %s --debbuildopts "-i.git -I.git -sa" --buildresult %s' % (signkey, pbuilderrc, resultsdir)]
        else:
            cmd = ['/usr/bin/pdebuild', '--debsign-k', signkey, '--auto-debsign', '--debbuildopts', '-i\.git -I.git -sa', '--configfile', pbuilderrc, '--buildresult', resultsdir]
        return Popen(cmd, stdout=PIPE, stderr=STDOUT)

class PackageHandler(RequestHandler):
    def get(self, gitpath, gitrepo):
        gitpath = os.path.join(conf('buildbot.gitpath.%s' % gitpath), gitrepo)

        repo = GitRepository()
        refs = repo.ls_remote(gitpath)
        return Response(status=200, body=dumps(refs))

    def post(self, gitpath, gitrepo):
        if not 'ref' in self.request.params:
            return Response(status=400, body='Required parameter "ref" is missing. You must pass a git tag, branch, or commit ID to be built.\n')

        gitpath = os.path.join(conf('buildbot.gitpath.%s' % gitpath), gitrepo)
        gitref = self.request.params['ref']
        cburl = self.request.params.get('cburl', None)
        submodules = self.request.params.get('submodules', None)
        environment = self.request.params.get('environment', 'stable')

        if cburl:
            cburl = cburl.split(',')
        else:
            cburl = []

        build = BuildTask(gitpath, gitref, environment, callbacks=cburl, bool(submodules))
        buildq.put(build)
        return Response(status=200, body=build.id + '\n')

class RepoListHandler(RequestHandler):
    def get(self, gitpath):
        try:
            gitindex = conf('buildbot.gitindex.%s' % gitpath)
        except KeyError:
            return Response(status=404, body='Unknown git path')
        response = urllib.urlopen(gitindex)
        index = response.read()
        index = [x.strip('\r\n ').split(' ')[0].rsplit('.')[0] for x in index.split('\n') if x.strip('\r\n ')]
        return Response(status=200, body=dumps(index))

class TarballHandler(RequestHandler):
    def get(self, buildid):
        builddir = os.path.join(conf('buildbot.buildpath'), buildid)
        if not os.path.exists(builddir):
            return Response(status=404, body='The build ID does not exist.\n')

        tarpath = os.path.join(builddir, 'package.tar.gz')
        if not os.path.exists(tarpath):
            return Response(status=400, body='The build is not done yet.\n')
        else:
            fd = file(tarpath, 'rb')
            data = fd.read()
            fd.close()
            return Response(status=200, body=data, content_type='application/x-tar-gz')

class StatusHandler(RequestHandler):
    def get(self, buildid):
        builddir = os.path.join(conf('buildbot.buildpath'), buildid)
        if not os.path.exists(builddir):
            return Response(status=404, body='The build ID does not exist.\n')

        try:
            log = file('%s/build.log' % builddir, 'r').read()
        except:
            log = ''
        if not os.path.exists(builddir + '/package.tar.gz'):
            return Response(status=400, body='The build is not done yet.\n' + log)
        else:
            return Response(status=200, body='Build complete.\n' + log)

class BuildTask(object):
    def __init__(self, gitpath, gitref, environment, callbacks=[], submodules=False):
        self.gitpath = gitpath
        self.gitref = gitref
        self.environment = environment
        self.callbacks = callbacks
        self.submodules = submodules
        self.id = uuid.uuid4().hex
        self.status = 'init'

        self.tmpdir = os.path.join(conf('buildbot.buildpath'), self.id)
        self.resultsdir = os.path.join(self.tmpdir, '.build_results')
        os.makedirs(self.resultsdir)

        self.setup()

    def set_status(self, status):
        self.log('Build status: %s -> %s' % (self.status, status))
        self.status = status

    def log(self, msg):
        sys.stderr.write('%s: %s\n' % (self.id, msg))
        sys.stderr.flush()

    def setup(self):
        self.repo = GitRepository(tmpdir)

        try:
            pbuilderrc = conf('buildbot.environments.%s' % environment)
        except KeyError:
            self.log('No pbuilderrc defined for environment %s, using stable' % environment)
            pbuilderrc = conf('buildbot.environments.stable')

        self.set_status('git clone')
        output, retcode = repo.clone(gitpath)
        if retcode:
            self.log('Unable to clone %s. %s\n' % (gitpath, '\n'.join(output)))
            return

        self.set_status('git checkout')
        output, retcode = repo.checkout(ref)
        if retcode:
            self.log('Unable to checkout %s. %s\n' % (ref, '\n'.join(output)))
            return

        if submodules:
            self.set_status('git submodule')
            output, retcode = repo.submodule_init()
            output, retcode = repo.submodule_update()
            self.log('Updated submodules')

        self.set_status('setup done')

    def build(self):
        proc = repo.build(conf('buildbot.signkey'), pbuilderrc, resultsdir)
        self.set_status('building')
        for line in proc.stdout.readlines():
            self.log(line)
        retcode = proc.wait()
        self.set_status('build done')

        upload_results()

    def upload_results(self):
        os.chdir(resultsdir)
        if not os.listdir(resultsdir) or retcode != 0:
            self.log('Nothing in results directory. Giving up.')
            return

        self.set_status('make tarball')
        tarpath = os.path.join(tmpdir, 'package.tar.gz')
        tar = tarfile.open(tarpath, 'w:gz')
        for name in os.listdir(resultsdir):
            tar.add(name)
        tar.close()

        self.log('Build complete. Results in %s\n' % tarpath)

        self.set_status('upload callback')
        for url in self.callbacks:
            if not url.startswith('http://'):
                url = urljoin('http://127.0.0.1:%i/' % conf('server.bind_port'), url)
            try:
                self.log('Performing callback: %s' % url)
                datagen, headers = multipart_encode({'package': open(tarpath, 'rb')})
                req = Request(url, datagen, headers)
                response = urlopen(req).read()
            except:
                self.log('Callback to %s failed: %s' % (url, format_exc()))
                continue
        self.set_status('upload finished')

class BuildWorker(Thread):
    def __init__(self, queue):
        Thread.__init__(self)
        self.queue = queue

    def run(self):
        while True:
            task = self.queue.get()
            try:
                task.build()
            except:
                sys.stderr.write('task.build() threw an exception!\n%s\n' % format_exc())
