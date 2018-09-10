# Odoo AWS S3 module

The basis of the module is to allow the exact same structure of the odoo filestore inside an S3 bucket. The default behaviour is always to consider the unavailabily of an S3 connection. In all cases it will default to the flesystem. This makes migrating from filestore to S3 seamless. Just install as a server wide module or even in one only database.
        
After the propper key is loaded then the server will start witing new files to S3,  if available. To migrate just use the aws cli tool and copy all files in filestore to the respective bucket, odoo will give priority to S3 bucket.

## Requirements

```bash
$> pip install awscli boto3
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