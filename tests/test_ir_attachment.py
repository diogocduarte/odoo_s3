# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib
import os
import logging
import boto3
import botocore
from botocore.exceptions import ClientError

from odoo.tests.common import TransactionCase


_logger = logging.getLogger(__name__)

HASH_SPLIT = 2      # FIXME: testing implementations detail is not a good idea


class TestIrAttachment(TransactionCase):
    def setUp(self):
        super(TestIrAttachment, self).setUp()
        self.Attachment = self.env['ir.attachment']
        self.filestore = self.Attachment._filestore()

        # Blob1
        self.blob1 = 'blob1'
        self.blob1_b64 = self.blob1.encode('base64')
        blob1_hash = hashlib.sha1(self.blob1).hexdigest()
        self.blob1_fname = blob1_hash[:HASH_SPLIT] + '/' + blob1_hash

        # Blob2
        self.blob2 = 'blob2'
        self.blob2_b64 = self.blob2.encode('base64')

        self.storage = self.env['ir.attachment']._storage()
        self._s3_bucket = self.env['ir.attachment']._connect_to_S3_bucket(self.storage)

    def test_01_store_in_s3(self):
        # force storing in s3
        self.env['ir.config_parameter'].set_param('ir_attachment.location', 's3://profile:default@testodoofs1')

        # 'ir_attachment.location' is undefined test database storage
        a1 = self.Attachment.create({'name': 'a1', 'datas': self.blob1_b64})
        self.assertEqual('%s\n' % a1.datas, self.blob1_b64, 'The body of the attachment is different for key:%s' % self.blob1_fname)

        a1_db_datas = a1.db_datas
        self.assertEqual(a1_db_datas, None)


    def test_02_no_duplication(self):
        a2 = self.Attachment.create({'name': 'a2', 'datas': self.blob1_b64})
        a3 = self.Attachment.create({'name': 'a3', 'datas': self.blob1_b64})
        self.assertEqual(a3.store_fname, a2.store_fname)

    def test_03_check_s3key(self):
        a2 = self.Attachment.create({'name': 'a2', 'datas': self.blob1_b64})
        key = self.env['ir.attachment']._s3_key_from_fname(a2.store_fname)
        s3_key = self._s3_bucket.Object(key)
        self.assertEqual(s3_key.content_type, 'binary/octet-stream', 'Error getting the key:%s' % key)
        self.assertEqual(s3_key.metadata['name'], 'a2', 'Error getting the metadata for key:%s' % key)
