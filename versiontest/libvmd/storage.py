#-*- coding:utf-8 -*-
'''
Created on Aug 23, 2012

@author: johnny
'''

import databases
import error

NFS_DEFAULT = {
               'serviceip': '',
                'resource': ''
               }
CIFS_DEFAULT = {
                'serviceip': '',
                 'resource': '',
                 'username': '',
                 'password': ''
                }


def get_storage_path(host, storage):
        qurey = databases.DBQuery(host)
        keyword = "description=\'" + storage + "\'"
        if not qurey.get_storagepath(keyword):
            raise error.CommonError("Storage not found")
        
        return qurey.get_storagepath(keyword)
        
def get_storage_uuid(host, storage):
        qurey = databases.DBQuery(host)
        keyword = "description=\'" + storage + "\'"
        if not qurey.get_storagepath(keyword):
            raise error.CommonError("Storage not found")
        
        return qurey.get_storageUuid(keyword)
