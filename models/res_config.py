from openerp import models, fields, api, _
from odoo.exceptions import AccessError

import logging

_logger = logging.getLogger(__name__)


class S3ResConfig(models.TransientModel):
    _inherit = 'res.config.settings'

    s3_profile = fields.Char('AWS Profile')
    s3_bucket = fields.Char('Bucket Name')
    s3_load = fields.Boolean(
        'Load S3 with existing filestore?',
        help="If you check this option, when you apply"
    )

    @api.model
    def get_values(self):
        res = super(S3ResConfig, self).get_values()
        ir_attachment = self.env['ir.attachment'].sudo().browse()
        storage = ir_attachment._storage()
        if storage[:5] == 's3://':
            part, s3_bucket = storage.split('@')
            part, part1, s3_profile = part.split(':')
            res.update(s3_profile=s3_profile, s3_bucket=s3_bucket)
        return res

    def set_values(self):
        super(S3ResConfig, self).set_values()
        ir_attachment = self.env['ir.attachment'].browse()
        storage = "s3://profile:{s3_profile}@{s3_bucket}".format(s3_profile=self.s3_profile, s3_bucket=self.s3_bucket)

        try:
            s3_bucket = ir_attachment._connect_to_S3_bucket(storage)
            self.env['ir.config_parameter'].sudo().set_param('ir_attachment.location', storage)
            if self.s3_load:
                self.env['ir.attachment'].sudo()._copy_filestore_to_s3()

        except Exception as e:
            raise AccessError(
                _('Error accessing the bucket \"{}\" through the aws profile \"{}\".').forma(
                self.s3_bucket, self.s3_profile))

    @api.multi
    def test_move_filestore_to_s3(self):
        for wiz in self:
            ir_attachment = self.env['ir.attachment'].browse()
            storage = "s3://profile:{s3_profile}@{s3_bucket}".format(s3_profile=wiz.s3_profile, s3_bucket=wiz.s3_bucket)
            try:
                s3_bucket = ir_attachment._connect_to_S3_bucket(storage)
                _logger.info("S3 bucket connection successful {}".format(s3_bucket.name))
            except Exception as e:
                raise AccessError(
                    _('Error accessing the bucket "{}" through the aws profile "{}".\n'
                      'Please fix the "AWS S3 Storage" settings').format(wiz.s3_bucket, wiz.s3_profile))


