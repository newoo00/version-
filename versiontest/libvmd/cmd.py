#-*- coding:utf-8 -*-
'''
Created on 2012-7-11

@author: johnny
'''
import Queue, json, os.path
import logging, datetime, time

import vmd_port
import listener, storage
import databases
import vmi as vm
from utils import zmq_client
from utils import base_utils
import error

STEP_INTERVAL = 5
BASE_MSG = {'id': '',
            'action': 0,
            'option_type': 'VmnoclusterchangeTask',
            'param': {} }
CODE = vmd_port.action_code
#default zmq socket port
DEFAULT_MSG_PORT = 9166
#global result queue
LISTENING_QUEUE = Queue.Queue()

class Message():
    def __init__(self):
        self.data = BASE_MSG
    
    def update(self, key, value):
        if self.data.has_key(key):
            self.data[key] = value
        else:
            print "BuildMsg: set_value: invalid key"
    
    def dumps(self):
        return json.dumps(self.data)
    
    def __str__(self):
        return str(self.data)
    
class Executer(object):
    def __init__(self):
        try:
            self.listener = listener.Listener(LISTENING_QUEUE)
        except Exception, e:
            logging.error(str(e))
              
    def insert_misson(self, host, action, opt_obj_type, opt_type,
                      param, progress=0, task_exe_stat='working',
                      username='admin', display=1):
        query = databases.DBQuery(host)

        mission_id = -1
        if query.get_mission_id_min() is not None:
            if query.get_mission_id_min() <= 0:
                mission_id = query.get_mission_id_min() - 1
        #avoid conflict with web counter
                    
        keys = """(id, action, optobjtype, progress, task_execute_stat, 
        username, display, option_type, created_at, param, user_ip )"""
        #Wrong method, it's OK, all fake.
        create_time = datetime.datetime.now().strftime("%Y%m%d %H:%M:%S.%f")
        user_ip = base_utils.get_local_ip(host)
        values = (mission_id, action, opt_obj_type, progress, task_exe_stat,
                  username, display, opt_type, create_time, param, user_ip)
        
        query.insert('missions', keys, values)
        return mission_id
            
    def run(self, action, params, host, obj_type,
            opt_type, port=DEFAULT_MSG_PORT):
        msg = Message()
        msg.update('param', params)
        msg.update('action', action)
        msg.update('option_type', opt_type)
        
        mission_id = self.insert_misson(host, action, obj_type,
                                        opt_type, str(params))
        msg.update('id', mission_id)
        logging.debug(msg)
        
        time.sleep(STEP_INTERVAL)
        self.send(msg.dumps(), host, port)
        return mission_id
        
    def send(self, message, host, port):
        #sending
        self.recv_msg = zmq_client.zmq_sender(message, host, port)
        return self.recv_msg
    
    def wait_for_done(self, m_id, host, timeout=60):
        """
        wait action finished,
        m_id: the mission id for action
        host: which host the task is running
        timeout: wait timeout
        """
        query = databases.DBQuery(host)
        while True:
            try:
                msg = LISTENING_QUEUE.get(True, timeout)
                #logging.debug(msg)
            except Queue.Empty:
                raise error.OperationTimeoutException(timeout)
            else:
                if ((msg.has_key('action') or msg.has_key('option_result'))
                     and msg.has_key('id')):
                
                    if m_id == msg['id'] and 'actionResult' == msg['message']:
                        logging.debug(msg)
                        if 'failed' == query.get_mission_stat(m_id):
                            err_msg = query.get_mission_message(m_id)
                            raise error.TestError("Action Failed: %s" % err_msg)
                    
                        if msg.has_key('option_result'):
                            return msg['option_result']
                    
                        return True
                    #Just put it back if mission id is not match, someone must need it
                    else:
                        #Every mission start from code has a negative id
                        if msg['id'] < 0 and msg['message'] != 'missionProgress':
                            LISTENING_QUEUE.put(msg, timeout=timeout)
                
    def do(self):
        #wrapper for run and wait_for_done
        pass
            
 
class Manager(object):
    def __init__(self):
        self.executor = Executer()
            
    def create(self, name, host, storage_name='defaultlocal',
               cfg=None, img=None):
        #avoid duplicated name
        if self.is_name_dupliacted(name, host):
            raise error.CommonError("Create vm: name duplicated!")
        
        m_vm = vm.VMS(name)
        
        #Set vm config info
        if cfg:
            m_vm.update_cfg(cfg)
        
        m_vm.cfg['storage_path'] = self.get_storage_path(host, storage_name)
        m_vm.cfg['storage_uuid'] = self.get_storage_uuid(host, storage_name)
        m_vm.cfg['hostUuid'] = self.get_host_uuid(host)
        
        if not img:
            m_vm.add_hd()
        else:
            vhd = {'baseimg': img, 'createvhd': 'no'}
            m_vm.add_hd(vhd)
                   
        m_vm.add_netcard()
        action_id = CODE['create_vms']      
        m_id = self.executor.run(action_id, m_vm.cfg, host, 'vm',
                                 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host, 120)
        m_vm.initialize(host, self.executor)
        return m_vm
    
    def clone_vm(self, src_vm, dest_name, dest_st, to_temp=False,
                 level='high', del_snapshot='yes', cfg=None):
        params = {}
        host_name = src_vm.get_hostname()
        if self.is_name_dupliacted(dest_name, host_name):
            raise error.CommonError("Create vm: name duplicated!")
        
        params.update(vmd_port.CLONE_VMS)
        m_vm = vm.VMS(dest_name)

        if cfg:
            params.update(cfg)
        else:
            dest_path = storage.get_storage_path(host_name, dest_st)
            dest_uuid = storage.get_storage_uuid(host_name, dest_st)
            params.update({
                       'parentUuid': src_vm.get_parentUuid(),
                       'targetVmdesc': dest_name,
                       'targetVmuuid': dest_name,
                       'bsstorage_uuid': src_vm.get_storage_uuid(),
                       'bsstorage_path': src_vm.get_storage_path(),
                       'vmUuid': src_vm.get_vmUuid(),
                       'storage_path': dest_path,
                       'storageUuid': dest_uuid,
                       'copy_level': level,
                       'del_snapshot': del_snapshot,
                       'to_template': 'yes' if to_temp else 'no' 
                       })
        
        action_id = CODE['clone_vms']
        m_id = self.executor.run(action_id, params, host_name,
                                 'vm', 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host_name, 120)
        m_vm.initialize(host_name, self.executor)
        return m_vm
    
    def snapshot(self, vm, sname, desc=""):
        params = {}
        params.update(vmd_port.TAKE_SNAPSHOT)
        params['parentUuid'] = vm.get_parentUuid()
        params['storage_uuid'] = vm.get_storage_uuid()
        params['storage_path'] = vm.get_storage_path()
        params['vmUuid'] = vm.get_vmUuid()
        params['snname'] = sname
        params['sndesc'] = desc
        host = vm.get_hostname()
        
        action_id = CODE['snapshot']
        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host)
    
    def recover_snapshot(self, vm, sn):
        params = {}
        params.update(vmd_port.RECOVER_SNAPSHOT)
        
        params['parentUuid'] = vm.get_parentUuid()
        params['storage_uuid'] = vm.get_storage_uuid()
        params['storage_path'] = vm.get_storage_path()
        params['vmUuid'] = vm.get_vmUuid()
        params['snuuid'] = sn
        host = vm.get_hostname()
        
        action_id = CODE['re_snapshot']
        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host)
    
    def clear_all_snapshot(self, vm):
        params = {}

        params['vmUuid'] = vm.get_vmUuid()
        params['storage_path'] = vm.get_storage_path()
        host = vm.get_hostname()

        action_id = CODE['clear_snapshot']
        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host)

    def conv_to_template(self, vm, del_snapshot=True):
        params = {}
        
        params['vmUuid'] = vm.get_vmUuid()
        params['parentUuid'] = vm.get_parentUuid()
        params['storage_path'] = vm.get_storage_path()
        host = vm.get_hostname()
        
        action_id = CODE['vm2temp']

        if del_snapshot:
            self.clear_all_snapshot(vm)

        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host)
        
    def dele_template(self, tp):
        params = {}
        
        params['vmUuid'] = tp.get_vmUuid()
        params['parentUuid'] = tp.get_parentUuid()
        params['storage_path'] = tp.get_storage_path()
        params['copy_level'] = ""
        host = tp.get_hostname()
        
        action_id = CODE['delete_temp']
        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host)
    
    #deprecated
    def pause_vm(self, vm):
        params = {}
        
        params['vmUuid'] = vm.get_vmUuid()
        params['parentUuid'] = vm.get_parentUuid()
        params['storage_path'] = vm.get_storage_path()
        host = vm.get_hostname()
        
        action_id = CODE['vm_pause']
        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host)
    
    def trans_vm(self, vm, storage, level="low", target=None):
        params = {}
        
        params['vmUuid'] = vm.get_vmUuid()
        params['storage_path'] = vm.get_storage_path()
        params['target_storage_path'] = vm.host.get_storage_path(storage)
        params['copy_level'] = level
        if target:
            params['target'] = target
        host = vm.get_hostname()
        
        action_id = CODE['vm_trans']
        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host)

    def diff_clone(self, tp, basename, typ='rw', number=1):
        '''
        tp: the name of template
        typ: diff clone type, 0 for readonly, 1 for read/write 
        '''
        params = {}
        
        params['vmUuid'] = tp.get_vmUuid()
        params['storage_path'] = tp.get_storage_path()
        if typ == 'ro':
            params['diff_type'] = 'ro_diff'
        elif typ == 'rw':
            params['diff_type'] = 'rw_diff'
        
        params['base_name'] = basename
        params['totalnum'] = number
        host = tp.get_hostname()
        
        action_id = CODE['diff_clone']
        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        
        #return names of cloned vm
        return self.executor.wait_for_done(m_id, host)
    
    def backup_vm(self, vm, dest, tp=0, level="low", 
                  descr="", baktype="manul"):
        params = {}
        
        params['vmUuid'] = vm.get_vmUuid()
        params['uuid'] = vm.get_storage_uuid()
        params['parentUuid'] = vm.get_parentUuid()
        params['storage_path'] = vm.get_storage_path()
        params['copy_Level'] = level
        params['bakdsc'] = descr
        params['baktype'] = baktype
        
        if vm.host.get_storage_path(dest):
            params['targetstorage_path'] = vm.host.get_storage_path(dest)
        else:
            raise error.CommonError("Target storage does not exist.")
        if not tp:
            params['backup_type'] = "diff_backup"
        elif tp == 1:
            params['backup_type'] = "complete_backup"
        
        action_id = CODE['backup_vm']
        host = vm.get_hostname()
        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        
        self.executor.wait_for_done(m_id, host, timeout=1800)
    
    def recover_backup(self, name, vm, t_storage, backup_numb=1, netcard=None):
        vm_uuid = vm.get_vmUuid()
        backup_id = vm.host.get_backups(vm_uuid, backup_numb)[0]
        backup_info = vm.host.get_backup_info(backup_id)
        default_netcard = [{"pg":"Virtual Machine Network 0",
                            "vnet_type":"Virtio ParaVirtual",
                            "seq":1}]
        
        params = {}
        params['baknum'] = str(backup_numb)
        params['storage_path'] = backup_info['storage_path']
        params['storage_uuid'] = backup_info['storage_uuid']
        params['target_storage_uuid'] = vm.host.get_storage_uuid(t_storage)
        params['targetstorage_path'] = vm.host.get_storage_path(t_storage)
        params['vmUuid'] = backup_info['vm_uuid']
        params['backup_type'] = backup_info['baktype']
        params['baktim'] = time.strftime("%Y-%m-%d %H:%M:%S", 
                           time.localtime(float(backup_info['baktim'])))
        params['nvmuuid'] = name
        params['hostUuid'] = vm.host.uuid
        params['nvmname'] = name
        params['pcidevice'] = []
        if netcard:
            params['netcardAllPara'] = netcard
        else:
            params['netcardAllPara'] = default_netcard

        action_id = CODE['recover_backup']
        host = vm.get_hostname()
        m_id = self.executor.run(action_id, params, host, 'vm',
                                 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host, timeout=1800)


    
    def delete_vm(self, host, vm, del_vhd=False):
        params = {}
        self.vm = vm
        params['vmUuid'] = self.vm.get_vmUuid()
        params['storage_path'] = self.vm.get_storage_path()
        params['parentUuid'] = self.vm.cfg['hostUuid']
        params['storageUuid'] = self.vm.get_storage_uuid()
        if del_vhd:
            params['delvhd'] = 'delvhd'
        else:
            params['delvhd'] = 'savevhd'
            
        action_id = CODE['delete_vms']
        m_id = self.executor.run(action_id, params, host,
                                 'vm', 'VmnoclusterchangeTask')
        self.executor.wait_for_done(m_id, host, 120)
    
    def is_name_dupliacted(self, name, host):
        query = databases.DBQuery(host)
        if name in query.query('vms', column='description'):
            return True
        else:
            return False
    
    def check_img(self, vm):
        img = os.path.basename(vm.get_baseimg())
        storage_path = vm.get_storage_path()
        result = vm.host.run("find %s -name %s" % 
                             (storage_path, img)).stdout.strip()
        
        if vm.get_baseimg() not in result:
            raise error.TestError("Check create: Cannot find image file")
    
    def check_clone(self, vm):
        img = os.path.basename(vm.get_baseimg())
        storage_path = vm.get_storage_path()
        result = vm.host.run("find %s -name %s" % 
                             (storage_path, img)).stdout.strip()
        
        if vm.get_baseimg() not in result:
            raise error.TestError("VERIFY clone: Cannot find image file")
     
    def get_img_path(self, host, storage, name):
        query = databases.DBQuery(host, user="postgres")
        keyword = "description=\'" + storage + "\'"
        path = os.path.join(query.get_storagepath(keyword), name)
        path = path.replace('\\', '/')
        return path   
        
    def get_storage_path(self, host, storage_name):
        return storage.get_storage_path(host, storage_name)
        
    def get_storage_uuid(self, host, storage_name):
        return storage.get_storage_uuid(host, storage_name)
        
    def get_host_uuid(self, host):
        qurey = databases.DBQuery(host)
        return qurey.get_hostUuid()
        
    def wait_parallel(self, mission_ids, host):
        for i in mission_ids:
            self.executor.wait_for_done(i, host)
        
    
