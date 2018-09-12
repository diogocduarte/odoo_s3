# -*- coding: utf-8 -*-
# Copyright 2018 OdooGap, Diogo Duarte <dduarte@odoogap.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models
from odoo import SUPERUSER_ID
import threading


def copy_filestore_to_s3(cr, registry):
    ''' This is a utility function used to preserve existing previous tags during upgrade of the module.'''
    env = api.Environment(cr, SUPERUSER_ID, {})
    threaded_copy = threading.Thread(target=env['ir.attachment']._copy_filestore_to_s3(), args=())
    threaded_copy.start()
    return True

class AutoVacuum(models.AbstractModel):
    _inherit = 'ir.autovacuum'

    @api.model
    def power_on(self, *args, **kwargs):
        self.env['ir.attachment']._copy_filestore_to_s3()
        self.env['ir.attachment']._file_gc_s3()
        return super(AutoVacuum, self).power_on(*args, **kwargs)
