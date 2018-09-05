# Odoo AWS S3 module

The basis of the module is to allow the exact same structure of the odoo filestore inside an S3 bucket. The default behaviour is always to consider the unavailabily of an S3 connection. In all cases it will default to the flesystem. This makes migrating from filestore to S3 seamless. Just install as a server wide module or even in one only database.
        
After the propper key is loaded then the server will start witing new files to S3,  if available. To migrate just use the aws cli tool and copy all files in filestore to the respective bucket, odoo will give priority to S3 bucket.