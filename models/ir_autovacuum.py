# Copyright 2018 OdooGap, Diogo Duarte <dduarte@odoogap.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models
from odoo import SUPERUSER_ID


class AutoVacuum(models.AbstractModel):
    _inherit = 'ir.autovacuum'

    @api.model
    def power_on(self, *args, **kwargs):
        res = super(AutoVacuum, self).power_on(*args, **kwargs)
        self.env['ir.attachment']._file_gc_s3()
        return res
