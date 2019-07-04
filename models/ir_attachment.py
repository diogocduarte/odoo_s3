# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models, fields

import boto3
import botocore
from botocore.exceptions import ClientError
import base64
import logging
import re
import os

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
            region = session.region_name
        else:
            raise NotImplemented

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
            location = {'LocationConstraint': region}
            s3_conn.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration=location
            )
        return s3_bucket

    def _s3_key_from_fname(self, store_fname):
        db_name = self.env.registry.db_name
        store_fname = re.sub('[.]', '', store_fname)
        store_fname = store_fname.strip('/\\')
        return '/'.join([db_name, store_fname])

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
                _logger.error('S3: _file_read Was not able to connect ({}), '
                              'gonna try other filestore'.format(storage))
                return super(S3Attachment, self)._file_read(fname=fname, bin_size=bin_size)

            # It's not a @multi but i always use a for instead of an if exists because makes it easy to switch to multi
            for attachment in self:
                key = self._s3_key_from_fname(fname)
                try:
                    # Try reading this key
                    s3_key = self._s3_bucket.Object(key)
                    r = base64.b64encode(s3_key.get()['Body'].read())
                    # Set the field s3_key on the attachment, if not there already
                    if not attachment.s3_key:
                        attachment.s3_key = s3_key.key
                        attachment.s3_url = '{}/{}/{}'.format(
                            s3_key.meta.client.meta.endpoint_url, s3_key.bucket_name, s3_key.key)
                        _logger.debug('S3: _file_read updated s3_url for key:{}'.format(key))

                    _logger.debug('S3: _file_read read key:{} from bucket successfully'.format(key))

                except Exception:
                    _logger.error('S3: _file_read was not able to read from S3 or other filestore'
                                  ' key:{}'.format(key))
                    # Check the trash
                    try:
                        trash_key_list = key.split('/')
                        trash_key_list.insert(1, 'trash')
                        trash_key = '/'.join(trash_key_list)
                        # Try reading trash key
                        s3_trash_key = self._s3_bucket.Object(trash_key)
                        r = base64.b64encode(s3_trash_key.get()['Body'].read())
                        _logger.debug('S3: _file_read read key:{} from bucket trash bin'.format(
                            s3_trash_key))
                        # Restore the file
                        self._s3_bucket.Object(key).copy_from(CopySource='{}/{}'.format(
                            s3_trash_key.bucket_name, s3_trash_key.key))
                        s3_trash_key.delete()
                        _logger.debug('S3: _file_read --::-- restored the key:{} from bucket'
                                      ' trash bin key {}'.format(s3_trash_key.key, key))

                    except Exception:
                        _logger.error('S3: _file_read also not able to find in trash the key: '
                                      '{}'.format(key))

                    attachment.s3_lost = True
                    # Only try filesystem if the not copied to S3
                    if not self.env['ir.config_parameter'].sudo().get_param(
                            'ir_attachment.location_s3_copied_to', False):
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
                _logger.error('S3: _file_write was not able to connect ({}), '
                              'gonna try other filestore'.format(storage))
                return super(S3Attachment, self)._file_write(value, checksum)

            for attachment in self:
                bin_value = base64.b64decode(value)
                fname, full_path = self._get_path(bin_value, checksum)
                key = self._get_s3_key(bin_value, checksum)

                try:
                    s3_key = self._s3_bucket.Object(key)
                    # todo: check if we can get these values from context,
                    # we do not want to change the method type, this could cause trouble with other
                    # custom apps
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
                        attachment.s3_url = '{}/{}/{}'.format(
                            s3_key.meta.client.meta.endpoint_url , s3_key.bucket_name, s3_key.key)
                        attachment.s3_key = s3_key.key
                    _logger.debug('S3: _file_write  key:{} was successfully uploaded'.format(key))
                except Exception:
                    _logger.error('S3: _file_write was not able to write, gonna try other '
                                  'filestore key: {}'.format(key))
                    # Only try filesystem if the not copied to S3
                    if not self.env['ir.config_parameter'].sudo().get_param(
                            'ir_attachment.location_s3_copied_to', False):
                        return super(S3Attachment, self)._file_write(value, checksum)
        else:
            _logger.debug('S3: _file_write bypass to filesystem storage: {}'.format(storage))
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
            _logger.debug('S3: _file_gc_s3 connected Sucessfuly ({})'.format(storage))
        except Exception:
            _logger.error('S3: _file_gc_s3 was not able to connect ({})'.format(storage))
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
            for s3_key_gc in self._s3_bucket.objects.filter(
                    Prefix=self._s3_key_from_fname('checklist')):
                real_key_name = self._s3_key_from_fname(
                    s3_key_gc.key[1 + len(self._s3_key_from_fname('checklist/')):])
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

                    new_key = self._s3_key_from_fname('trash/{}'.format('/').join(
                        real_key_name.split('/')[1:]))
                    trashed_key = self._s3_bucket.Object(new_key).copy_from(
                        CopySource={'Bucket': self._s3_bucket.name, 'Key': real_key_name})
                    s3_key.delete()
                    s3_key_gc = self._s3_bucket.Object(check_key_name)
                    s3_key_gc.delete()
                    removed += 1
                    _logger.debug('S3: _file_gc_s3 deleted key:{} successfully (moved to {})'
                                  .format(real_key_name, trashed_key.key))

        except ClientError as ex:
            _logger.error('S3: _file_gc_s3 (key:{}) (checklist_key:{}) {}:{}'.format(
                real_key_name, check_key_name,
                ex.response['Error']['Code'], ex.response['Error']['Message']))

        except Exception as ex:
            _logger.error('S3: _file_gc_s3 was not able to gc (key:{}) (checklist_key:{})'.format(
                real_key_name, check_key_name))

        # commit to release the lock
        cr.commit()
        _logger.info("S3: filestore gc {} checked, {} removed".format(len(checklist), removed))

    def _mark_for_gc(self, fname):
        """ We will mark for garbage collection in both s3 and filesystem
        Just the garbage collection in s3 will move to trash and not delete"""
        storage = self._storage()
        if storage[:5] == 's3://':
            try:
                if not self._s3_bucket:
                    self._s3_bucket = self._connect_to_S3_bucket(storage)
                _logger.debug('S3: File mark as gc. Connected Sucessfuly ({})'.format(storage))
            except Exception:
                _logger.error('S3: File mark as gc. Was not able to connect ({}), '
                              'gonna try other filestore'.format(storage))
                # Only try filesystem if the not copied to S3
                if not self.env['ir.config_parameter'].sudo().get_param(
                        'ir_attachment.location_s3_copied_to', False):
                    return super(S3Attachment, self)._mark_for_gc(fname)

            new_key = self._s3_key_from_fname('checklist/{}'.format(fname))

            try:
                s3_key = self._s3_bucket.Object(new_key)
                # Just create an empty file to
                s3_key.put(Body='')
                _logger.debug('S3: _mark_for_gc key:{} marked for garbage collection'.format(
                    new_key))
            except Exception:
                _logger.error('S3: _mark_for_gc Was not able to save key:{}'.format(new_key))
                # Only try filesystem if the not copied to S3
                if not self.env['ir.config_parameter'].sudo().get_param(
                        'ir_attachment.location_s3_copied_to', False):
                    return super(S3Attachment, self)._mark_for_gc(fname)
        else:
            # if other storage type
            return super(S3Attachment, self)._mark_for_gc(fname)

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
        is_copied = self.env['ir.config_parameter'].sudo().get_param(
            'ir_attachment.location_s3_copied_to', False)
        scheme, access_type, profile_name, bucket_name = self._parse_storage_url(storage)
        if scheme == 's3://' and not is_copied:
            db_name = self.env.registry.db_name
            s3_url = 's3://{}/{}'.format(bucket_name, db_name)
            full_path = self._full_path('')
            try:
                if not self._s3_bucket:
                    self._s3_bucket = self._connect_to_S3_bucket(storage)
                _logger.debug('S3: Copy filestore to S3. Connected Sucessfuly ({})'.format(storage))
            except Exception:
                _logger.error('S3: Copy filestore to S3. Was not able to connect ({}), '
                              'gonna try other filestore'.format(storage))
            s3 = boto3.client('s3')
            db_name = os.path.basename(os.path.dirname(full_path))
            for root, dirs, files in os.walk(full_path):
                for file_name in files:
                    path = os.path.join(root, file_name)
                    bucket_name = self._s3_bucket.name
                    s3.upload_file(path, bucket_name,  '{}/{}'.format(
                        db_name, path[len(full_path):]))
                    _logger.debug('S3: Copy filestore to S3. Loading file {}/{}'.format(
                        db_name, path[len(full_path):]))
            self.env['ir.config_parameter'].sudo().set_param(
                'ir_attachment.location_s3_copied_to', '{}'.format(s3_url))

    @api.multi
    def check_s3_filestore(self):
        """This command is here for being trigger using odoo shell:

        e.g.:

        $> a, b = env['ir.attachment'].search([]).check_s3_filestore()
        $> filter(lambda x: x['s3_lost']==True, a)
        $> print b # will show totals
        $> env.cr.commit() # need to do this to update the table s3_lost field to know if something is lost

        """
        storage = self._storage()
        if storage[:5] != 's3://':
            return

        try:
            if not self._s3_bucket:
                self._s3_bucket = self._connect_to_S3_bucket(storage)
            _logger.debug('S3: _file_gc_s3 connected Sucessfuly ({})'.format(storage))
        except Exception:
            _logger.error('S3: _file_gc_s3 was not able to connect ({})'.format(storage))
            return False

        status_res = []
        totals = {
            'lost_count': 0,
        }

        for att in self:
            status = {}
            status['name'] = att.name
            status['fname'] = att.store_fname
            status['s3_lost'] = False

            try:
                if not att.store_fname:
                    raise Exception('There is no store_fname')
                key = self._s3_key_from_fname(att.store_fname)
                s3_key = self._s3_bucket.Object(key)

                # will return 404 if not exists
                chk = s3_key.content_type is False

                if not att.s3_key:
                    att.s3_key = s3_key.key
                    att.s3_url = '%s/%s/%s' % (
                        s3_key.meta.client.meta.endpoint_url, s3_key.bucket_name, s3_key.key)
                    _logger.debug('S3: check_s3_filestore updated s3_url for key:{}'.format(key))

                _logger.debug('S3: check_s3_filestore read key:{} from bucket successfully'.format(
                    key))

            except ClientError as ex:
                if int(ex.response['Error']['Code']) == 404:
                    status['s3_lost'] = True
                    totals['lost_count'] += 1

                _logger.error('S3: check_s3_filestore was not able to read from S3 or other '
                              'filestore key:{}'.format(key))
                att.s3_lost = True
                status['error'] = ex.response['Error']['Message']

            except Exception as e:
                status['error'] = e.message
            status_res.append(status)

        return status_res, totals

