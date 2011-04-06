import datetime
import time
import traceback
import sys
import re
from types import StringTypes

from sfa.util.faults import *
from sfa.util.xrn import get_authority, hrn_to_urn, urn_to_hrn, Xrn
from sfa.util.plxrn import slicename_to_hrn, hrn_to_pl_slicename, hostname_to_urn
from sfa.util.rspec import *
from sfa.util.specdict import *
from sfa.util.record import SfaRecord
from sfa.util.policy import Policy
from sfa.util.record import *
from sfa.util.sfaticket import SfaTicket
from sfa.plc.slices import Slices
from sfa.trust.credential import Credential
import sfa.plc.peers as peers
from sfa.plc.network import *
from sfa.plc.api import SfaAPI
from sfa.plc.slices import *
from sfa.util.version import version_core
from sfa.util.sfatime import utcparse
from sfa.util.callids import Callids

def GetVersion(api):
    xrn=Xrn(api.hrn)
    return version_core({'interface':'aggregate',
                         'testbed':'myplc',
                         'hrn':xrn.get_hrn(),
                         })

def __get_registry_objects(slice_xrn, creds, users):
    """

    """
    hrn, type = urn_to_hrn(slice_xrn)

    hrn_auth = get_authority(hrn)

    # Build up objects that an SFA registry would return if SFA
    # could contact the slice's registry directly
    reg_objects = None

    if users:
        # dont allow special characters in the site login base
        #only_alphanumeric = re.compile('[^a-zA-Z0-9]+')
        #login_base = only_alphanumeric.sub('', hrn_auth[:20]).lower()
        slicename = hrn_to_pl_slicename(hrn)
        login_base = slicename.split('_')[0]
        reg_objects = {}
        site = {}
        site['site_id'] = 0
        site['name'] = 'geni.%s' % login_base 
        site['enabled'] = True
        site['max_slices'] = 100

        # Note:
        # Is it okay if this login base is the same as one already at this myplc site?
        # Do we need uniqueness?  Should use hrn_auth instead of just the leaf perhaps?
        site['login_base'] = login_base
        site['abbreviated_name'] = login_base
        site['max_slivers'] = 1000
        reg_objects['site'] = site

        slice = {}
        
        extime = Credential(string=creds[0]).get_expiration()
        # If the expiration time is > 60 days from now, set the expiration time to 60 days from now
        if extime > datetime.datetime.utcnow() + datetime.timedelta(days=60):
            extime = datetime.datetime.utcnow() + datetime.timedelta(days=60)
        slice['expires'] = int(time.mktime(extime.timetuple()))
        slice['hrn'] = hrn
        slice['name'] = hrn_to_pl_slicename(hrn)
        slice['url'] = hrn
        slice['description'] = hrn
        slice['pointer'] = 0
        reg_objects['slice_record'] = slice

        reg_objects['users'] = {}
        for user in users:
            user['key_ids'] = []
            hrn, _ = urn_to_hrn(user['urn'])
            user['email'] = hrn_to_pl_slicename(hrn) + "@geni.net"
            user['first_name'] = hrn
            user['last_name'] = hrn
            reg_objects['users'][user['email']] = user

        return reg_objects

def __get_hostnames(nodes):
    hostnames = []
    for node in nodes:
        hostnames.append(node.hostname)
    return hostnames

def slice_status(api, slice_xrn, creds):
    hrn, type = urn_to_hrn(slice_xrn)
    # find out where this slice is currently running
    api.logger.info(hrn)
    slicename = hrn_to_pl_slicename(hrn)
    
    slices = api.plshell.GetSlices(api.plauth, [slicename], ['node_ids','person_ids','name','expires'])
    if len(slices) == 0:        
        raise Exception("Slice %s not found (used %s as slicename internally)" % slice_xrn, slicename)
    slice = slices[0]
    
    nodes = api.plshell.GetNodes(api.plauth, slice['node_ids'],
                                    ['hostname', 'site_id', 'boot_state', 'last_contact'])
    site_ids = [node['site_id'] for node in nodes]
    sites = api.plshell.GetSites(api.plauth, site_ids, ['site_id', 'login_base'])
    sites_dict = {}
    for site in sites:
        sites_dict[site['site_id']] = site['login_base']

    # XX remove me
    #api.logger.info(slice_xrn)
    #api.logger.info(slice)
    #api.logger.info(nodes)
    # XX remove me

    result = {}
    top_level_status = 'unknown'
    if nodes:
        top_level_status = 'ready'
    result['geni_urn'] = Xrn(slice_xrn, 'slice').get_urn()
    result['pl_login'] = slice['name']
    result['pl_expires'] = datetime.datetime.fromtimestamp(slice['expires']).ctime()
    
    resources = []
    for node in nodes:
        res = {}
        res['pl_hostname'] = node['hostname']
        res['pl_boot_state'] = node['boot_state']
        res['pl_last_contact'] = node['last_contact']
        if not node['last_contact'] is None:
            res['pl_last_contact'] = datetime.datetime.fromtimestamp(node['last_contact']).ctime()
        res['geni_urn'] = hostname_to_urn(api.hrn, sites_dict[node['site_id']], node['hostname'])
        if node['boot_state'] == 'boot':
            res['geni_status'] = 'ready'
        else:
            res['geni_status'] = 'failed'
            top_level_staus = 'failed' 
            
        res['geni_error'] = ''

        resources.append(res)
        
    result['geni_status'] = top_level_status
    result['geni_resources'] = resources
    # XX remove me
    #api.logger.info(result)
    # XX remove me
    return result

def create_slice(api, slice_xrn, creds, rspec, users):
    """
    Create the sliver[s] (slice) at this aggregate.    
    Verify HRN and initialize the slice record in PLC if necessary.
    """

    reg_objects = __get_registry_objects(slice_xrn, creds, users)

    hrn, type = urn_to_hrn(slice_xrn)
    peer = None
    slices = Slices(api)
    peer = slices.get_peer(hrn)
    sfa_peer = slices.get_sfa_peer(hrn)
    registry = api.registries[api.hrn]
    credential = api.getCredential()
    site_id, remote_site_id = slices.verify_site(registry, credential, hrn, 
                                                 peer, sfa_peer, reg_objects)

    slice_record = slices.verify_slice(registry, credential, hrn, site_id, 
                                remote_site_id, peer, sfa_peer, reg_objects)
     
    network = Network(api)

    slice = network.get_slice(api, hrn)
    slice.peer_id = slice_record['peer_slice_id']
    current = __get_hostnames(slice.get_nodes())
    
    network.addRSpec(rspec, api.config.SFA_AGGREGATE_RSPEC_SCHEMA)
    request = __get_hostnames(network.nodesWithSlivers())
    
    # remove nodes not in rspec
    deleted_nodes = list(set(current).difference(request))

    # add nodes from rspec
    added_nodes = list(set(request).difference(current))

    try:
        if peer:
            api.plshell.UnBindObjectFromPeer(api.plauth, 'slice', slice.id, peer)

        api.plshell.AddSliceToNodes(api.plauth, slice.name, added_nodes) 
        api.plshell.DeleteSliceFromNodes(api.plauth, slice.name, deleted_nodes)

        network.updateSliceTags()

    finally:
        if peer:
            api.plshell.BindObjectToPeer(api.plauth, 'slice', slice.id, peer, 
                                         slice.peer_id)

    # print network.toxml()

    return True


def renew_slice(api, xrn, creds, expiration_time):
    hrn, type = urn_to_hrn(xrn)
    slicename = hrn_to_pl_slicename(hrn)
    slices = api.plshell.GetSlices(api.plauth, {'name': slicename}, ['slice_id'])
    if not slices:
        raise RecordNotFound(hrn)
    slice = slices[0]
    requested_time = utcparse(expiration_time)
    record = {'expires': int(time.mktime(requested_time.timetuple()))}
    api.plshell.UpdateSlice(api.plauth, slice['slice_id'], record)
    return 1         

def start_slice(api, xrn, creds):
    hrn, type = urn_to_hrn(xrn)
    slicename = hrn_to_pl_slicename(hrn)
    slices = api.plshell.GetSlices(api.plauth, {'name': slicename}, ['slice_id'])
    if not slices:
        raise RecordNotFound(hrn)
    slice_id = slices[0]['slice_id']
    slice_tags = api.plshell.GetSliceTags(api.plauth, {'slice_id': slice_id, 'tagname': 'enabled'}, ['slice_tag_id'])
    # just remove the tag if it exists
    if slice_tags:
        api.plshell.DeleteSliceTag(api.plauth, slice_tags[0]['slice_tag_id'])

    return 1
 
def stop_slice(api, xrn, creds):
    hrn, type = urn_to_hrn(xrn)
    slicename = hrn_to_pl_slicename(hrn)
    slices = api.plshell.GetSlices(api.plauth, {'name': slicename}, ['slice_id'])
    if not slices:
        raise RecordNotFound(hrn)
    slice_id = slices[0]['slice_id']
    slice_tags = api.plshell.GetSliceTags(api.plauth, {'slice_id': slice_id, 'tagname': 'enabled'})
    if not slice_tags:
        api.plshell.AddSliceTag(api.plauth, slice_id, 'enabled', '0')
    elif slice_tags[0]['value'] != "0":
        tag_id = attributes[0]['slice_tag_id']
        api.plshell.UpdateSliceTag(api.plauth, tag_id, '0')
    return 1

def reset_slice(api, xrn):
    # XX not implemented at this interface
    return 1

def delete_slice(api, xrn, creds):
    hrn, type = urn_to_hrn(xrn)
    slicename = hrn_to_pl_slicename(hrn)
    slices = api.plshell.GetSlices(api.plauth, {'name': slicename})
    if not slices:
        return 1
    slice = slices[0]

    # determine if this is a peer slice
    peer = peers.get_peer(api, hrn)
    try:
        if peer:
            api.plshell.UnBindObjectFromPeer(api.plauth, 'slice', slice['slice_id'], peer)
        api.plshell.DeleteSliceFromNodes(api.plauth, slicename, slice['node_ids'])
    finally:
        if peer:
            api.plshell.BindObjectToPeer(api.plauth, 'slice', slice['slice_id'], peer, slice['peer_slice_id'])
    return 1

def get_slices(api, creds):
    # look in cache first
    if api.cache:
        slices = api.cache.get('slices')
        if slices:
            return slices

    # get data from db 
    slices = api.plshell.GetSlices(api.plauth, {'peer_id': None}, ['name'])
    slice_hrns = [slicename_to_hrn(api.hrn, slice['name']) for slice in slices]
    slice_urns = [hrn_to_urn(slice_hrn, 'slice') for slice_hrn in slice_hrns]

    # cache the result
    if api.cache:
        api.cache.add('slices', slice_urns) 

    return slice_urns
    
# xxx Thierry : caching at the aggregate level sounds wrong...
caching=True
def get_rspec(api, creds, options,call_id):
    if not Callids().should_handle_call_id(call_id): return ""
    # get slice's hrn from options
    xrn = options.get('geni_slice_urn', '')
    (hrn, type) = urn_to_hrn(xrn)

    # look in cache first
    if caching and api.cache and not xrn:
        rspec = api.cache.get('nodes')
        if rspec:
            api.logger.info("aggregate.get_rspec: returning cached value for hrn %s"%hrn)
            return rspec 

    network = Network(api)
    if (hrn):
        if network.get_slice(api, hrn):
            network.addSlice()

    rspec = network.toxml()

    # cache the result
    if caching and api.cache and not xrn:
        api.cache.add('nodes', rspec)

    return rspec


def get_ticket(api, xrn, creds, rspec, users):

    reg_objects = __get_registry_objects(xrn, creds, users)

    slice_hrn, type = urn_to_hrn(xrn)
    slices = Slices(api)
    peer = slices.get_peer(slice_hrn)
    sfa_peer = slices.get_sfa_peer(slice_hrn)

    # get the slice record
    registry = api.registries[api.hrn]
    credential = api.getCredential()
    records = registry.Resolve(xrn, credential)

    # similar to create_slice, we must verify that the required records exist
    # at this aggregate before we can issue a ticket
    site_id, remote_site_id = slices.verify_site(registry, credential, slice_hrn,
                                                 peer, sfa_peer, reg_objects)
    slice = slices.verify_slice(registry, credential, slice_hrn, site_id,
                                remote_site_id, peer, sfa_peer, reg_objects)

    # make sure we get a local slice record
    record = None
    for tmp_record in records:
        if tmp_record['type'] == 'slice' and \
           not tmp_record['peer_authority']:
            record = SliceRecord(dict=tmp_record)
    if not record:
        raise RecordNotFound(slice_hrn)

    # get sliver info
    slivers = Slices(api).get_slivers(slice_hrn)
    if not slivers:
        raise SliverDoesNotExist(slice_hrn)

    # get initscripts
    initscripts = []
    data = {
        'timestamp': int(time.time()),
        'initscripts': initscripts,
        'slivers': slivers
    }

    # create the ticket
    object_gid = record.get_gid_object()
    new_ticket = SfaTicket(subject = object_gid.get_subject())
    new_ticket.set_gid_caller(api.auth.client_gid)
    new_ticket.set_gid_object(object_gid)
    new_ticket.set_issuer(key=api.key, subject=api.hrn)
    new_ticket.set_pubkey(object_gid.get_pubkey())
    new_ticket.set_attributes(data)
    new_ticket.set_rspec(rspec)
    #new_ticket.set_parent(api.auth.hierarchy.get_auth_ticket(auth_hrn))
    new_ticket.encode()
    new_ticket.sign()

    return new_ticket.save_to_string(save_parents=True)



def main():
    api = SfaAPI()
    """
    rspec = get_rspec(api, "plc.princeton.sapan", None, 'pl_test_sapan')
    #rspec = get_rspec(api, "plc.princeton.coblitz", None, 'pl_test_coblitz')
    #rspec = get_rspec(api, "plc.pl.sirius", None, 'pl_test_sirius')
    print rspec
    """
    f = open(sys.argv[1])
    xml = f.read()
    f.close()
    create_slice(api, "plc.princeton.sapan", xml)

if __name__ == "__main__":
    main()
