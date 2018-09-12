# -*- coding: utf-8 -*-
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from . import models


def _copy_filestore_to_s3(cr, registry):
    from odoo.addons.odoo_s3.models.ir_autovacuum import copy_filestore_to_s3
    copy_filestore_to_s3(cr, registry)
