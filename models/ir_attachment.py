# -*- coding: utf-8 -*-
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models, fields

import boto3
import botocore
from botocore.exceptions import ClientError
import base64
import logging
import re
import os

from awscli.clidriver import create_clidriver

_logger = logging.getLogger(__name__)


class S3Attachment(models.Model):
    """Extends ir.attachment to implement the S3 storage engine
    """
    _inherit = "ir.attachment"
    _s3_bucket = False

    s3_key = fields.Char('S3 Key', index=True)
    s3_url = fields.Char('S3 Url', index=True, size=1024)
    s3_lost = fields.Boolean('S3 Not Found')

    def _parse_storage_url(self, bucket_url):
        scheme = bucket_url[:5]
        assert scheme == 's3://', \
            "Expecting an s3:// scheme, got {} instead.".format(scheme)
        try:
            remain = bucket_url.lstrip(scheme)
            access_type = remain.split(':')[0]
            remain = remain.lstrip(access_type).lstrip(':')
            profile_name = remain.split('@')[0]
            bucket_name = remain.split('@')[1]
            if not access_type or not profile_name:
                raise Exception(
                    "AWS profile and bucket not provided."
                    " Unable to establish a connexion to S3.")
        except Exception:
            raise Exception("Unable to parse the S3 bucket url.")
        return scheme, access_type, profile_name, bucket_name

    def _connect_to_S3_bucket(self, bucket_url):
        scheme, access_type, profile_name, bucket_name = self._parse_storage_url(bucket_url)
        if access_type == 'profile':
            session = boto3.session.Session(profile_name=profile_name)
            s3_conn = session.resource('s3')

        # Get bucket or create one
        s3_bucket = s3_conn.Bucket(bucket_name)
        exists = True
        try:
            s3_conn.meta.client.head_bucket(Bucket=bucket_name)
        except botocore.exceptions.ClientError as e:
            error_code = int(e.response['Error']['Code'])
            if error_code == 404:
                exists = False

        if not exists:
            s3_bucket.create_bucket(Bucket=bucket_name)

        return s3_bucket

    @api.model
    def _s3_key_from_fname(self, path):
        # sanitize path
        db_name = self.env.registry.db_name
        path = re.sub('[.]', '', path)
        path = path.strip('/\\')
        return '/'.join([db_name, path])

    @api.model
    def _get_s3_key(self, bin_data, sha):
        # scatter files across 256 dirs
        # we use '/' in the db (even on windows)
        db_name = self.env.registry.db_name
        fname = sha[:2] + '/' + sha
        return '/'.join([db_name, fname])

    @api.multi
    def _file_read(self, fname, bin_size=False):
        storage = self._storage()
        r = ''
        if storage[:5] == 's3://':
            for attachment in self:
                try:
                    if not self._s3_bucket:
                        self._s3_bucket = self._connect_to_S3_bucket(storage)
                except Exception:
                    _logger.error('S3: _file_read Was not able to connect (%s), gonna try other filestore', storage)
                    return super(S3Attachment, self)._file_read(fname=fname, bin_size=bin_size)

                key = self._s3_key_from_fname(fname)
                try:
                    s3_key = self._s3_bucket.Object(key)
                    r = base64.b64encode(s3_key.get()['Body'].read())
                    if not attachment.s3_key:
                        attachment.s3_key = s3_key.key
                        attachment.s3_url = '%s/%s/%s' % (
                        s3_key.meta.client.meta.endpoint_url, s3_key.bucket_name, s3_key.key)
                        _logger.debug('S3: _file_read updated s3_url for key:%s', key)

                    _logger.debug('S3: _file_read read key:%s from bucket successfully', key)
                except Exception:
                    _logger.error('S3: _file_read was not able to read from S3 or other filestore key:%s', key)
                    attachment.s3_lost = True
                    # Only try filesystem if the not copied to S3
                    if not self.env['ir.config_parameter'].sudo().get_param('ir_attachment.location_s3_copied_to', False):
                        r = super(S3Attachment, self)._file_read(fname, bin_size=bin_size)
        else:
            # storage is not as s3 type
            r = super(S3Attachment, self)._file_read(fname, bin_size=bin_size)
        return r

    @api.multi
    def _file_write(self, value, checksum):
        storage = self._storage()
        if storage[:5] == 's3://':
            for attachment in self:
                try:
                    if not self._s3_bucket:
                        self._s3_bucket = self._connect_to_S3_bucket(storage)
                except Exception:
                    _logger.error('S3: _file_write was not able to connect (%s), gonna try other filestore', storage)
                    return super(S3Attachment, self)._file_write(value, checksum)
                bin_value = value.decode('base64')
                fname, full_path = self._get_path(bin_value, checksum)
                key = self._get_s3_key(bin_value, checksum)

                try:
                    s3_key = self._s3_bucket.Object(key)
                    metadata = {
                        'name': self.name or '',
                        'res_id': str(self.res_id) or '',
                        'res_model': self.res_model or '',
                        'description': self.description or '',
                        'create_date': str(self.create_date or '')
                    }
                    s3_key.put(Body=bin_value, Metadata=metadata)
                    # Storing this info because can be usefull for later having public urls for assets
                    if not attachment.s3_key:
                        attachment.s3_url = '%s/%s/%s' % (s3_key.meta.client.meta.endpoint_url , s3_key.bucket_name, s3_key.key)
                        attachment.s3_key = s3_key.key
                    _logger.debug('S3: _file_write  key:%s was successfully uploaded', key)
                except Exception:
                    _logger.error('S3: _file_write was not able to write, gonna try other filestore key:%s', key)
                    # Only try filesystem if the not copied to S3
                    if not self.env['ir.config_parameter'].sudo().get_param('ir_attachment.location_s3_copied_to', False):
                        return super(S3Attachment, self)._file_write(value, checksum)
        else:
            _logger.debug('S3: _file_write bypass to filesystem storage: %s', storage)
            return super(S3Attachment, self)._file_write(value, checksum)

        # Returning the file name
        return fname

    @api.model
    def _file_gc_s3(self):
        storage = self._storage()
        if storage[:5] != 's3://':
            return

        try:
            if not self._s3_bucket:
                self._s3_bucket = self._connect_to_S3_bucket(storage)
            _logger.debug('S3: _file_gc_s3 connected Sucessfuly (%s)', storage)
        except Exception:
            _logger.error('S3: _file_gc_s3 was not able to connect (%s)', storage)
            return False

        # Continue in a new transaction. The LOCK statement below must be the
        # first one in the current transaction, otherwise the database snapshot
        # used by it may not contain the most recent changes made to the table
        # ir_attachment! Indeed, if concurrent transactions create attachments,
        # the LOCK statement will wait until those concurrent transactions end.
        # But this transaction will not see the new attachements if it has done
        # other requests before the LOCK (like the method _storage() above).
        cr = self._cr
        cr.commit()

        # prevent all concurrent updates on ir_attachment while collecting!
        cr.execute("LOCK ir_attachment IN SHARE MODE")

        try:
            # retrieve the file names from the checklist
            checklist = {}
            for s3_key_gc in self._s3_bucket.objects.filter(Prefix=self._s3_key_from_fname('checklist')):
                real_key_name = self._s3_key_from_fname(s3_key_gc.key[1 + len(self._s3_key_from_fname('checklist/')):])
                checklist[real_key_name] = s3_key_gc.key

            # determine which files to keep among the checklist
            whitelist = set()
            for names in cr.split_for_in_conditions(checklist):
                cr.execute("SELECT store_fname FROM ir_attachment WHERE store_fname IN %s", [names])
                whitelist.update(row[0] for row in cr.fetchall())

            # remove garbage files, and clean up checklist
            removed = 0
            for real_key_name, check_key_name in checklist.iteritems():
                if real_key_name not in whitelist:
                    # Get the real key from the bucket
                    s3_key = self._s3_bucket.Object(real_key_name)
                    new_key = self._s3_key_from_fname('trash/%s' % real_key_name)
                    trashed_key = self._s3_bucket.Object(new_key).copy_from(
                        CopySource={'Bucket': self._s3_bucket.name, 'Key': real_key_name})
                    s3_key.delete()
                    s3_key_gc = self._s3_bucket.Object(check_key_name)
                    s3_key_gc.delete()
                    removed += 1
                    _logger.debug('S3: _file_gc_s3 deleted key:%s successfully', real_key_name)

        except ClientError as ex:
            _logger.error('S3: _file_gc_s3 (key:%s) (checklist_key:%s) %s:%s', real_key_name, check_key_name,
                          ex.response['Error']['Code'], ex.response['Error']['Message'])

        except Exception as ex:
            _logger.error('S3: _file_gc_s3 was not able to gc (key:%s) (checklist_key:%s)', real_key_name, check_key_name)

        # commit to release the lock
        cr.commit()
        _logger.info("S3: filestore gc %d checked, %d removed", len(checklist), removed)

    def _mark_for_gc(self, fname):
        """ We will mark for garbage collection in both s3 and filesystem
        Just the garbage collection in s3 will move to trash and not delete"""
        storage = self._storage()
        if storage[:5] == 's3://':
            try:
                if not self._s3_bucket:
                    self._s3_bucket = self._connect_to_S3_bucket(storage)
                _logger.debug('S3: File mark as gc. Connected Sucessfuly (%s)', storage)
            except Exception:
                _logger.error('S3: File mark as gc. Was not able to connect (%s), gonna try other filestore', storage)
                # Only try filesystem if the not copied to S3
                if not self.env['ir.config_parameter'].sudo().get_param('ir_attachment.location_s3_copied_to', False):
                    return super(S3Attachment, self)._mark_for_gc(fname)

            new_key = self._s3_key_from_fname('checklist/%s' % fname)

            try:
                s3_key = self._s3_bucket.Object(new_key)
                # Just create an empty file to
                s3_key.put(Body='')
                _logger.debug('S3: _mark_for_gc key:%s marked for garbage collection', new_key)
            except Exception:
                _logger.error('S3: _mark_for_gc Was not able to save key:%s', new_key)
                # Only try filesystem if the not copied to S3
                if not self.env['ir.config_parameter'].sudo().get_param('ir_attachment.location_s3_copied_to', False):
                    return super(S3Attachment, self)._mark_for_gc(fname)
        else:
            # if other storage type
            return super(S3Attachment, self)._mark_for_gc(fname)

    def aws_cli(*cmd):
        old_env = dict(os.environ)
        try:

            # Environment
            env = os.environ.copy()
            env['LC_CTYPE'] = u'en_US.UTF'
            os.environ.update(env)
            # Run awscli in the same process
            exit_code = create_clidriver().main(cmd[1:])

            # Deal with problems
            if exit_code > 0:
                raise RuntimeError('AWS CLI exited with code {}'.format(exit_code))
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def _copy_filestore_to_s3(self):
        with api.Environment.manage():
            try:
                self._run_copy_filestore_to_s3()
                _logger.info('S3: filestore copied to S3 successfully')
            except Exception:
                _logger.info('S3: filestore copy to S3 aborted!')
            return {}

    @api.model
    def _run_copy_filestore_to_s3(self):
        storage = self._storage()
        is_copied = self.env['ir.config_parameter'].sudo().get_param('ir_attachment.location_s3_copied_to', False)
        scheme, access_type, profile_name, bucket_name = self._parse_storage_url(storage)
        if scheme == 's3://' and not is_copied:
            db_name = self.env.registry.db_name
            s3_url = 's3://%s/%s' % (bucket_name, db_name)
            full_path = self._full_path('')
            self.aws_cli('s3', 'cp', '--profile', profile_name, '--recursive', full_path, s3_url)
            self.env['ir.config_parameter'].sudo().set_param('ir_attachment.location_s3_copied_to', '%' % s3_url,
                                                             groups=['base.group_system'])
