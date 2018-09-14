# Odoo AWS S3 module

The basis of the module is to allow the exact same structure of the odoo filestore inside an S3 bucket. The default behaviour is always to consider the unavailabily of an S3 connection. In all cases it will default to the flesystem. This makes migrating from filestore to S3 seamless. Just install as a server wide module or even in one only database.
        
After the propper key is loaded then the server will start witing new files to S3,  if available. To migrate just use the aws cli tool and copy all files in filestore to the respective bucket, odoo will give priority to S3 bucket.

## Requirements


* awscli - v1.16.9
* boto3 - v1.8.9
* botocore - v1.11.9


```bash
$> pip install -r requirements.txt
$> aws configure
```

This last command will ask you for the ASW credentials and secret and will generate a **default** profile.

## Installation

Start the Odoo server or use an existing instance. Update modules list and install *odoo_s3* module.
Activate the developer model and find in:

* Settings >> Technical >> Parameters >> System Parameters (find **ir_attachment.location**)

The default should be loaded to: _s3://profile:default@testodoofs1_

After you set the correct parameters Odoo will start saving new attachments to AWS S3 but the existing ones will stay in the filesystem until you run the auto vacuum scheduler.
In order for ODoo to copy the filestore you need to open:

* Settings >> Technical >> Automation >> Scheduled Actions (find **Auto-vacuum internal data**)

Press run manually and Odoo will copy all files to S3 in a separated thread.

Also recommend using on your odoo.conf file on server wide modules:

```bash
server_wide_modules = odoo_s3,web,web_kanban
```

## Maintenance

To check what is the status of the filestore we can run a toll in Odoo shell environment:

```bash
IPython 5.6.0 -- An enhanced Interactive Python.
?         -> Introduction and overview of IPython's features.
%quickref -> Quick reference.
help      -> Python's own help system.
object?   -> Details about 'object', use 'object??' for extra details.

In [1]: res_list, totals = env['ir.attachment'].search([]).check_s3_filestore()
2018-09-12 14:41:10,962 3522 INFO v10_odoo_s3 botocore.credentials: Found credentials in shared credentials file: ~/.aws/credentials
2018-09-12 14:41:17,167 3522 ERROR v10_odoo_s3 odoo.addons.odoo_s3.models.ir_attachment: S3: _file_read was not able to read from S3 or other filestore key:v10_odoo_s3/91/91c1ab69ca4a6c3c5e9c32187cb975d19b194b93
2018-09-12 14:41:29,978 3522 ERROR v10_odoo_s3 odoo.addons.odoo_s3.models.ir_attachment: S3: _file_read was not able to read from S3 or other filestore key:v10_odoo_s3/6b/6bc87910870d5ec831c3adbf4df22c5bbed1fe31
2018-09-12 14:41:30,375 3522 ERROR v10_odoo_s3 odoo.addons.odoo_s3.models.ir_attachment: S3: _file_read was not able to read from S3 or other filestore key:v10_odoo_s3/cc/ccd41799069ae21b845f931369eca4f9fdc76ba5
2018-09-12 14:41:30,682 3522 ERROR v10_odoo_s3 odoo.addons.odoo_s3.models.ir_attachment: S3: _file_read was not able to read from S3 or other filestore key:v10_odoo_s3/4f/4f21892e89f55600f30723c55094ac8658a48bab

In [2]: totals
Out[2]: {'lost_count': 4}

In [3]: filter(lambda x: x['s3_lost']==True, res_list)
Out[3]: 
[{'error': 'Not Found',
  'fname': u'91/91c1ab69ca4a6c3c5e9c32187cb975d19b194b93',
  'name': u'/mail/static/src/less/web.assets_backend/followers.less.css',
  's3_lost': True},
 {'error': 'Not Found',
  'fname': u'6b/6bc87910870d5ec831c3adbf4df22c5bbed1fe31',
  'name': u'Screenshot-20180904222459-481x628.png',
  's3_lost': True},
 {'error': 'Not Found',
  'fname': u'cc/ccd41799069ae21b845f931369eca4f9fdc76ba5',
  'name': u'Menu_009.png',
  's3_lost': True},
 {'error': 'Not Found',
  'fname': u'4f/4f21892e89f55600f30723c55094ac8658a48bab',
  'name': u'Screenshot-20180903121333-1348x741.png',
  's3_lost': True}]

In [4]: env.cr.commit() # to make sure that field s3_lost gets updated

```

In the described scenarion we will have the s3_lost field updated in the database and that
 allows us to drop and recreate the missing assets, if that's the situation.
 
 You can also find other results using the filter expression or sorting and grouping this dictionary.