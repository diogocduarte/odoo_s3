# -*- coding: utf-8 -*-

from . import models


def _copy_filestore_to_s3(cr, registry):
    from odoo.addons.odoo_s3.models.ir_autovacuum import copy_filestore_to_s3
    copy_filestore_to_s3(cr, registry)
