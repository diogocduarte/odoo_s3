# -*- coding: utf-8 -*-

from odoo import api, models

import boto
import base64
import logging
import re


_logger = logging.getLogger(__name__)


class S3Attachment(models.Model):
    """Extends ir.attachment to implement the S3 storage engine
    """
    _inherit = "ir.attachment"
    _s3_bucket = False

    def _connect_to_S3_bucket(self, bucket_url):
        # Parse the bucket url
        scheme = bucket_url[:5]
        assert scheme == 's3://', \
            "Expecting an s3:// scheme, got {} instead.".format(scheme)

        try:
            remain = bucket_url.lstrip(scheme)
            access_key_id = remain.split(':')[0]
            remain = remain.lstrip(access_key_id).lstrip(':')
            secret_key = remain.split('@')[0]
            bucket_name = remain.split('@')[1]
            if not access_key_id or not secret_key:
                raise Exception(
                    "No AWS access and secret keys were provided."
                    " Unable to establish a connexion to S3."
                )
        except Exception:
            raise Exception("Unable to parse the S3 bucket url.")

        if access_key_id == 'profile':
            s3_conn = boto.connect_s3(profile_name=secret_key)
        else:
            s3_conn = boto.connect_s3(access_key_id, secret_key)

        s3_bucket = s3_conn.lookup(bucket_name)

        if not s3_bucket:
            # If the bucket does not exist, create a new one
            s3_bucket = s3_conn.create_bucket(bucket_name)
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

    @api.model
    def _file_read(self, fname, bin_size=False):
        storage = self._storage()
        r = ''
        if storage[:5] == 's3://':
            try:
                if not self._s3_bucket:
                    self._s3_bucket = self._connect_to_S3_bucket(storage)
            except Exception:
                _logger.error('S3: _file_read Was not able to connect (%s), gonna try other filestore', storage)
                return super(S3Attachment, self)._file_read(fname=fname, bin_size=bin_size)

            key = self._s3_key_from_fname(fname)
            try:
                s3_key = self._s3_bucket.get_key(key)
                r = base64.b64encode(s3_key.get_contents_as_string())
                _logger.debug('S3: _file_read read key:%s from bucket successfully', key)
                print "read s3 ", fname
            except Exception:
                _logger.error('S3: _file_read was not able to read from S3 or other filestore key:%s', key)
                r = super(S3Attachment, self)._file_read(fname, bin_size=bin_size)
        else:
            # storage is not as s3 type
            r = super(S3Attachment, self)._file_read(fname, bin_size=bin_size)
        return r

    @api.model
    def _file_write(self, value, checksum):
        storage = self._storage()
        if storage[:5] == 's3://':
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
                s3_key = self._s3_bucket.get_key(key)
                s3_key.set_metadata('name', self.name)
                s3_key.set_metadata('resid', self.res_id)
                s3_key.set_metadata('resmodel', self.res_model)
                s3_key.set_metadata('description', self.description)
                s3_key.set_metadata('createdate', self.create_date)
            except Exception:
                _logger.error('S3: _file_write was not able tag key:%s', key)



            # use the same format as Odoo in case we need to mount it back
            try:
                s3_key = self._s3_bucket.get_key(key)
                if not s3_key:
                    s3_key = self._s3_bucket.new_key(key)
                    _logger.debug('S3: _file_write created new content key:%s', key)
                else:
                    _logger.debug('S3: _file_write updating key:%s content', key)

                s3_key.set_contents_from_string(bin_value)
            except Exception:
                _logger.error('S3: _file_write was not able to write, gonna try other filestore key:%s', key)
                return super(S3Attachment, self)._file_write(value, checksum)
        else:
            _logger.debug('S3: _file_write bypass to filesystem storage: %s', storage)
            return super(S3Attachment, self)._file_write(value, checksum)

        # Returning the file name
        return fname

    @api.model
    def _file_gc_s3(self):
        storage = self._storage()
        if storage[:5] == 's3://':
            try:
                if not self._s3_bucket:
                    self._s3_bucket = self._connect_to_S3_bucket(storage)
                _logger.debug('S3: _file_gc_s3 connected Sucessfuly (%s)', storage)
            except Exception:
                _logger.error('S3: _file_gc_s3 was not able to connect (%s)', storage)
                return False

            try:
                for s3_key_gc in self._s3_bucket.list(prefix=self._s3_key_from_fname('checklist')):
                    real_key_name = self._s3_key_from_fname(s3_key_gc.key[1 + len(self._s3_key_from_fname('checklist/')):])

                    s3_key = self._s3_bucket.get_key(real_key_name)
                    if s3_key:
                        new_key = self._s3_key_from_fname('trash/%s' % real_key_name)
                        s3_key.copy(self._s3_bucket.name, new_key)
                        s3_key.delete()
                        s3_key_gc.delete()
                        _logger.debug('S3: _file_gc_s3 deleted key:%s successfully', real_key_name)
            except Exception:
                _logger.error('S3: _file_gc_s3 was not able move to gc/trash key:%s', real_key_name)
                return False
        else:
            # storage is not as s3 type
            return True

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
                return super(S3Attachment, self)._mark_for_gc(fname)

            new_key = self._s3_key_from_fname('checklist/%s' % fname)

            try:
                s3_key = self._s3_bucket.new_key(new_key)
                # Just create an empty file to
                s3_key.set_contents_from_string('')
                _logger.debug('S3: _mark_for_gc key:%s marked for garbage collection', new_key)
            except Exception:
                _logger.error('S3: _mark_for_gc Was not able to save key:%s', new_key)
                return super(S3Attachment, self)._mark_for_gc(fname)

        # Always do same in filestore anyway
        return super(S3Attachment, self)._mark_for_gc(fname)

