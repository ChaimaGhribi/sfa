#
# SFA XML-RPC and SOAP interfaces
#
### $Id$
### $URL$
#

import sys
import os
import traceback
import string
import xmlrpclib
from sfa.trust.auth import Auth
from sfa.util.config import *
from sfa.util.faults import *
from sfa.util.debug import *
from sfa.trust.rights import *
from sfa.trust.credential import *
from sfa.trust.certificate import *
from sfa.util.namespace import *
from sfa.util.api import *
from sfa.util.nodemanager import NodeManager
from sfa.util.sfalogging import *

def list_to_dict(recs, key):
    keys = [rec[key] for rec in recs]
    return dict(zip(keys, recs))


class SfaAPI(BaseAPI):

    # flat list of method names
    import sfa.methods
    methods = sfa.methods.all
    
    def __init__(self, config = "/etc/sfa/sfa_config.py", encoding = "utf-8", methods='sfa.methods', \
                 peer_cert = None, interface = None, key_file = None, cert_file = None):
        BaseAPI.__init__(self, config=config, encoding=encoding, methods=methods, \
                         peer_cert=peer_cert, interface=interface, key_file=key_file, \
                         cert_file=cert_file)
 
        self.encoding = encoding

        from sfa.util.table import SfaTable
        self.SfaTable = SfaTable
        # Better just be documenting the API
        if config is None:
            print "CONFIG IS NONE"
            return

        # Load configuration
        self.config = Config(config)
        self.auth = Auth(peer_cert)
        self.interface = interface
        self.key_file = key_file
        self.key = Keypair(filename=self.key_file)
        self.cert_file = cert_file
        self.cert = Certificate(filename=self.cert_file)
        self.credential = None
        # Initialize the PLC shell only if SFA wraps a myPLC
        rspec_type = self.config.get_aggregate_type()
        if (rspec_type == 'pl' or rspec_type == 'vini'):
            self.plshell = self.getPLCShell()
            self.plshell_version = self.getPLCShellVersion()

        self.hrn = self.config.SFA_INTERFACE_HRN
        self.time_format = "%Y-%m-%d %H:%M:%S"
        self.logger=get_sfa_logger()

    def getPLCShell(self):
        self.plauth = {'Username': self.config.SFA_PLC_USER,
                       'AuthMethod': 'password',
                       'AuthString': self.config.SFA_PLC_PASSWORD}
        try:
            sys.path.append(os.path.dirname(os.path.realpath("/usr/bin/plcsh")))
            self.plshell_type = 'direct'
            import PLC.Shell
            shell = PLC.Shell.Shell(globals = globals())
            shell.AuthCheck(self.plauth)
            return shell
        except ImportError:
            self.plshell_type = 'xmlrpc' 
            # connect via xmlrpc
            url = self.config.SFA_PLC_URL
            shell = xmlrpclib.Server(url, verbose = 0, allow_none = True)
            shell.AuthCheck(self.plauth)
            return shell

    def getPLCShellVersion(self):
        # We need to figure out what version of PLCAPI we are talking to.
        # Some calls we need to make later will be different depending on
        # the api version. 
        try:
            # This is probably a bad way to determine api versions
            # but its easy and will work for now. Lets try to make 
            # a call that only exists is PLCAPI.4.3. If it fails, we
            # can assume the api version is 4.2
            self.plshell.GetTagTypes(self.plauth)
            return '4.3'
        except:
            return '4.2'
            

    def getCredential(self):
        if self.interface in ['registry']:
            return self.getCredentialFromLocalRegistry()
        else:
            return self.getCredentialFromRegistry()
    
    def getCredentialFromRegistry(self):
        """ 
        Get our credential from a remote registry 
        """
        type = 'authority'
        path = self.config.SFA_DATA_DIR
        filename = ".".join([self.interface, self.hrn, type, "cred"])
        cred_filename = path + os.sep + filename
        try:
            credential = Credential(filename = cred_filename)
            return credential.save_to_string(save_parents=True)
        except IOError:
            from sfa.server.registry import Registries
            registries = Registries(self)
            registry = registries[self.hrn]
            cert_string=self.cert.save_to_string(save_parents=True)
            # get self credential
            self_cred = registry.get_self_credential(cert_string, type, self.hrn)
            # get credential
            cred = registry.get_credential(self_cred, type, self.hrn)
            
            # save cred to file
            Credential(string=cred).save_to_file(cred_filename, save_parents=True)
            return cred

    def getCredentialFromLocalRegistry(self):
        """
        Get our current credential directly from the local registry.
        """

        hrn = self.hrn
        auth_hrn = self.auth.get_authority(hrn)
    
        # is this a root or sub authority
        if not auth_hrn or hrn == self.config.SFA_INTERFACE_HRN:
            auth_hrn = hrn
        auth_info = self.auth.get_auth_info(auth_hrn)
        table = self.SfaTable()
        records = table.findObjects(hrn)
        if not records:
            raise RecordNotFound
        record = records[0]
        type = record['type']
        object_gid = record.get_gid_object()
        new_cred = Credential(subject = object_gid.get_subject())
        new_cred.set_gid_caller(object_gid)
        new_cred.set_gid_object(object_gid)
        new_cred.set_issuer(key=auth_info.get_pkey_object(), subject=auth_hrn)
        new_cred.set_pubkey(object_gid.get_pubkey())
        r1 = determine_rights(type, hrn)
        new_cred.set_privileges(r1)

        auth_kind = "authority,ma,sa"

        new_cred.set_parent(self.auth.hierarchy.get_auth_cred(auth_hrn, kind=auth_kind))

        new_cred.encode()
        new_cred.sign()

        return new_cred.save_to_string(save_parents=True)
   

    def loadCredential (self):
        """
        Attempt to load credential from file if it exists. If it doesnt get
        credential from registry.
        """

        # see if this file exists
        # XX This is really the aggregate's credential. Using this is easier than getting
        # the registry's credential from iteslf (ssl errors).   
        ma_cred_filename = self.config.SFA_DATA_DIR + os.sep + self.interface + self.hrn + ".ma.cred"
        try:
            self.credential = Credential(filename = ma_cred_filename)
        except IOError:
            self.credential = self.getCredentialFromRegistry()

    ##
    # Convert SFA fields to PLC fields for use when registering up updating
    # registry record in the PLC database
    #
    # @param type type of record (user, slice, ...)
    # @param hrn human readable name
    # @param sfa_fields dictionary of SFA fields
    # @param pl_fields dictionary of PLC fields (output)

    def sfa_fields_to_pl_fields(self, type, hrn, record):

        def convert_ints(tmpdict, int_fields):
            for field in int_fields:
                if field in tmpdict:
                    tmpdict[field] = int(tmpdict[field])

        pl_record = {}
        #for field in record:
        #    pl_record[field] = record[field]
 
        if type == "slice":
            if not "instantiation" in pl_record:
                pl_record["instantiation"] = "plc-instantiated"
            pl_record["name"] = hrn_to_pl_slicename(hrn)
	    if "url" in record:
               pl_record["url"] = record["url"]
	    if "description" in record:
	        pl_record["description"] = record["description"]
	    if "expires" in record:
	        pl_record["expires"] = int(record["expires"])

        elif type == "node":
            if not "hostname" in pl_record:
                if not "hostname" in record:
                    raise MissingSfaInfo("hostname")
                pl_record["hostname"] = record["hostname"]
            if not "model" in pl_record:
                pl_record["model"] = "geni"

        elif type == "authority":
            pl_record["login_base"] = hrn_to_pl_login_base(hrn)

            if not "name" in pl_record:
                pl_record["name"] = hrn

            if not "abbreviated_name" in pl_record:
                pl_record["abbreviated_name"] = hrn

            if not "enabled" in pl_record:
                pl_record["enabled"] = True

            if not "is_public" in pl_record:
                pl_record["is_public"] = True

        return pl_record

    def fill_record_pl_info(self, records):
        """
        Fill in the planetlab specific fields of a SFA record. This
        involves calling the appropriate PLC method to retrieve the 
        database record for the object.
        
        PLC data is filled into the pl_info field of the record.
    
        @param record: record to fill in field (in/out param)     
        """
        # get ids by type
        node_ids, site_ids, slice_ids = [], [], [] 
        person_ids, key_ids = [], []
        type_map = {'node': node_ids, 'authority': site_ids,
                    'slice': slice_ids, 'user': person_ids}
                  
        for record in records:
            for type in type_map:
                if type == record['type']:
                    type_map[type].append(record['pointer'])

        # get pl records
        nodes, sites, slices, persons, keys = {}, {}, {}, {}, {}
        if node_ids:
            node_list = self.plshell.GetNodes(self.plauth, node_ids)
            nodes = list_to_dict(node_list, 'node_id')
        if site_ids:
            site_lists = self.plshell.GetSites(self.plauth, site_ids)
            sites = list_to_dict(site_list, 'site_id')
        if slice_ids:
            slice_list = self.plshell.GetSlices(self.plauth, slice_ids)
            slices = list_to_dict(slice_list, 'slice_id')
        if person_ids:
            person_list = self.plshell.GetPersons(self.plauth, person_ids)
            persons = list_to_dict(person_list, 'person_id')
            for person in persons:
                key_ids.extend(persons[person]['key_ids'])

        pl_records = {'node': nodes, 'authority': sites,
                      'slice': slices, 'user': persons}

        if key_ids:
            key_list = self.plshell.GetKeys(self.plauth, key_ids)
            keys = list_to_dict(key_list, 'key_id')

        # fill record info
        for record in records:
            # records with pointer==-1 do not have plc info associated with them.
            # for example, the top level authority records which are
            # authorities, but not PL "sites"
            if record['pointer'] == -1:
                continue
           
            for type in pl_records:
                if record['type'] == type:
                    if record['pointer'] in pl_records[type]:
                        record.update(pl_records[type][record['pointer']])
                        break
            # fill in key info
            if record['type'] == 'user':
                pubkeys = [keys[key_id]['key'] for key_id in record['key_ids'] if key_id in keys] 
                record['keys'] = pubkeys

        # fill in record hrns
        records = self.fill_record_hrns(records)   
 
        return records

    def fill_record_hrns(self, records):
        """
        convert pl ids to hrns
        """

        # get ids
        slice_ids, person_ids, site_ids, node_ids = [], [], [], []
        for record in records:
            if 'site_id' in record:
                site_ids.append(record['site_id'])
            if 'site_ids' in records:
                site_ids.extend(record['site_ids'])
            if 'person_ids' in record:
                person_ids.extend(record['person_ids'])
            if 'slice_ids' in record:
                slice_ids.extend(record['slice_ids'])
            if 'node_ids' in record:
                node_ids.extend(record['node_ids'])

        # get pl records
        slices, persons, sites, nodes = {}, {}, {}, {}
        if site_ids:
            site_list = self.plshell.GetSites(self.plauth, site_ids, ['site_id', 'login_base'])
            sites = list_to_dict(site_list, 'site_id')
        if person_ids:
            person_list = self.plshell.GetPersons(self.plauth, person_ids, ['person_id', 'email'])
            persons = list_to_dict(person_list, 'person_id')
        if slice_ids:
            slice_list = self.plshell.GetSlices(self.plauth, slice_ids, ['slice_id', 'name'])
            slices = list_to_dict(slice_list, 'slice_id')       
        if node_ids:
            node_list = self.plshell.GetNodes(self.plauth, node_ids, ['node_id', 'hostname'])
            nodes = list_to_dict(node_list, 'node_id')
       
        # convert ids to hrns
        for record in records:
             
            # get all relevant data
            type = record['type']
            pointer = record['pointer']
            auth_hrn = self.hrn
            login_base = ''
            if pointer == -1:
                continue

            if 'site_id' in record:
                site = sites[record['site_id']]
                login_base = site['login_base']
                record['site'] = ".".join([auth_hrn, login_base])
            if 'person_ids' in record:
                emails = [persons[person_id]['email'] for person_id in record['person_ids'] \
                          if person_id in  persons]
                usernames = [email.split('@')[0] for email in emails]
                person_hrns = [".".join([auth_hrn, login_base, username]) for username in usernames]
                record['persons'] = person_hrns 
            if 'slice_ids' in record:
                slicenames = [slices[slice_id]['name'] for slice_id in record['slice_ids'] \
                              if slice_id in slices]
                slice_hrns = [slicename_to_hrn(auth_hrn, slicename) for slicename in slicenames]
                record['slices'] = slice_hrns
            if 'node_ids' in record:
                hostnames = [nodes[node_id]['hostname'] for node_id in record['node_ids'] \
                             if node_id in nodes]
                node_hrns = [hostname_to_hrn(auth_hrn, login_base, hostname) for hostname in hostnames]
                record['nodes'] = node_hrns
            if 'site_ids' in record:
                login_bases = [sites[site_id]['login_base'] for site_id in record['site_ids'] \
                               if site_id in sites]
                site_hrns = [".".join([auth_hrn, lbase]) for lbase in login_bases]
                record['sites'] = site_hrns

        return records   

    def fill_record_sfa_info(self, record):
        sfa_info = {}
        type = record['type']
        table = self.SfaTable()
        if (type == "slice"):
            person_ids = record.get("person_ids", [])
            persons = table.find({'type': 'user', 'pointer': person_ids})
            researchers = [person['hrn'] for person in persons]
            sfa_info['researcher'] = researchers

        elif (type == "authority"):
            person_ids = record.get("person_ids", [])
            persons = table.find({'type': 'user', 'pointer': person_ids})
            persons_dict = {}
            for person in persons:
                persons_dict[person['pointer']] = person 
            pl_persons = self.plshell.GetPersons(self.plauth, person_ids, ['person_id', 'roles'])
            pis, techs, admins = [], [], []
            for person in pl_persons:
                pointer = person['person_id']
                
                if pointer not in persons_dict:
                    # this means there is not sfa record for this user
                    continue    
                hrn = persons_dict[pointer]['hrn']    
                if 'pi' in person['roles']:
                    pis.append(hrn)
                if 'tech' in person['roles']:
                    techs.append(hrn)
                if 'admin' in person['roles']:
                    admins.append(hrn)
            
            sfa_info['PI'] = pis
            sfa_info['operator'] = techs
            sfa_info['owner'] = admins
            # xxx TODO: OrganizationName

        elif (type == "node"):
            sfa_info['dns'] = record.get("hostname", "")
            # xxx TODO: URI, LatLong, IP, DNS
    
        elif (type == "user"):
            sfa_info['email'] = record.get("email", "")
            # xxx TODO: PostalAddress, Phone

        record.update(sfa_info)

    def fill_record_info(self, records):
        """
        Given a SFA record, fill in the PLC specific and SFA specific
        fields in the record. 
        """
        if not isinstance(records, list):
            records = [records]

        self.fill_record_pl_info(records)
        for record in records:
            self.fill_record_sfa_info(record)        
        #self.fill_record_sfa_info(records)

    def update_membership_list(self, oldRecord, record, listName, addFunc, delFunc):
        # get a list of the HRNs tht are members of the old and new records
        if oldRecord:
            oldList = oldRecord.get(listName, [])
        else:
            oldList = []     
        newList = record.get(listName, [])

        # if the lists are the same, then we don't have to update anything
        if (oldList == newList):
            return

        # build a list of the new person ids, by looking up each person to get
        # their pointer
        newIdList = []
        table = self.SfaTable()
        records = table.find({'type': 'user', 'hrn': newList})
        for rec in records:
            newIdList.append(rec['pointer'])

        # build a list of the old person ids from the person_ids field 
        if oldRecord:
            oldIdList = oldRecord.get("person_ids", [])
            containerId = oldRecord.get_pointer()
        else:
            # if oldRecord==None, then we are doing a Register, instead of an
            # update.
            oldIdList = []
            containerId = record.get_pointer()

    # add people who are in the new list, but not the oldList
        for personId in newIdList:
            if not (personId in oldIdList):
                addFunc(self.plauth, personId, containerId)

        # remove people who are in the old list, but not the new list
        for personId in oldIdList:
            if not (personId in newIdList):
                delFunc(self.plauth, personId, containerId)

    def update_membership(self, oldRecord, record):
        if record.type == "slice":
            self.update_membership_list(oldRecord, record, 'researcher',
                                        self.plshell.AddPersonToSlice,
                                        self.plshell.DeletePersonFromSlice)
        elif record.type == "authority":
            # xxx TODO
            pass



class ComponentAPI(BaseAPI):

    def __init__(self, config = "/etc/sfa/sfa_config.py", encoding = "utf-8", methods='sfa.methods',
                 peer_cert = None, interface = None, key_file = None, cert_file = None):

        BaseAPI.__init__(self, config=config, encoding=encoding, methods=methods, peer_cert=peer_cert,
                         interface=interface, key_file=key_file, cert_file=cert_file)
        self.encoding = encoding

        # Better just be documenting the API
        if config is None:
            return

        self.nodemanager = NodeManager(self.config)

    def sliver_exists(self):
        sliver_dict = self.nodemanager.GetXIDs()
        if slicename in sliver_dict.keys():
            return True
        else:
            return False
