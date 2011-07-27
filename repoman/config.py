import logging
import logging.config

import os.path
import sys

try:
    import json
except ImportError:
    import simplejson as json

config = None

def set_log_conf(logging_conf):
    logging.config.fileConfig(logging_conf)

def set_web_conf(web_conf):
    """"""
    global config  # lulz
    if os.path.exists(web_conf):
        config = json.load(file(web_conf, 'r'))

    if not config:
        logging.critical('Unable to load config file. Exiting.')
        sys.exit(0)

def conf(key):
    if config is None:
        logging.critical('Config not loaded. Exiting.')
        sys.exit(0)

    obj = config
    for k in key.split('.'):
        obj = obj[k]
    return obj
