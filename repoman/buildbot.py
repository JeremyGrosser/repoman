from ncore.serialize import dumps, loads
from webob import Response
from pycurl import Curl

from subprocess import Popen, PIPE
from multiprocessing import Process, Queue
from traceback import format_exc
from time import sleep
import logging
import tarfile
import os.path
import urllib
import uuid
import sys
import os

from config import conf
from wsgi import RequestHandler

buildq = Queue()

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
            cmd = ['/usr/bin/git-buildpackage', '--git-sign', '--git-cleaner="fakeroot debian/rules clean"', '--git-keyid="%s"' % signkey, '--git-builder="pdebuild --debsign-k %s --auto-debsign --configfile %s --debbuildopts "-i.git -sa" --buildresult %s' % (signkey, pbuilderrc, resultsdir)]
        else:
            cmd = ['/usr/bin/pdebuild', '--debsign-k', signkey, '--auto-debsign', '--debbuildopts', '-i.git -sa', '--configfile', pbuilderrc, '--buildresult', resultsdir]
        return self._cmd(cmd)

class PackageHandler(RequestHandler):
    def get(self, gitpath, gitrepo):
        gitpath = os.path.join(conf('buildbot.gitpath.%s' % gitpath), gitrepo)

        repo = GitRepository()
        refs = repo.ls_remote(gitpath)
        return Response(status=200, body=dumps(self.request.params, refs))

    def post(self, gitpath, gitrepo):
        if not 'ref' in self.request.params:
            return Response(status=400, body='Required parameter "ref" is missing. You must pass a git tag, branch, or commit ID to be built.\n')

        gitpath = os.path.join(conf('buildbot.gitpath.%s' % gitpath), gitrepo)
        ref = self.request.params['ref']
        cburl = self.request.params.get('cburl', None)
        submodules = self.request.params.get('submodules', None)

        buildid = uuid.uuid4().hex

        buildq.put((gitpath, ref, buildid, cburl, submodules))
        return Response(status=200, body=buildid + '\n')

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

        if not os.path.exists(builddir + '/package.tar.gz'):
            return Response(status=400, body='The build is not done yet.\n')
        else:
            return Response(status=200, body='Build complete.\n')

def build_thread(gitpath, ref, buildid, cburl=None, submodules=False):
    tmpdir = os.path.join(conf('buildbot.buildpath'), buildid)
    repo = GitRepository(tmpdir)

    output, retcode = repo.clone(gitpath)
    if retcode:
        logging.warning('Unable to clone %s. %s\n' % (gitpath, '\n'.join(output)))
        return

    output, retcode = repo.checkout(ref)
    if retcode:
        logging.warning('Unable to checkout %s. %s\n' % (ref, '\n'.join(output)))
        return

    if submodules:
        output, retcode = repo.submodule_init()
        output, retcode = repo.submodule_update()

    resultsdir = os.path.join(tmpdir, '.build_results')
    os.makedirs(resultsdir)
    output, retcode = repo.build(conf('buildbot.signkey'), conf('buildbot.pbuilderrc'), resultsdir)

    #logging.debug(output[0])
    #logging.debug(output[1])

    os.chdir(resultsdir)
    if not os.listdir(resultsdir) or retcode != 0:
        logging.warning('Nothing in results directory.')

    tarpath = os.path.join(tmpdir, 'package.tar.gz')
    tar = tarfile.open(tarpath, 'w:gz')
    for name in os.listdir(resultsdir):
        tar.add(name)
    tar.close()

    logging.info('Build complete. Results in %s\n' % tarpath)
    data = file(tarpath, 'rb').read()
    logging.info('Built %i byte tarball' % len(data))

    if cburl:
        logging.info('Performing callback: %s' % cburl)
        req = Curl()
        req.setopt(req.POST, 1)
        req.setopt(req.URL, cburl)
        req.setopt(req.HTTPPOST, [('package', (req.FORM_FILE, str(tarpath)))])
        req.perform()
        req.close()

def build_worker():
    logging.info('Build worker process now running, pid %i' % os.getpid())
    while True:
        try:
            job = buildq.get()
            print 'jobspec:', repr(job)
            build_thread(*job)
        except:
            logging.warning('Build worker caught exception: %s' % format_exc())
p = Process(target=build_worker)
p.start()
