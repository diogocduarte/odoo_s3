# -*- coding: utf-8 -*-

from odoo import api, models


class AutoVacuum(models.AbstractModel):
    _inherit = 'ir.autovacuum'

    @api.model
    def power_on(self, *args, **kwargs):
        print "--------------------- S3 GC"
        self.env['ir.attachment']._file_gc_s3()
        return super(AutoVacuum, self).power_on(*args, **kwargs)
