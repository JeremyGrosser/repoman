import logging
import logging.config
logging.config.fileConfig('/etc/repoman/logging.conf')

import os.path
import sys

try:
    import json
except ImportError:
    import simplejson as json

config = None
for filename in ('web.conf', '/etc/repoman/web.conf'):
    if os.path.exists(filename):
        config = json.load(file(filename, 'r'))
        break

if not config:
    logging.critical('Unable to load a config file. Exiting.')
    sys.exit(0)

def conf(key):
    obj = config

    for k in key.split('.'):
        obj = obj[k]
    return obj
