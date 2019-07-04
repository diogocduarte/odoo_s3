# -*- coding: utf-8 -*-
# This is just an example script on how to automate the deployment to S3 using XML-RPC lib
import xmlrpclib

# Instance Credentials
dbname = 'v10_odoo_s3'
user = 'admin'
pwd = 'admin'
host = 'localhost'
port = 8069
protocol = 'http'

com = xmlrpclib.ServerProxy("%s://%s:%s/xmlrpc/common" % (protocol, host, port))
uid = com.login(dbname, user, pwd)
sock = xmlrpclib.ServerProxy("%s://%s:%s/xmlrpc/object" % (protocol, host, port))


config_id = sock.execute(dbname, uid, pwd, 'res.config.settings', 'create', [], {
    's3_profile': 'default',
    's3_bucket': 'testodoofs1',
    's3_load': True
})
res = sock.execute(dbname, uid, pwd, 'res.config.settings', 'execute', [config_id])
