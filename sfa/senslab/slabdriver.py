import subprocess

from datetime import datetime

from sfa.util.faults import SliverDoesNotExist, UnknownSfaType
from sfa.util.sfalogging import logger

from sfa.storage.alchemy import dbsession
from sfa.storage.model import RegRecord, RegUser

from sfa.trust.credential import Credential


from sfa.managers.driver import Driver
from sfa.rspecs.version_manager import VersionManager
from sfa.rspecs.rspec import RSpec

from sfa.util.xrn import hrn_to_urn


## thierry: everything that is API-related (i.e. handling incoming requests) 
# is taken care of 
# SlabDriver should be really only about talking to the senslab testbed


from sfa.senslab.OARrestapi import  OARrestapi
from sfa.senslab.LDAPapi import LDAPapi

from sfa.senslab.slabpostgres import SlabDB, slab_dbsession, SliceSenslab
                                                                
from sfa.senslab.slabaggregate import SlabAggregate, slab_xrn_to_hostname, \
                                                            slab_xrn_object
from sfa.senslab.slabslices import SlabSlices



# thierry : note
# this inheritance scheme is so that the driver object can receive
# GetNodes or GetSites sorts of calls directly
# and thus minimize the differences in the managers with the pl version
class SlabDriver(Driver):
    """ Senslab Driver class inherited from Driver generic class.
    
    Contains methods compliant with the SFA standard and the testbed
    infrastructure (calls to LDAP and OAR).
    """
    def __init__(self, config):
        Driver.__init__ (self, config)
        self.config = config
        self.hrn = config.SFA_INTERFACE_HRN
        self.root_auth = config.SFA_REGISTRY_ROOT_AUTH
        self.oar = OARrestapi()
        self.ldap = LDAPapi()
        self.time_format = "%Y-%m-%d %H:%M:%S"
        self.db = SlabDB(config, debug = True)
        self.cache = None
        
    
    def sliver_status(self, slice_urn, slice_hrn):
        """Receive a status request for slice named urn/hrn 
        urn:publicid:IDN+senslab+nturro_slice hrn senslab.nturro_slice
        shall return a structure as described in
        http://groups.geni.net/geni/wiki/GAPI_AM_API_V2#SliverStatus
        NT : not sure if we should implement this or not, but used by sface.
        
        """
        
        #First get the slice with the slice hrn
        slice_list =  self.GetSlices(slice_filter = slice_hrn, \
                                    slice_filter_type = 'slice_hrn')
        
        if len(slice_list) is 0:
            raise SliverDoesNotExist("%s  slice_hrn" % (slice_hrn))
        
        #Slice has the same slice hrn for each slice in the slice/lease list
        #So fetch the info on the user once 
        one_slice = slice_list[0] 
        recuser = dbsession.query(RegRecord).filter_by(record_id = \
                                            one_slice['record_id_user']).first()
        
        #Make a list of all the nodes hostnames  in use for this slice
        slice_nodes_list = []
        for sl in slice_list:
            for node in sl['node_ids']:
                slice_nodes_list.append(node['hostname'])
            
        #Get all the corresponding nodes details    
        nodes_all = self.GetNodes({'hostname':slice_nodes_list},
                                ['node_id', 'hostname','site','boot_state'])
        nodeall_byhostname = dict([(n['hostname'], n) for n in nodes_all])  
          
          
          
        for sl in slice_list:

              #For compatibility
            top_level_status = 'empty' 
            result = {}
            result.fromkeys(\
                ['geni_urn','pl_login','geni_status','geni_resources'], None)
            result['pl_login'] = recuser.hrn
            logger.debug("Slabdriver - sliver_status Sliver status \
                                        urn %s hrn %s sl  %s \r\n " \
                                        %(slice_urn, slice_hrn, sl))
            try:
                nodes_in_slice = sl['node_ids']
            except KeyError:
                #No job in the slice
                result['geni_status'] = top_level_status
                result['geni_resources'] = [] 
                return result
           
            top_level_status = 'ready' 

            #A job is running on Senslab for this slice
            # report about the local nodes that are in the slice only
         
            result['geni_urn'] = slice_urn
            

            
            #timestamp = float(sl['startTime']) + float(sl['walltime']) 
            #result['pl_expires'] = strftime(self.time_format, \
                                                    #gmtime(float(timestamp)))
            #result['slab_expires'] = strftime(self.time_format,\
                                                    #gmtime(float(timestamp)))
            
            resources = []
            for node in sl['node_ids']:
                res = {}
                #res['slab_hostname'] = node['hostname']
                #res['slab_boot_state'] = node['boot_state']
                
                res['pl_hostname'] = node['hostname']
                res['pl_boot_state'] = \
                            nodeall_byhostname[node['hostname']]['boot_state']
                #res['pl_last_contact'] = strftime(self.time_format, \
                                                    #gmtime(float(timestamp)))
                sliver_id =  Xrn(slice_urn, type='slice', \
                        id=nodeall_byhostname[node['hostname']]['node_id'], \
                        authority=self.hrn).urn
    
                res['geni_urn'] = sliver_id 
                if nodeall_byhostname[node['hostname']]['boot_state'] == 'Alive':

                    res['geni_status'] = 'ready'
                else:
                    res['geni_status'] = 'failed'
                    top_level_status = 'failed' 
                    
                res['geni_error'] = ''
        
                resources.append(res)
                
            result['geni_status'] = top_level_status
            result['geni_resources'] = resources 
            logger.debug("SLABDRIVER \tsliver_statusresources %s res %s "\
                                                    %(resources,res))
            return result        
            
             
    def create_sliver (self, slice_urn, slice_hrn, creds, rspec_string, \
                                                             users, options):
        aggregate = SlabAggregate(self)
        
        slices = SlabSlices(self)
        peer = slices.get_peer(slice_hrn)
        sfa_peer = slices.get_sfa_peer(slice_hrn)
        slice_record = None 
 
        if not isinstance(creds, list):
            creds = [creds]
    
        if users:
            slice_record = users[0].get('slice_record', {})
    
        # parse rspec
        rspec = RSpec(rspec_string)
        logger.debug("SLABDRIVER.PY \t create_sliver \tr spec.version \
                                            %s slice_record %s " \
                                            %(rspec.version,slice_record))

        # ensure site record exists?
        # ensure slice record exists
        #Removed options to verify_slice SA 14/08/12
        sfa_slice = slices.verify_slice(slice_hrn, slice_record, peer, \
                                                    sfa_peer)
                                                    
        #requested_attributes returned by rspec.version.get_slice_attributes() 
        #unused, removed SA 13/08/12
        rspec.version.get_slice_attributes()

        logger.debug("SLABDRIVER.PY create_sliver slice %s " %(sfa_slice))
        
        # ensure person records exists
        #verify_persons returns added persons but since the return value
        #is not used 
        slices.verify_persons(slice_hrn, sfa_slice, users, peer, \
                                                    sfa_peer, options=options)
        

        
        # add/remove slice from nodes 
       
        requested_slivers = [node.get('component_name') \
                            for node in rspec.version.get_nodes_with_slivers()]
        l = [ node for node in rspec.version.get_nodes_with_slivers() ]
        logger.debug("SLADRIVER \tcreate_sliver requested_slivers \
                                    requested_slivers %s  listnodes %s" \
                                    %(requested_slivers,l))
        #verify_slice_nodes returns nodes, but unused here. Removed SA 13/08/12.
        #slices.verify_slice_nodes(sfa_slice, requested_slivers, peer) 
        
        # add/remove leases
        requested_lease_list = []

        logger.debug("SLABDRIVER.PY \tcreate_sliver AVANTLEASE " )
        rspec_requested_leases = rspec.version.get_leases()
        for lease in rspec.version.get_leases():
            single_requested_lease = {}
            logger.debug("SLABDRIVER.PY \tcreate_sliver lease %s " %(lease))
            if not lease.get('lease_id'):
                single_requested_lease['hostname'] = \
                            slab_xrn_to_hostname(\
                                            lease.get('component_id').strip())
                single_requested_lease['start_time'] = lease.get('start_time')
                single_requested_lease['duration'] = lease.get('duration')

            if single_requested_lease.get('hostname'):
                requested_lease_list.append(single_requested_lease)
                
        logger.debug("SLABDRIVER.PY \tcreate_sliver APRESLEASE" )       
        #dCreate dict of leases by start_time, regrouping nodes reserved
        #at the same
        #time, for the same amount of time = one job on OAR
        requested_job_dict = {}
        for lease in requested_lease_list:
            
            #In case it is an asap experiment start_time is empty
            if lease['start_time'] == '':
                lease['start_time'] = '0' 
                
            if lease['start_time'] not in requested_job_dict:
                if isinstance(lease['hostname'], str):
                    lease['hostname'] =  [lease['hostname']]
                    
                requested_job_dict[lease['start_time']] = lease
                
            else :
                job_lease = requested_job_dict[lease['start_time']]
                if lease['duration'] == job_lease['duration'] :
                    job_lease['hostname'].append(lease['hostname'])
                    
          
                
                        
        logger.debug("SLABDRIVER.PY \tcreate_sliver  requested_job_dict %s "\
                                                     %(requested_job_dict))    
        #verify_slice_leases returns the leases , but the return value is unused
        #here. Removed SA 13/08/12           
        slices.verify_slice_leases(sfa_slice, \
                                    requested_job_dict, peer)
        
        return aggregate.get_rspec(slice_xrn=slice_urn, version=rspec.version)
        
        
    def delete_sliver (self, slice_urn, slice_hrn, creds, options):
        
        sfa_slice_list  = self.GetSlices(slice_filter = slice_hrn, \
                                            slice_filter_type = 'slice_hrn')
        
        if not sfa_slice_list:
            return 1
        
        #Delete all in the slice
        for sfa_slice in sfa_slice_list:

        
            logger.debug("SLABDRIVER.PY delete_sliver slice %s" %(sfa_slice))
            slices = SlabSlices(self)
            # determine if this is a peer slice
        
            peer = slices.get_peer(slice_hrn) 
            #TODO delete_sliver SA : UnBindObjectFromPeer should be 
            #used when there is another 
            #senslab testbed, which is not the case 14/08/12 . 
            
            logger.debug("SLABDRIVER.PY delete_sliver peer %s" %(peer))
            try:
                if peer:
                    self.UnBindObjectFromPeer('slice', \
                                            sfa_slice['record_id_slice'], \
                                            peer, None)
                self.DeleteSliceFromNodes(sfa_slice)
            finally:
                if peer:
                    self.BindObjectToPeer('slice', \
                                            sfa_slice['record_id_slice'], \
                                            peer, sfa_slice['peer_slice_id'])
            return 1
            
            
    def AddSlice(self, slice_record):
        slab_slice = SliceSenslab( slice_hrn = slice_record['slice_hrn'], \
                        record_id_slice= slice_record['record_id_slice'] , \
                        record_id_user= slice_record['record_id_user'], \
                        peer_authority = slice_record['peer_authority'])
        logger.debug("SLABDRIVER.PY \tAddSlice slice_record %s slab_slice %s" \
                                            %(slice_record,slab_slice))
        slab_dbsession.add(slab_slice)
        slab_dbsession.commit()
        return
        
    # first 2 args are None in case of resource discovery
    def list_resources (self, slice_urn, slice_hrn, creds, options):
        #cached_requested = options.get('cached', True) 
    
        version_manager = VersionManager()
        # get the rspec's return format from options
        rspec_version = \
                version_manager.get_version(options.get('geni_rspec_version'))
        version_string = "rspec_%s" % (rspec_version)
    
        #panos adding the info option to the caching key (can be improved)
        if options.get('info'):
            version_string = version_string + "_" + \
                                        options.get('info', 'default')
    
        # look in cache first
        #if cached_requested and self.cache and not slice_hrn:
            #rspec = self.cache.get(version_string)
            #if rspec:
                #logger.debug("SlabDriver.ListResources: \
                                    #returning cached advertisement")
                #return rspec 
    
        #panos: passing user-defined options
        aggregate = SlabAggregate(self)
        origin_hrn = Credential(string=creds[0]).get_gid_caller().get_hrn()
        options.update({'origin_hrn':origin_hrn})
        rspec =  aggregate.get_rspec(slice_xrn=slice_urn, \
                                        version=rspec_version, options=options)
       
        # cache the result
        #if self.cache and not slice_hrn:
            #logger.debug("Slab.ListResources: stores advertisement in cache")
            #self.cache.add(version_string, rspec)
    
        return rspec
        
        
    def list_slices (self, creds, options):
        # look in cache first
        #if self.cache:
            #slices = self.cache.get('slices')
            #if slices:
                #logger.debug("PlDriver.list_slices returns from cache")
                #return slices
    
        # get data from db 

        slices = self.GetSlices()        
        logger.debug("SLABDRIVER.PY \tlist_slices hrn %s \r\n \r\n" %(slices))        
        slice_hrns = [slab_slice['slice_hrn'] for slab_slice in slices]
        #slice_hrns = [slicename_to_hrn(self.hrn, slab_slice['slice_hrn']) \
                                                    #for slab_slice in slices]
        slice_urns = [hrn_to_urn(slice_hrn, 'slice') \
                                                for slice_hrn in slice_hrns]

        # cache the result
        #if self.cache:
            #logger.debug ("SlabDriver.list_slices stores value in cache")
            #self.cache.add('slices', slice_urns) 
    
        return slice_urns
    
   
    def register (self, sfa_record, hrn, pub_key):
        """ 
        Adding new user, slice, node or site should not be handled
        by SFA.
        
        Adding nodes = OAR
        Adding users = LDAP Senslab
        Adding slice = Import from LDAP users
        Adding site = OAR
        """
        return -1
            
    #No site or node record update allowed       
    def update (self, old_sfa_record, new_sfa_record, hrn, new_key):
        pointer = old_sfa_record['pointer']
        old_sfa_record_type = old_sfa_record['type']

        # new_key implemented for users only
        if new_key and old_sfa_record_type not in [ 'user' ]:
            raise UnknownSfaType(old_sfa_record_type)
        
        #if (type == "authority"):
            #self.shell.UpdateSite(pointer, new_sfa_record)
    
        if old_sfa_record_type == "slice":
            slab_record = self.sfa_fields_to_slab_fields(old_sfa_record_type, \
                                                hrn, new_sfa_record)
            if 'name' in slab_record:
                slab_record.pop('name')
                #Prototype should be UpdateSlice(self,
                #auth, slice_id_or_name, slice_fields)
                #Senslab cannot update slice since slice = job
                #so we must delete and create another job
                self.UpdateSlice(pointer, slab_record)
    
        elif old_sfa_record_type == "user":
            update_fields = {}
            all_fields = new_sfa_record
            for key in all_fields.keys():
                if key in ['first_name', 'last_name', 'title', 'email',
                           'password', 'phone', 'url', 'bio', 'accepted_aup',
                           'enabled']:
                    update_fields[key] = all_fields[key]
            self.UpdatePerson(pointer, update_fields)
    
            if new_key:
                # must check this key against the previous one if it exists
                persons = self.GetPersons([pointer], ['key_ids'])
                person = persons[0]
                keys = person['key_ids']
                keys = self.GetKeys(person['key_ids'])
                
                # Delete all stale keys
                key_exists = False
                for key in keys:
                    if new_key != key['key']:
                        self.DeleteKey(key['key_id'])
                    else:
                        key_exists = True
                if not key_exists:
                    self.AddPersonKey(pointer, {'key_type': 'ssh', \
                                                    'key': new_key})


        return True
        

    def remove (self, sfa_record):
        sfa_record_type = sfa_record['type']
        hrn = sfa_record['hrn']
        if sfa_record_type == 'user':

            #get user from senslab ldap  
            person = self.GetPersons(sfa_record)
            #No registering at a given site in Senslab.
            #Once registered to the LDAP, all senslab sites are
            #accesible.
            if person :
                #Mark account as disabled in ldap
                self.DeletePerson(sfa_record)
        elif sfa_record_type == 'slice':
            if self.GetSlices(slice_filter = hrn, \
                                    slice_filter_type = 'slice_hrn'):
                self.DeleteSlice(sfa_record)

        #elif type == 'authority':
            #if self.GetSites(pointer):
                #self.DeleteSite(pointer)

        return True
            
            
            
    #TODO clean GetPeers. 05/07/12SA        
    def GetPeers (self, auth = None, peer_filter=None, return_fields_list=None):

        existing_records = {}
        existing_hrns_by_types = {}
        logger.debug("SLABDRIVER \tGetPeers auth = %s, peer_filter %s, \
                    return_field %s " %(auth , peer_filter, return_fields_list))
        all_records = dbsession.query(RegRecord).filter(RegRecord.type.like('%authority%')).all()
        for record in all_records:
            existing_records[(record.hrn, record.type)] = record
            if record.type not in existing_hrns_by_types:
                existing_hrns_by_types[record.type] = [record.hrn]
                logger.debug("SLABDRIVER \tGetPeer\t NOT IN \
                    existing_hrns_by_types %s " %( existing_hrns_by_types))
            else:
                
                logger.debug("SLABDRIVER \tGetPeer\t \INNN  type %s hrn %s " \
                                                %(record.type,record.hrn))
                existing_hrns_by_types[record.type].append(record.hrn)

                        
        logger.debug("SLABDRIVER \tGetPeer\texisting_hrns_by_types %s "\
                                             %( existing_hrns_by_types))
        records_list = [] 
      
        try: 
            if peer_filter:
                records_list.append(existing_records[(peer_filter,'authority')])
            else :
                for hrn in existing_hrns_by_types['authority']:
                    records_list.append(existing_records[(hrn,'authority')])
                    
            logger.debug("SLABDRIVER \tGetPeer \trecords_list  %s " \
                                            %(records_list))

        except KeyError:
            pass
                
        return_records = records_list
        if not peer_filter and not return_fields_list:
            return records_list

       
        logger.debug("SLABDRIVER \tGetPeer return_records %s " \
                                                    %(return_records))
        return return_records
        
     
    #TODO  : Handling OR request in make_ldap_filters_from_records 
    #instead of the for loop 
    #over the records' list
    def GetPersons(self, person_filter=None):
        """
        person_filter should be a list of dictionnaries when not set to None.
        Returns a list of users whose accounts are enabled found in ldap.
       
        """
        logger.debug("SLABDRIVER \tGetPersons person_filter %s" \
                                                    %(person_filter))
        person_list = []
        if person_filter and isinstance(person_filter, list):
        #If we are looking for a list of users (list of dict records)
        #Usually the list contains only one user record
            for searched_attributes in person_filter:
                
                #Get only enabled user accounts in senslab LDAP : 
                #add a filter for make_ldap_filters_from_record
                person = self.ldap.LdapFindUser(searched_attributes, \
                                is_user_enabled=True)
                person_list.append(person)
          
        else:
            #Get only enabled user accounts in senslab LDAP : 
            #add a filter for make_ldap_filters_from_record
            person_list  = self.ldap.LdapFindUser(is_user_enabled=True)  

        return person_list

    def GetTimezone(self):
        server_timestamp, server_tz = self.oar.parser.\
                                            SendRequest("GET_timezone")
        return server_timestamp, server_tz
    

    def DeleteJobs(self, job_id, slice_hrn):
        if not job_id or job_id is -1:
            return
        username  = slice_hrn.split(".")[-1].rstrip("_slice")
        reqdict = {}
        reqdict['method'] = "delete"
        reqdict['strval'] = str(job_id)
       

        answer = self.oar.POSTRequestToOARRestAPI('DELETE_jobs_id', \
                                                    reqdict,username)
        logger.debug("SLABDRIVER \tDeleteJobs jobid  %s \r\n answer %s \
                                username %s" %(job_id,answer, username))
        return answer

            
        
        ##TODO : Unused GetJobsId ? SA 05/07/12
    #def GetJobsId(self, job_id, username = None ):
        #"""
        #Details about a specific job. 
        #Includes details about submission time, jot type, state, events, 
        #owner, assigned ressources, walltime etc...
            
        #"""
        #req = "GET_jobs_id"
        #node_list_k = 'assigned_network_address'
        ##Get job info from OAR    
        #job_info = self.oar.parser.SendRequest(req, job_id, username)

        #logger.debug("SLABDRIVER \t GetJobsId  %s " %(job_info))
        #try:
            #if job_info['state'] == 'Terminated':
                #logger.debug("SLABDRIVER \t GetJobsId job %s TERMINATED"\
                                                            #%(job_id))
                #return None
            #if job_info['state'] == 'Error':
                #logger.debug("SLABDRIVER \t GetJobsId ERROR message %s "\
                                                            #%(job_info))
                #return None
                                                            
        #except KeyError:
            #logger.error("SLABDRIVER \tGetJobsId KeyError")
            #return None 
        
        #parsed_job_info  = self.get_info_on_reserved_nodes(job_info, \
                                                            #node_list_k)
        ##Replaces the previous entry 
        ##"assigned_network_address" / "reserved_resources"
        ##with "node_ids"
        #job_info.update({'node_ids':parsed_job_info[node_list_k]})
        #del job_info[node_list_k]
        #logger.debug(" \r\nSLABDRIVER \t GetJobsId job_info %s " %(job_info))
        #return job_info

        
    def GetJobsResources(self, job_id, username = None):
        #job_resources=['reserved_resources', 'assigned_resources',\
                            #'job_id', 'job_uri', 'assigned_nodes',\
                             #'api_timestamp']
        #assigned_res = ['resource_id', 'resource_uri']
        #assigned_n = ['node', 'node_uri']

        req = "GET_jobs_id_resources"
       
               
        #Get job resources list from OAR    
        node_id_list = self.oar.parser.SendRequest(req, job_id, username)
        logger.debug("SLABDRIVER \t GetJobsResources  %s " %(node_id_list))
        
        hostname_list = \
            self.__get_hostnames_from_oar_node_ids(node_id_list)
        

        #Replaces the previous entry "assigned_network_address" / 
        #"reserved_resources"
        #with "node_ids"
        job_info = {'node_ids': hostname_list}

        return job_info

            
    def get_info_on_reserved_nodes(self, job_info, node_list_name):
        #Get the list of the testbed nodes records and make a 
        #dictionnary keyed on the hostname out of it
        node_list_dict = self.GetNodes() 
        #node_hostname_list = []
        node_hostname_list = [node['hostname'] for node in node_list_dict] 
        #for node in node_list_dict:
            #node_hostname_list.append(node['hostname'])
        node_dict = dict(zip(node_hostname_list, node_list_dict))
        try :
            reserved_node_hostname_list = []
            for index in range(len(job_info[node_list_name])):
               #job_info[node_list_name][k] = 
                reserved_node_hostname_list[index] = \
                        node_dict[job_info[node_list_name][index]]['hostname']
                            
            logger.debug("SLABDRIVER \t get_info_on_reserved_nodes \
                        reserved_node_hostname_list %s" \
                        %(reserved_node_hostname_list))
        except KeyError:
            logger.error("SLABDRIVER \t get_info_on_reserved_nodes KEYERROR " )
            
        return reserved_node_hostname_list  
            
    def GetNodesCurrentlyInUse(self):
        """Returns a list of all the nodes already involved in an oar job"""
        return self.oar.parser.SendRequest("GET_running_jobs") 
    
    def __get_hostnames_from_oar_node_ids(self, resource_id_list ):
        full_nodes_dict_list = self.GetNodes()
        #Put the full node list into a dictionary keyed by oar node id
        oar_id_node_dict = {}
        for node in full_nodes_dict_list:
            oar_id_node_dict[node['oar_id']] = node
            
        #logger.debug("SLABDRIVER \t  __get_hostnames_from_oar_node_ids\
                        #oar_id_node_dict %s" %(oar_id_node_dict))

        hostname_dict_list = [] 
        for resource_id in resource_id_list:
            #Because jobs requested "asap" do not have defined resources
            if resource_id is not "Undefined":
                hostname_dict_list.append(\
                        oar_id_node_dict[resource_id]['hostname'])
                
            #hostname_list.append(oar_id_node_dict[resource_id]['hostname'])
        return hostname_dict_list 
        
    def GetReservedNodes(self,username = None):
        #Get the nodes in use and the reserved nodes
        reservation_dict_list = \
                        self.oar.parser.SendRequest("GET_reserved_nodes", username = username)
        
        
        for resa in reservation_dict_list:
            logger.debug ("GetReservedNodes resa %s"%(resa))
            #dict list of hostnames and their site
            resa['reserved_nodes'] = \
                self.__get_hostnames_from_oar_node_ids(resa['resource_ids'])
                
        #del resa['resource_ids']
        return reservation_dict_list
     
    def GetNodes(self, node_filter_dict = None, return_fields_list = None):
        """
        node_filter_dict : dictionnary of lists
        
        """
        node_dict_by_id = self.oar.parser.SendRequest("GET_resources_full")
        node_dict_list = node_dict_by_id.values()
        logger.debug (" SLABDRIVER GetNodes  node_filter_dict %s return_fields_list %s "%(node_filter_dict,return_fields_list))
        #No  filtering needed return the list directly
        if not (node_filter_dict or return_fields_list):
            return node_dict_list
        
        return_node_list = []
        if node_filter_dict:
            for filter_key in node_filter_dict:
                try:
                    #Filter the node_dict_list by each value contained in the 
                    #list node_filter_dict[filter_key]
                    for value in node_filter_dict[filter_key]:
                        for node in node_dict_list:
                            if node[filter_key] == value:
                                if return_fields_list :
                                    tmp = {}
                                    for k in return_fields_list:
                                        tmp[k] = node[k]     
                                    return_node_list.append(tmp)
                                else:
                                    return_node_list.append(node)
                except KeyError:
                    logger.log_exc("GetNodes KeyError")
                    return


        return return_node_list
    
  
    def GetSites(self, site_filter_name_list = None, return_fields_list = None):
        site_dict = self.oar.parser.SendRequest("GET_sites")
        #site_dict : dict where the key is the sit ename
        return_site_list = []
        if not ( site_filter_name_list or return_fields_list):
            return_site_list = site_dict.values()
            return return_site_list
        
        for site_filter_name in site_filter_name_list:
            if site_filter_name in site_dict:
                if return_fields_list:
                    for field in return_fields_list:
                        tmp = {}
                        try:
                            tmp[field] = site_dict[site_filter_name][field]
                        except KeyError:
                            logger.error("GetSites KeyError %s "%(field))
                            return None
                    return_site_list.append(tmp)
                else:
                    return_site_list.append( site_dict[site_filter_name])
            

        return return_site_list
                
                
      
    def GetSlices(self, slice_filter = None, slice_filter_type = None):
    #def GetSlices(self, slice_filter = None, slice_filter_type = None, \
                                            #return_fields_list = None):
        """ Get the slice records from the slab db. 
        Returns a slice ditc if slice_filter  and slice_filter_type 
        are specified.
        Returns a list of slice dictionnaries if there are no filters
        specified. 
       
        """
        login = None
        return_slice_list = []
        slicerec  = {}
        slicerec_dict = {}
        authorized_filter_types_list = ['slice_hrn', 'record_id_user']
        slicerec_dictlist = []
        
             
        if slice_filter_type in authorized_filter_types_list:
            
            
            def __get_slice_records(slice_filter = None, slice_filter_type = None):
       
                login = None
                #Get list of slices based on the slice hrn
                if slice_filter_type == 'slice_hrn':
        
                    login = slice_filter.split(".")[1].split("_")[0] 
                    
                    #DO NOT USE RegSlice - reg_researchers to get the hrn of the user
                    #otherwise will mess up the RegRecord in Resolve, don't know
                    #why - SA 08/08/2012
                    
                    #Only one entry for one user  = one slice in slice_senslab table
                    slicerec = slab_dbsession.query(SliceSenslab).filter_by(slice_hrn = slice_filter).first()
                    
                #Get slice based on user id                             
                if slice_filter_type == 'record_id_user':
                    slicerec = slab_dbsession.query(SliceSenslab).filter_by(record_id_user = slice_filter).first()
                    
                if slicerec is None:
                    return login, []
                else:
                    fixed_slicerec_dict = slicerec.dump_sqlalchemyobj_to_dict()
                    
                    if login is None :
                        login = fixed_slicerec_dict['slice_hrn'].split(".")[1].split("_")[0] 
                    return login, fixed_slicerec_dict
                
            
            
            
            login, fixed_slicerec_dict = __get_slice_records(slice_filter, slice_filter_type)
            logger.debug(" SLABDRIVER \tGetSlices login %s \
                                            slice record %s" \
                                            %(login, fixed_slicerec_dict))
    
            
    
            #One slice can have multiple jobs
            
            leases_list = self.GetReservedNodes(username = login)
            #If no job is running or no job scheduled            
            if leases_list == [] :
                return [fixed_slicerec_dict]
            
            #Several jobs for one slice  
            for lease in leases_list : 
                slicerec_dict = {} 
                      
                
                #Check with OAR the status of the job if a job id is in 
                #the slice record 
                
            
                
                slicerec_dict['oar_job_id'] = lease['lease_id']
                #reserved_list = []
                #for reserved_node in lease['reserved_nodes']:
                    #reserved_list.append(reserved_node['hostname'])
                reserved_list = lease['reserved_nodes']
                #slicerec_dict.update({'node_ids':[lease['reserved_nodes'][n]['hostname'] for n in lease['reserved_nodes']]})
                slicerec_dict.update({'list_node_ids':{'hostname':reserved_list}})   
                slicerec_dict.update({'node_ids':lease['reserved_nodes']})
                #If the slice does not belong to senslab:
                if fixed_slicerec_dict:
                    slicerec_dict.update(fixed_slicerec_dict)
                    slicerec_dict.update({'hrn':\
                                    str(fixed_slicerec_dict['slice_hrn'])})
                    
    
                slicerec_dictlist.append(slicerec_dict)
                logger.debug("SLABDRIVER.PY  \tGetSlices  slicerec_dict %s slicerec_dictlist %s lease['reserved_nodes'] %s" %(slicerec_dict, slicerec_dictlist,lease['reserved_nodes'] ))
                
            logger.debug("SLABDRIVER.PY  \tGetSlices  RETURN slicerec_dictlist  %s"\
                                                        %(slicerec_dictlist))
                            
            return slicerec_dictlist
                
                
        else:
            
            slice_list = slab_dbsession.query(SliceSenslab).all()
            leases_list = self.GetReservedNodes()
            
          
            slicerec_dictlist = []
            return_slice_list = []
            for record in slice_list:
                return_slice_list.append(record.dump_sqlalchemyobj_to_dict())
                
            for fixed_slicerec_dict in return_slice_list:
                slicerec_dict = {} 
                owner = fixed_slicerec_dict['slice_hrn'].split(".")[1].split("_")[0] 
                for lease in leases_list:   
                    if owner == lease['user']:
                        slicerec_dict['oar_job_id'] = lease['lease_id']
                        reserved_list = []
                        
                        #for reserved_node in lease['reserved_nodes']:
                        logger.debug("SLABDRIVER.PY  \tGetSlices lease %s " %(lease ))
                            #reserved_list.append(reserved_node['hostname'])
                        reserved_list.extend(lease['reserved_nodes'])
                        #slicerec_dict.update({'node_ids':{'hostname':reserved_list}})    
                        #slicerec_dict.update({'node_ids':[lease['reserved_nodes'][n]['hostname'] for n in lease['reserved_nodes']]})
                        slicerec_dict.update({'node_ids':lease['reserved_nodes']})
                        slicerec_dict.update({'list_node_ids':{'hostname':reserved_list}}) 
                        slicerec_dict.update(fixed_slicerec_dict)
                        slicerec_dict.update({'hrn':\
                                    str(fixed_slicerec_dict['slice_hrn'])})
                        slicerec_dictlist.append(slicerec_dict)
            
            logger.debug("SLABDRIVER.PY  \tGetSlices RETURN slices %s \
                        slice_filter %s " %(return_slice_list, slice_filter))
        
        #if return_fields_list:
            #return_slice_list  = parse_filter(sliceslist, \
                                #slice_filter,'slice', return_fields_list)

        return slicerec_dictlist
        
    
    def testbed_name (self): return self.hrn
         
    # 'geni_request_rspec_versions' and 'geni_ad_rspec_versions' are mandatory
    def aggregate_version (self):
        version_manager = VersionManager()
        ad_rspec_versions = []
        request_rspec_versions = []
        for rspec_version in version_manager.versions:
            if rspec_version.content_type in ['*', 'ad']:
                ad_rspec_versions.append(rspec_version.to_dict())
            if rspec_version.content_type in ['*', 'request']:
                request_rspec_versions.append(rspec_version.to_dict()) 
        return {
            'testbed':self.testbed_name(),
            'geni_request_rspec_versions': request_rspec_versions,
            'geni_ad_rspec_versions': ad_rspec_versions,
            }
          
          
          
          
          
          
    ##
    # Convert SFA fields to PLC fields for use when registering up updating
    # registry record in the PLC database
    #
    # @param type type of record (user, slice, ...)
    # @param hrn human readable name
    # @param sfa_fields dictionary of SFA fields
    # @param slab_fields dictionary of PLC fields (output)

    def sfa_fields_to_slab_fields(self, sfa_type, hrn, record):


        slab_record = {}
        #for field in record:
        #    slab_record[field] = record[field]
 
        if sfa_type == "slice":
            #instantion used in get_slivers ? 
            if not "instantiation" in slab_record:
                slab_record["instantiation"] = "senslab-instantiated"
            #slab_record["hrn"] = hrn_to_pl_slicename(hrn)     
            #Unused hrn_to_pl_slicename because Slab's hrn already in the appropriate form SA 23/07/12
            slab_record["hrn"] = hrn 
            logger.debug("SLABDRIVER.PY sfa_fields_to_slab_fields \
                        slab_record %s  " %(slab_record['hrn']))
            if "url" in record:
                slab_record["url"] = record["url"]
            if "description" in record:
                slab_record["description"] = record["description"]
            if "expires" in record:
                slab_record["expires"] = int(record["expires"])
                
        #nodes added by OAR only and then imported to SFA
        #elif type == "node":
            #if not "hostname" in slab_record:
                #if not "hostname" in record:
                    #raise MissingSfaInfo("hostname")
                #slab_record["hostname"] = record["hostname"]
            #if not "model" in slab_record:
                #slab_record["model"] = "geni"
                
        #One authority only 
        #elif type == "authority":
            #slab_record["login_base"] = hrn_to_slab_login_base(hrn)

            #if not "name" in slab_record:
                #slab_record["name"] = hrn

            #if not "abbreviated_name" in slab_record:
                #slab_record["abbreviated_name"] = hrn

            #if not "enabled" in slab_record:
                #slab_record["enabled"] = True

            #if not "is_public" in slab_record:
                #slab_record["is_public"] = True

        return slab_record

    

            
    def __transforms_timestamp_into_date(self, xp_utc_timestamp = None):
        """ Transforms unix timestamp into valid OAR date format """
        
        #Used in case of a scheduled experiment (not immediate)
        #To run an XP immediately, don't specify date and time in RSpec 
        #They will be set to None. 
        if xp_utc_timestamp:
            #transform the xp_utc_timestamp into server readable time  
            xp_server_readable_date = datetime.fromtimestamp(int(\
                                xp_utc_timestamp)).strftime(self.time_format)

            return xp_server_readable_date
            
        else:
            return None
        
   

             
    def LaunchExperimentOnOAR(self, added_nodes, slice_name, \
                        lease_start_time, lease_duration, slice_user=None):
        lease_dict = {}
        lease_dict['lease_start_time'] = lease_start_time
        lease_dict['lease_duration'] = lease_duration
        lease_dict['added_nodes'] = added_nodes
        lease_dict['slice_name'] = slice_name
        lease_dict['slice_user'] = slice_user
        lease_dict['grain'] = self.GetLeaseGranularity()
        lease_dict['time_format'] = self.time_format
        
        def __create_job_structure_request_for_OAR(lease_dict):
            """ Creates the structure needed for a correct POST on OAR.
            Makes the timestamp transformation into the appropriate format.
            Sends the POST request to create the job with the resources in 
            added_nodes.
            
            """

            nodeid_list = []
            reqdict = {}
    
            
            reqdict['workdir'] = '/tmp'   
            reqdict['resource'] = "{network_address in ("   
    
            for node in lease_dict['added_nodes']: 
                logger.debug("\r\n \r\n OARrestapi \t __create_job_structure_request_for_OAR \
                                                                node %s" %(node))
    
                # Get the ID of the node 
                nodeid = node
                reqdict['resource'] += "'" + nodeid + "', "
                nodeid_list.append(nodeid)
    
            custom_length = len(reqdict['resource'])- 2
            reqdict['resource'] = reqdict['resource'][0:custom_length] + \
                                                ")}/nodes=" + str(len(nodeid_list))
    
            def __process_walltime(duration):
                """ Calculates the walltime in seconds from the duration in H:M:S
                    specified in the RSpec.
                    
                """
                if duration:
                    # Fixing the walltime by adding a few delays. 
                    # First put the walltime in seconds oarAdditionalDelay = 20;
                    #  additional delay for /bin/sleep command to
                    # take in account  prologue and epilogue scripts execution
                    # int walltimeAdditionalDelay = 240;  additional delay
                    desired_walltime = duration 
                    total_walltime = desired_walltime + 240 #+4 min Update SA 23/10/12
                    sleep_walltime = desired_walltime  # 0 sec added Update SA 23/10/12
                    walltime = []
                    #Put the walltime back in str form
                    #First get the hours
                    walltime.append(str(total_walltime / 3600))
                    total_walltime = total_walltime - 3600 * int(walltime[0])
                    #Get the remaining minutes
                    walltime.append(str(total_walltime / 60))
                    total_walltime = total_walltime - 60 * int(walltime[1])
                    #Get the seconds
                    walltime.append(str(total_walltime))
    
                else:
                    logger.log_exc(" __process_walltime duration null")
                    
                return walltime, sleep_walltime
                    

            walltime, sleep_walltime = \
                        __process_walltime(int(lease_dict['lease_duration'])*lease_dict['grain'])
    
    
            reqdict['resource'] += ",walltime=" + str(walltime[0]) + \
                                ":" + str(walltime[1]) + ":" + str(walltime[2])
            reqdict['script_path'] = "/bin/sleep " + str(sleep_walltime)
    
            #In case of a scheduled experiment (not immediate)
            #To run an XP immediately, don't specify date and time in RSpec 
            #They will be set to None.
            if lease_dict['lease_start_time'] is not '0':
                #Readable time accepted by OAR
                start_time = datetime.fromtimestamp(int(lease_dict['lease_start_time'])).\
                                                        strftime(lease_dict['time_format'])
                reqdict['reservation'] = start_time
            #If there is not start time, Immediate XP. No need to add special 
            # OAR parameters
    
    
            reqdict['type'] = "deploy" 
            reqdict['directory'] = ""
            reqdict['name'] = "SFA_" + lease_dict['slice_user']
    
            return reqdict
        
                                   
        #Create the request for OAR
        reqdict = __create_job_structure_request_for_OAR(lease_dict)
         # first step : start the OAR job and update the job 
        logger.debug("SLABDRIVER.PY \tLaunchExperimentOnOAR reqdict %s\
                             \r\n "  %(reqdict))  
       
        answer = self.oar.POSTRequestToOARRestAPI('POST_job', \
                                                            reqdict, slice_user)
        logger.debug("SLABDRIVER \tLaunchExperimentOnOAR jobid   %s " %(answer))
        try:       
            jobid = answer['id']
        except KeyError:
            logger.log_exc("SLABDRIVER \tLaunchExperimentOnOAR \
                                Impossible to create job  %s "  %(answer))
            return
        
        
        def __configure_experiment(jobid, added_nodes):
            # second step : configure the experiment
            # we need to store the nodes in a yaml (well...) file like this :
            # [1,56,23,14,45,75] with name /tmp/sfa<jobid>.json
            job_file = open('/tmp/sfa/'+ str(jobid) + '.json', 'w')
            job_file.write('[')
            job_file.write(str(added_nodes[0].strip('node')))
            for node in added_nodes[1:len(added_nodes)] :
                job_file.write(', '+ node.strip('node'))
            job_file.write(']')
            job_file.close()
            return 
        
        def __launch_senslab_experiment(jobid):   
            # third step : call the senslab-experiment wrapper
            #command= "java -jar target/sfa-1.0-jar-with-dependencies.jar 
            # "+str(jobid)+" "+slice_user
            javacmdline = "/usr/bin/java"
            jarname = \
                "/opt/senslabexperimentwrapper/sfa-1.0-jar-with-dependencies.jar"
            #ret=subprocess.check_output(["/usr/bin/java", "-jar", ", \
                                                        #str(jobid), slice_user])
            output = subprocess.Popen([javacmdline, "-jar", jarname, str(jobid), \
                                slice_user],stdout=subprocess.PIPE).communicate()[0]
    
            logger.debug("SLABDRIVER \t __configure_experiment wrapper returns%s " \
                                                                    %(output))
            return 
        
        
        
        if jobid :
            logger.debug("SLABDRIVER \tLaunchExperimentOnOAR jobid %s \
                    added_nodes %s slice_user %s" %(jobid, added_nodes, slice_user))
            
        
            __configure_experiment(jobid, added_nodes)
            __launch_senslab_experiment(jobid) 
            
        return
        
    def AddLeases(self, hostname_list, slice_record, lease_start_time, lease_duration):
        logger.debug("SLABDRIVER \r\n \r\n \t AddLeases hostname_list %s  \
                slice_record %s lease_start_time %s lease_duration %s  "\
                 %( hostname_list, slice_record , lease_start_time, \
                 lease_duration))

        tmp = slice_record['reg-researchers'][0].split(".")
        username = tmp[(len(tmp)-1)]
        self.LaunchExperimentOnOAR(hostname_list, slice_record['slice_hrn'], lease_start_time, lease_duration, username)
        start_time = datetime.fromtimestamp(int(lease_start_time)).strftime(self.time_format)
        logger.debug("SLABDRIVER \t AddLeases hostname_list start_time %s " %(start_time))
        
        return
    
    
    #Delete the jobs from job_senslab table
    def DeleteSliceFromNodes(self, slice_record):

        self.DeleteJobs(slice_record['oar_job_id'], slice_record['hrn'])
        return   
    
 
    def GetLeaseGranularity(self):
        """ Returns the granularity of Senslab testbed.
        OAR returns seconds for experiments duration.
        Defined in seconds. """
        
        grain = 60 
        return grain
    
    def GetLeases(self, lease_filter_dict=None):
        unfiltered_reservation_list = self.GetReservedNodes()
        
        ##Synchronize slice_table of sfa senslab db
        #self.synchronize_oar_and_slice_table(unfiltered_reservation_list)
        
        reservation_list = []
        #Find the slice associated with this user senslab ldap uid
        logger.debug(" SLABDRIVER.PY \tGetLeases ")
        #Create user dict first to avoir looking several times for
        #the same user in LDAP SA 27/07/12
        resa_user_dict = {}
        for resa in unfiltered_reservation_list:
            logger.debug("SLABDRIVER \tGetLeases USER %s"\
                                            %(resa['user']))    
            if resa['user'] not in resa_user_dict: 
                logger.debug("SLABDRIVER \tGetLeases userNOTIN ")
                ldap_info = self.ldap.LdapSearch('(uid='+resa['user']+')')
                ldap_info = ldap_info[0][1]
                user = dbsession.query(RegUser).filter_by(email = \
                                                    ldap_info['mail'][0]).first()
                #Separated in case user not in database : record_id not defined SA 17/07//12
                query_slice_info = slab_dbsession.query(SliceSenslab).filter_by(record_id_user = user.record_id)
                if query_slice_info:
                    slice_info = query_slice_info.first()
                else:
                    slice_info = None
                    
                resa_user_dict[resa['user']] = {}
                resa_user_dict[resa['user']]['ldap_info'] = user
                resa_user_dict[resa['user']]['slice_info'] = slice_info
 
        logger.debug("SLABDRIVER \tGetLeases resa_user_dict %s"\
                                            %(resa_user_dict))         
        for resa in unfiltered_reservation_list:
            
            
            #Put the slice_urn  
            resa['slice_hrn'] = resa_user_dict[resa['user']]['slice_info'].slice_hrn
            resa['slice_id'] = hrn_to_urn(resa['slice_hrn'], 'slice')    
            #Put the slice_urn 
            #resa['slice_id'] = hrn_to_urn(slice_info.slice_hrn, 'slice')
            resa['component_id_list'] = []
            #Transform the hostnames into urns (component ids)
            for node in resa['reserved_nodes']:
                #resa['component_id_list'].append(hostname_to_urn(self.hrn, \
                         #self.root_auth, node['hostname']))
                slab_xrn = slab_xrn_object(self.root_auth, node)
                resa['component_id_list'].append(slab_xrn.urn)
        
        #Filter the reservation list if necessary
        #Returns all the leases associated with a given slice
        if lease_filter_dict:
            logger.debug("SLABDRIVER \tGetLeases lease_filter_dict %s"\
                                            %(lease_filter_dict))
            for resa in unfiltered_reservation_list:
                if lease_filter_dict['name'] == resa['slice_hrn']:
                    reservation_list.append(resa)
        else:
            reservation_list = unfiltered_reservation_list
            
        logger.debug(" SLABDRIVER.PY \tGetLeases reservation_list %s"\
                                                    %(reservation_list))
        return reservation_list
            
    def augment_records_with_testbed_info (self, sfa_records):
        return self.fill_record_info (sfa_records)
    
    def fill_record_info(self, record_list):
        """
        Given a SFA record, fill in the senslab specific and SFA specific
        fields in the record. 
        """
                    
        logger.debug("SLABDRIVER \tfill_record_info records %s " %(record_list))
        if not isinstance(record_list, list):
            record_list = [record_list]
            
        try:
            for record in record_list:
                #If the record is a SFA slice record, then add information 
                #about the user of this slice. This kind of 
                #information is in the Senslab's DB.
                if str(record['type']) == 'slice':
                    #Get slab slice record.
                    recslice_list = self.GetSlices(slice_filter = \
                                                str(record['hrn']),\
                                                slice_filter_type = 'slice_hrn')
                    
                    recuser = dbsession.query(RegRecord).filter_by(record_id = \
                                            recslice_list[0]['record_id_user']).first()
                    logger.debug("SLABDRIVER \tfill_record_info TYPE SLICE RECUSER %s " %(recuser))
                    record.update({'PI':[recuser.hrn],
                                'researcher': [recuser.hrn],
                                'name':record['hrn'], 
                                'oar_job_id':[],
                                'node_ids': [],
                                'person_ids':[recslice_list[0]['record_id_user']],
                                'geni_urn':'',  #For client_helper.py compatibility
                                'keys':'',  #For client_helper.py compatibility
                                'key_ids':''})  #For client_helper.py compatibility
                    
                    try:
                        for rec in recslice_list:
                            record['oar_job_id'].append(rec['oar_job_id'])
                            record['node_ids'] = [ self.root_auth + hostname for hostname in rec['node_ids']]
                    except KeyError:
                        pass

                    logger.debug( "SLABDRIVER.PY \t fill_record_info SLICE \
                                                    recslice_list  %s \r\n \t RECORD %s \r\n \r\n" %(recslice_list,record)) 
                if str(record['type']) == 'user':
                    #The record is a SFA user record.
                    #Get the information about his slice from Senslab's DB
                    #and add it to the user record.
                    recslice_list = self.GetSlices(\
                            slice_filter = record['record_id'],\
                            slice_filter_type = 'record_id_user')
                                            
                    logger.debug( "SLABDRIVER.PY \t fill_record_info TYPE USER \
                                                recslice_list %s \r\n \t RECORD %s \r\n" %(recslice_list , record)) 
                    #Append slice record in records list, 
                    #therefore fetches user and slice info again(one more loop)
                    #Will update PIs and researcher for the slice
                    recuser = dbsession.query(RegRecord).filter_by(record_id = \
                                                recslice_list[0]['record_id_user']).first()
                    logger.debug( "SLABDRIVER.PY \t fill_record_info USER  \
                                                recuser %s \r\n \r\n" %(recuser)) 
                    recslice = {}
                    recslice = recslice_list[0]
                    recslice.update({'PI':[recuser.hrn],
                        'researcher': [recuser.hrn],
                        'name':record['hrn'], 
                        'node_ids': [],
                        'oar_job_id': [],
                        'person_ids':[recslice_list[0]['record_id_user']]}) 
                    try:
                        for rec in recslice_list:
                            recslice['oar_job_id'].append(rec['oar_job_id'])
                    except KeyError:
                        pass
                            
                    recslice.update({'type':'slice', \
                                                'hrn':recslice_list[0]['slice_hrn']})


                    #GetPersons takes [] as filters 
                    #user_slab = self.GetPersons([{'hrn':recuser.hrn}])
                    user_slab = self.GetPersons([record])
    
                    
                    record.update(user_slab[0])
                    #For client_helper.py compatibility
                    record.update( { 'geni_urn':'',
                    'keys':'',
                    'key_ids':'' })                
                    record_list.append(recslice)
                    
                    logger.debug("SLABDRIVER.PY \tfill_record_info ADDING SLICE\
                                INFO TO USER records %s" %(record_list)) 
                logger.debug("SLABDRIVER.PY \tfill_record_info END \
                                #record %s \r\n \r\n " %(record))     

        except TypeError, error:
            logger.log_exc("SLABDRIVER \t fill_record_info  EXCEPTION %s"\
                                                                     %(error))
        #logger.debug("SLABDRIVER.PY \t fill_record_info ENDENDEND ")
                              
        return
        
        #self.fill_record_slab_info(records)
    
    
        

    
    #TODO Update membership?    update_membership_list SA 05/07/12
    #def update_membership_list(self, oldRecord, record, listName, addFunc, \
                                                                #delFunc):
        ## get a list of the HRNs tht are members of the old and new records
        #if oldRecord:
            #oldList = oldRecord.get(listName, [])
        #else:
            #oldList = []     
        #newList = record.get(listName, [])

        ## if the lists are the same, then we don't have to update anything
        #if (oldList == newList):
            #return

        ## build a list of the new person ids, by looking up each person to get
        ## their pointer
        #newIdList = []
        #table = SfaTable()
        #records = table.find({'type': 'user', 'hrn': newList})
        #for rec in records:
            #newIdList.append(rec['pointer'])

        ## build a list of the old person ids from the person_ids field 
        #if oldRecord:
            #oldIdList = oldRecord.get("person_ids", [])
            #containerId = oldRecord.get_pointer()
        #else:
            ## if oldRecord==None, then we are doing a Register, instead of an
            ## update.
            #oldIdList = []
            #containerId = record.get_pointer()

    ## add people who are in the new list, but not the oldList
        #for personId in newIdList:
            #if not (personId in oldIdList):
                #addFunc(self.plauth, personId, containerId)

        ## remove people who are in the old list, but not the new list
        #for personId in oldIdList:
            #if not (personId in newIdList):
                #delFunc(self.plauth, personId, containerId)

    #def update_membership(self, oldRecord, record):
       
        #if record.type == "slice":
            #self.update_membership_list(oldRecord, record, 'researcher',
                                        #self.users.AddPersonToSlice,
                                        #self.users.DeletePersonFromSlice)
        #elif record.type == "authority":
            ## xxx TODO
            #pass

### thierry
# I don't think you plan on running a component manager at this point
# let me clean up the mess of ComponentAPI that is deprecated anyways


#TODO FUNCTIONS SECTION 04/07/2012 SA

    #TODO : Is UnBindObjectFromPeer still necessary ? Currently does nothing
    #04/07/2012 SA
    def UnBindObjectFromPeer(self, auth, object_type, object_id, shortname):
        """ This method is a hopefully temporary hack to let the sfa correctly
        detach the objects it creates from a remote peer object. This is 
        needed so that the sfa federation link can work in parallel with 
        RefreshPeer, as RefreshPeer depends on remote objects being correctly 
        marked.
        Parameters:
        auth : struct, API authentication structure
            AuthMethod : string, Authentication method to use 
        object_type : string, Object type, among 'site','person','slice',
        'node','key'
        object_id : int, object_id
        shortname : string, peer shortname 
        FROM PLC DOC
        
        """
        logger.warning("SLABDRIVER \tUnBindObjectFromPeer EMPTY-\
                        DO NOTHING \r\n ")
        return 
    
    #TODO Is BindObjectToPeer still necessary ? Currently does nothing 
    #04/07/2012 SA
    def BindObjectToPeer(self, auth, object_type, object_id, shortname=None, \
                                                    remote_object_id=None):
        """This method is a hopefully temporary hack to let the sfa correctly 
        attach the objects it creates to a remote peer object. This is needed 
        so that the sfa federation link can work in parallel with RefreshPeer, 
        as RefreshPeer depends on remote objects being correctly marked.
        Parameters:
        shortname : string, peer shortname 
        remote_object_id : int, remote object_id, set to 0 if unknown 
        FROM PLC API DOC
        
        """
        logger.warning("SLABDRIVER \tBindObjectToPeer EMPTY - DO NOTHING \r\n ")
        return
    
    #TODO UpdateSlice 04/07/2012 SA
    #Funciton should delete and create another job since oin senslab slice=job
    def UpdateSlice(self, auth, slice_id_or_name, slice_fields=None):    
        """Updates the parameters of an existing slice with the values in 
        slice_fields.
        Users may only update slices of which they are members. 
        PIs may update any of the slices at their sites, or any slices of 
        which they are members. Admins may update any slice.
        Only PIs and admins may update max_nodes. Slices cannot be renewed
        (by updating the expires parameter) more than 8 weeks into the future.
         Returns 1 if successful, faults otherwise.
        FROM PLC API DOC
        
        """  
        logger.warning("SLABDRIVER UpdateSlice EMPTY - DO NOTHING \r\n ")
        return
    
    #TODO UpdatePerson 04/07/2012 SA
    def UpdatePerson(self, auth, person_id_or_email, person_fields=None):
        """Updates a person. Only the fields specified in person_fields 
        are updated, all other fields are left untouched.
        Users and techs can only update themselves. PIs can only update
        themselves and other non-PIs at their sites.
        Returns 1 if successful, faults otherwise.
        FROM PLC API DOC
         
        """
        logger.warning("SLABDRIVER UpdatePerson EMPTY - DO NOTHING \r\n ")
        return
    
    #TODO GetKeys 04/07/2012 SA
    def GetKeys(self, auth, key_filter=None, return_fields=None):
        """Returns an array of structs containing details about keys. 
        If key_filter is specified and is an array of key identifiers, 
        or a struct of key attributes, only keys matching the filter 
        will be returned. If return_fields is specified, only the 
        specified details will be returned.

        Admin may query all keys. Non-admins may only query their own keys.
        FROM PLC API DOC
        
        """
        logger.warning("SLABDRIVER  GetKeys EMPTY - DO NOTHING \r\n ")
        return
    
    #TODO DeleteKey 04/07/2012 SA
    def DeleteKey(self, auth, key_id):
        """  Deletes a key.
         Non-admins may only delete their own keys.
         Returns 1 if successful, faults otherwise.
         FROM PLC API DOC
         
        """
        logger.warning("SLABDRIVER  DeleteKey EMPTY - DO NOTHING \r\n ")
        return

    
    #TODO : Check rights to delete person 
    def DeletePerson(self, auth, person_record):
        """ Disable an existing account in senslab LDAP.
        Users and techs can only delete themselves. PIs can only 
        delete themselves and other non-PIs at their sites. 
        ins can delete anyone.
        Returns 1 if successful, faults otherwise.
        FROM PLC API DOC
        
        """
        #Disable user account in senslab LDAP
        ret = self.ldap.LdapMarkUserAsDeleted(person_record)
        logger.warning("SLABDRIVER DeletePerson %s " %(person_record))
        return ret
    
    #TODO Check DeleteSlice, check rights 05/07/2012 SA
    def DeleteSlice(self, auth, slice_record):
        """ Deletes the specified slice.
         Senslab : Kill the job associated with the slice if there is one
         using DeleteSliceFromNodes.
         Updates the slice record in slab db to remove the slice nodes.
         
         Users may only delete slices of which they are members. PIs may 
         delete any of the slices at their sites, or any slices of which 
         they are members. Admins may delete any slice.
         Returns 1 if successful, faults otherwise.
         FROM PLC API DOC
        
        """
        self.DeleteSliceFromNodes(slice_record)
        logger.warning("SLABDRIVER DeleteSlice %s "%(slice_record))
        return
    
    #TODO AddPerson 04/07/2012 SA
    #def AddPerson(self, auth,  person_fields=None): 
    def AddPerson(self, record):#TODO fixing 28/08//2012 SA
        """Adds a new account. Any fields specified in records are used, 
        otherwise defaults are used.
        Accounts are disabled by default. To enable an account, 
        use UpdatePerson().
        Returns the new person_id (> 0) if successful, faults otherwise. 
        FROM PLC API DOC
        
        """
        ret = self.ldap.LdapAddUser(record)
        logger.warning("SLABDRIVER AddPerson return code %s \r\n ", ret)
        return
    
    #TODO AddPersonToSite 04/07/2012 SA
    def AddPersonToSite (self, auth, person_id_or_email, \
                                                site_id_or_login_base=None):
        """  Adds the specified person to the specified site. If the person is 
        already a member of the site, no errors are returned. Does not change 
        the person's primary site.
        Returns 1 if successful, faults otherwise.
        FROM PLC API DOC
        
        """
        logger.warning("SLABDRIVER AddPersonToSite EMPTY - DO NOTHING \r\n ")
        return
    
    #TODO AddRoleToPerson : Not sure if needed in senslab 04/07/2012 SA
    def AddRoleToPerson(self, auth, role_id_or_name, person_id_or_email):
        """Grants the specified role to the person.
        PIs can only grant the tech and user roles to users and techs at their 
        sites. Admins can grant any role to any user.
        Returns 1 if successful, faults otherwise.
        FROM PLC API DOC
        
        """
        logger.warning("SLABDRIVER AddRoleToPerson EMPTY - DO NOTHING \r\n ")
        return
    
    #TODO AddPersonKey 04/07/2012 SA
    def AddPersonKey(self, auth, person_id_or_email, key_fields=None):
        """Adds a new key to the specified account.
        Non-admins can only modify their own keys.
        Returns the new key_id (> 0) if successful, faults otherwise.
        FROM PLC API DOC
        
        """
        logger.warning("SLABDRIVER AddPersonKey EMPTY - DO NOTHING \r\n ")
        return
    
    def DeleteLeases(self, leases_id_list, slice_hrn ):
        for job_id in leases_id_list:
            self.DeleteJobs(job_id, slice_hrn)
        
        logger.debug("SLABDRIVER DeleteLeases leases_id_list %s slice_hrn %s \
                \r\n " %(leases_id_list, slice_hrn))
        return 
