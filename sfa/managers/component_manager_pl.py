import os
import xmlrpclib

from sfa.util.faults import *
from sfa.util.plxrn import PlXrn
from sfa.util.sfaticket import SfaTicket
from sfa.util.version import version_core

def GetVersion(api):
    return version_core({'interface':'component',
                         'testbed':'myplc'})

def init_server():
    from sfa.server import sfa_component_setup
    # get current trusted gids
    try:
        sfa_component_setup.get_trusted_certs()
    except:
        # our keypair may be old, try refreshing
        sfa_component_setup.get_node_key()
        sfa_component_setup.get_credential(force=True)
        sfa_component_setup.get_trusted_certs()

def slice_status(api, slice_xrn, creds):
    result = {}
    result['geni_urn'] = slice_xrn
    result['geni_status'] = 'unknown'
    result['geni_resources'] = {}
    return result
           
def start_slice(api, xrn, creds):
    slicename = PlXrn(xrn, type='slice').pl_slicename()
    api.nodemanger.Start(slicename)

def stop_slice(api, xrn, creds):
    slicename = PlXrn(xrn, type='slice').pl_slicename()
    api.nodemanager.Stop(slicename)

def delete_slice(api, xrn, creds):
    slicename = PlXrn(xrn, type='slice').pl_slicename()
    api.nodemanager.Destroy(slicename)

def reset_slice(api, xrn):
    slicename = PlXrn(xrn, type='slice').pl_slicename()
    if not api.sliver_exists(slicename):
        raise SliverDoesNotExist(slicename)
    api.nodemanager.ReCreate(slicename)
 
def get_slices(api):
    # this returns a tuple, the data we want is at index 1 
    xids = api.nodemanager.GetXIDs()
    # unfortunately the data we want is given to us as 
    # a string but we really want it as a dict
    # lets eval it
    slices = eval(xids[1])
    return slices.keys()

def redeem_ticket(api, ticket_string):
    ticket = SfaTicket(string=ticket_string)
    ticket.decode()
    hrn = ticket.attributes['slivers'][0]['hrn']
    slicename = PlXrn (hrn).pl_slicename()
    if not api.sliver_exists(slicename):
        raise SliverDoesNotExist(slicename)

    # convert ticket to format nm is used to
    nm_ticket = xmlrpclib.dumps((ticket.attributes,), methodresponse=True)
    api.nodemanager.AdminTicket(nm_ticket)
    

