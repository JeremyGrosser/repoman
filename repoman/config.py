import logging
import logging.config
logging.config.fileConfig('/etc/repoman/logging.conf')

try:
    import json
except ImportError:
    import simplejson as json

config = json.load(file('/etc/repoman/web.conf', 'r'))

def conf(key):
    obj = config
    for k in key.split('.'):
        obj = obj[k]
    return obj
