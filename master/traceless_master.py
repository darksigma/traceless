#!/usr/bin/env python
import os
from master_app import create_app, celery
from flask.ext.script import Manager

application = create_app(os.getenv('FLASK_CONFIG') or 'default')
manager = Manager(application)

if __name__ == '__main__':
    manager.run()
