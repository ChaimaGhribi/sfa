#
import sys
import time,datetime
from StringIO import StringIO
from types import StringTypes
from copy import deepcopy
from copy import copy
from lxml import etree

from sfa.util.sfalogging import logger
from sfa.util.rspecHelper import merge_rspecs
from sfa.util.xrn import Xrn, urn_to_hrn, hrn_to_urn
from sfa.util.plxrn import hrn_to_pl_slicename
from sfa.util.rspec import *
from sfa.util.specdict import *
from sfa.util.faults import *
from sfa.util.record import SfaRecord
from sfa.rspecs.rspec_converter import RSpecConverter
from sfa.rspecs.version_manager import VersionManager
from sfa.rspecs.rspec import RSpec 
from sfa.util.policy import Policy
from sfa.util.prefixTree import prefixTree
from sfa.util.sfaticket import *
from sfa.trust.credential import Credential
from sfa.util.threadmanager import ThreadManager
import sfa.util.xmlrpcprotocol as xmlrpcprotocol     
import sfa.plc.peers as peers
from sfa.util.version import version_core
from sfa.util.callids import Callids


def _call_id_supported(api, server):
    """
    Returns true if server support the optional call_id arg, false otherwise.
    """
    server_version = api.get_cached_server_version(server)

    if 'sfa' in server_version:
        code_tag = server_version['code_tag']
        code_tag_parts = code_tag.split("-")

        version_parts = code_tag_parts[0].split(".")
        major, minor = version_parts[0:2]
        rev = code_tag_parts[1]
        if int(major) > 1:
            if int(minor) > 0 or int(rev) > 20:
                return True
    return False

# we have specialized xmlrpclib.ServerProxy to remember the input url
# OTOH it's not clear if we're only dealing with XMLRPCServerProxy instances
def get_serverproxy_url (server):
    try:
        return server.url
    except:
        logger.warning("GetVersion, falling back to xmlrpclib.ServerProxy internals")
        return server._ServerProxy__host + server._ServerProxy__handler

def GetVersion(api):
    # peers explicitly in aggregates.xml
    peers =dict ([ (peername,get_serverproxy_url(v)) for (peername,v) in api.aggregates.iteritems()
                   if peername != api.hrn])
    version_manager = VersionManager()
    ad_rspec_versions = []
    request_rspec_versions = []
    for rspec_version in version_manager.versions:
        if rspec_version in ['*', 'ad']:
            request_rspec_versions.append(rspec_version.to_dict())
        if rspec_version in ['*', 'request']:
            request_rspec_version.append(rspec_version.to_dict())
    default_rspec_version = version_manager.get_version("sfa 1").to_dict()
    xrn=Xrn(api.hrn)
    version_more = {'interface':'slicemgr',
                    'hrn' : xrn.get_hrn(),
                    'urn' : xrn.get_urn(),
                    'peers': peers,
                    'request_rspec_versions': request_rspec_versions,
                    'ad_rspec_versions': ad_rspec_versions,
                    'default_ad_rspec': default_rspec_version
                    }
    sm_version=version_core(version_more)
    # local aggregate if present needs to have localhost resolved
    if api.hrn in api.aggregates:
        local_am_url=get_serverproxy_url(api.aggregates[api.hrn])
        sm_version['peers'][api.hrn]=local_am_url.replace('localhost',sm_version['hostname'])
    return sm_version

def drop_slicemgr_stats(rspec):
    try:
        stats_elements = rspec.xml.xpath('//statistics')
        for node in stats_elements:
            node.getparent().remove(node)
    except Exception, e:
        api.logger.warn("drop_slicemgr_stats failed: %s " % (str(e)))

def add_slicemgr_stat(rspec, callname, aggname, elapsed, status):
    try:
        stats_tags = rspec.xml.xpath('//statistics[@call="%s"]' % callname)
        if stats_tags:
            stats_tag = stats_tags[0]
        else:
            stats_tag = etree.SubElement(rspec.xml.root, "statistics", call=callname)

        etree.SubElement(stats_tag, "aggregate", name=str(aggname), elapsed=str(elapsed), status=str(status))
    except Exception, e:
        api.logger.warn("add_slicemgr_stat failed on  %s: %s" %(aggname, str(e)))

def ListResources(api, creds, options, call_id):
    version_manager = VersionManager()
    def _ListResources(aggregate, server, credential, opts, call_id):

        my_opts = copy(opts)
        args = [credential, my_opts]
        tStart = time.time()
        try:
            if _call_id_supported(api, server):
                args.append(call_id)
            version = api.get_cached_server_version(server)
            # force ProtoGENI aggregates to give us a v2 RSpec
            if 'sfa' not in version.keys():
                my_opts['rspec_version'] = version_manager.get_version('ProtoGENI 2').to_dict()
            rspec = server.ListResources(*args)
            return {"aggregate": aggregate, "rspec": rspec, "elapsed": time.time()-tStart, "status": "success"}
        except Exception, e:
            api.logger.warn("ListResources failed at %s: %s" %(server.url, str(e)))
            return {"aggregate": aggregate, "elapsed": time.time()-tStart, "status": "exception"}

    if Callids().already_handled(call_id): return ""

    # get slice's hrn from options
    xrn = options.get('geni_slice_urn', '')
    (hrn, type) = urn_to_hrn(xrn)
    if 'geni_compressed' in options:
        del(options['geni_compressed'])

    # get the rspec's return format from options
    rspec_version = version_manager.get_version(options.get('rspec_version'))
    version_string = "rspec_%s" % (rspec_version.to_string())

    # look in cache first
    if caching and api.cache and not xrn:
        rspec =  api.cache.get(version_string)
        if rspec:
            return rspec

    # get the callers hrn
    valid_cred = api.auth.checkCredentials(creds, 'listnodes', hrn)[0]
    caller_hrn = Credential(string=valid_cred).get_gid_caller().get_hrn()

    # attempt to use delegated credential first
    credential = api.getDelegatedCredential(creds)
    if not credential:
        credential = api.getCredential()
    credentials = [credential]
    threads = ThreadManager()
    for aggregate in api.aggregates:
        # prevent infinite loop. Dont send request back to caller
        # unless the caller is the aggregate's SM
        if caller_hrn == aggregate and aggregate != api.hrn:
            continue

        # get the rspec from the aggregate
        server = api.aggregates[aggregate]
        threads.run(_ListResources, aggregate, server, credentials, options, call_id)

    results = threads.get_results()
    rspec_version = version_manager.get_version(options.get('rspec_version'))
    if xrn:    
        result_version = version_manager._get_version(rspec_version.type, rspec_version.version, 'manifest')
    else: 
        result_version = version_manager._get_version(rspec_version.type, rspec_version.version, 'ad')
    rspec = RSpec(version=result_version)
    for result in results:
        add_slicemgr_stat(rspec, "ListResources", result["aggregate"], result["elapsed"], result["status"])
        if result["status"]=="success":
            try:
                rspec.version.merge(result["rspec"])
            except:
                api.logger.log_exc("SM.ListResources: Failed to merge aggregate rspec")

    # cache the result
    if caching and api.cache and not xrn:
        api.cache.add(version_string, rspec.toxml())

    return rspec.toxml()


def CreateSliver(api, xrn, creds, rspec_str, users, call_id):

    version_manager = VersionManager()
    def _CreateSliver(aggregate, server, xrn, credential, rspec, users, call_id):
        tStart = time.time()
        try:
            # Need to call GetVersion at an aggregate to determine the supported
            # rspec type/format beofre calling CreateSliver at an Aggregate.
            server_version = api.get_cached_server_version(server)
            if 'sfa' not in server_version and 'geni_api' in server_version:
                # sfa aggregtes support both sfa and pg rspecs, no need to convert
                # if aggregate supports sfa rspecs. otherwise convert to pg rspec
                rspec = RSpecConverter.to_pg_rspec(rspec, 'request')
            args = [xrn, credential, rspec, users]
            if _call_id_supported(api, server):
                args.append(call_id)
            rspec = server.CreateSliver(*args)
            return {"aggregate": aggregate, "rspec": rspec, "elapsed": time.time()-tStart, "status": "success"}
        except: 
            logger.log_exc('Something wrong in _CreateSliver with URL %s'%server.url)
            return {"aggregate": aggregate, "elapsed": time.time()-tStart, "status": "exception"}

    if Callids().already_handled(call_id): return ""
    # Validate the RSpec against PlanetLab's schema --disabled for now
    # The schema used here needs to aggregate the PL and VINI schemas
    # schema = "/var/www/html/schemas/pl.rng"
    rspec = RSpec(rspec_str)
    schema = None
    if schema:
        rspec.validate(schema)

    # if there is a <statistics> section, the aggregates don't care about it,
    # so delete it.
    drop_slicemgr_stats(rspec)

    # attempt to use delegated credential first
    credential = api.getDelegatedCredential(creds)
    if not credential:
        credential = api.getCredential()

    # get the callers hrn
    hrn, type = urn_to_hrn(xrn)
    valid_cred = api.auth.checkCredentials(creds, 'createsliver', hrn)[0]
    caller_hrn = Credential(string=valid_cred).get_gid_caller().get_hrn()
    threads = ThreadManager()
    for aggregate in api.aggregates:
        # prevent infinite loop. Dont send request back to caller
        # unless the caller is the aggregate's SM 
        if caller_hrn == aggregate and aggregate != api.hrn:
            continue
        server = api.aggregates[aggregate]
        # Just send entire RSpec to each aggregate
        threads.run(_CreateSliver, aggregate, server, xrn, credential, rspec.toxml(), users, call_id)
            
    results = threads.get_results()
    manifest_version = version_manager._get_version(rspec.version.type, rspec.version.version, 'manifest')
    result_rspec = RSpec(version=manifest_version)
    for result in results:
        add_slicemgr_stat(rspec, "CreateSliver", result["aggregate"], result["elapsed"], result["status"])
        if result["status"]=="success":
            try:
                result_rspec.version.merge(result["rspec"])
            except:
                api.logger.log_exc("SM.CreateSliver: Failed to merge aggregate rspec")
    return rspec.toxml()

def RenewSliver(api, xrn, creds, expiration_time, call_id):
    def _RenewSliver(server, xrn, creds, expiration_time, call_id):
        server_version = api.get_cached_server_version(server)
        args =  [xrn, creds, expiration_time, call_id]
        if _call_id_supported(api, server):
            args.append(call_id)
        return server.RenewSliver(*args)

    if Callids().already_handled(call_id): return True

    (hrn, type) = urn_to_hrn(xrn)
    # get the callers hrn
    valid_cred = api.auth.checkCredentials(creds, 'renewsliver', hrn)[0]
    caller_hrn = Credential(string=valid_cred).get_gid_caller().get_hrn()

    # attempt to use delegated credential first
    credential = api.getDelegatedCredential(creds)
    if not credential:
        credential = api.getCredential()
    threads = ThreadManager()
    for aggregate in api.aggregates:
        # prevent infinite loop. Dont send request back to caller
        # unless the caller is the aggregate's SM
        if caller_hrn == aggregate and aggregate != api.hrn:
            continue
        server = api.aggregates[aggregate]
        threads.run(_RenewSliver, server, xrn, [credential], expiration_time, call_id)
    # 'and' the results
    return reduce (lambda x,y: x and y, threads.get_results() , True)

def DeleteSliver(api, xrn, creds, call_id):
    def _DeleteSliver(server, xrn, creds, call_id):
        server_version = api.get_cached_server_version(server)
        args =  [xrn, creds]
        if _call_id_supported(api, server):
            args.append(call_id)
        return server.DeleteSliver(*args)

    if Callids().already_handled(call_id): return ""
    (hrn, type) = urn_to_hrn(xrn)
    # get the callers hrn
    valid_cred = api.auth.checkCredentials(creds, 'deletesliver', hrn)[0]
    caller_hrn = Credential(string=valid_cred).get_gid_caller().get_hrn()

    # attempt to use delegated credential first
    credential = api.getDelegatedCredential(creds)
    if not credential:
        credential = api.getCredential()
    threads = ThreadManager()
    for aggregate in api.aggregates:
        # prevent infinite loop. Dont send request back to caller
        # unless the caller is the aggregate's SM
        if caller_hrn == aggregate and aggregate != api.hrn:
            continue
        server = api.aggregates[aggregate]
        threads.run(_DeleteSliver, server, xrn, credential, call_id)
    threads.get_results()
    return 1


# first draft at a merging SliverStatus
def SliverStatus(api, slice_xrn, creds, call_id):
    def _SliverStatus(server, xrn, creds, call_id):
        server_version = api.get_cached_server_version(server)
        args =  [xrn, creds]
        if _call_id_supported(api, server):
            args.append(call_id)
        return server.SliverStatus(*args)
    
    if Callids().already_handled(call_id): return {}
    # attempt to use delegated credential first
    credential = api.getDelegatedCredential(creds)
    if not credential:
        credential = api.getCredential()
    threads = ThreadManager()
    for aggregate in api.aggregates:
        server = api.aggregates[aggregate]
        threads.run (_SliverStatus, server, slice_xrn, credential, call_id)
    results = threads.get_results()

    # get rid of any void result - e.g. when call_id was hit where by convention we return {}
    results = [ result for result in results if result and result['geni_resources']]

    # do not try to combine if there's no result
    if not results : return {}

    # otherwise let's merge stuff
    overall = {}

    # mmh, it is expected that all results carry the same urn
    overall['geni_urn'] = results[0]['geni_urn']
    overall['pl_login'] = results[0]['pl_login']
    # append all geni_resources
    overall['geni_resources'] = \
        reduce (lambda x,y: x+y, [ result['geni_resources'] for result in results] , [])
    overall['status'] = 'unknown'
    if overall['geni_resources']:
        overall['status'] = 'ready'

    return overall

caching=True
#caching=False
def ListSlices(api, creds, call_id):
    def _ListSlices(server, creds, call_id):
        server_version = api.get_cached_server_version(server)
        args =  [creds]
        if _call_id_supported(api, server):
            args.append(call_id)
        return server.ListSlices(*args)

    if Callids().already_handled(call_id): return []

    # look in cache first
    if caching and api.cache:
        slices = api.cache.get('slices')
        if slices:
            return slices

    # get the callers hrn
    valid_cred = api.auth.checkCredentials(creds, 'listslices', None)[0]
    caller_hrn = Credential(string=valid_cred).get_gid_caller().get_hrn()

    # attempt to use delegated credential first
    credential = api.getDelegatedCredential(creds)
    if not credential:
        credential = api.getCredential()
    threads = ThreadManager()
    # fetch from aggregates
    for aggregate in api.aggregates:
        # prevent infinite loop. Dont send request back to caller
        # unless the caller is the aggregate's SM
        if caller_hrn == aggregate and aggregate != api.hrn:
            continue
        server = api.aggregates[aggregate]
        threads.run(_ListSlices, server, credential, call_id)

    # combime results
    results = threads.get_results()
    slices = []
    for result in results:
        slices.extend(result)

    # cache the result
    if caching and api.cache:
        api.cache.add('slices', slices)

    return slices


def get_ticket(api, xrn, creds, rspec, users):
    slice_hrn, type = urn_to_hrn(xrn)
    # get the netspecs contained within the clients rspec
    aggregate_rspecs = {}
    tree= etree.parse(StringIO(rspec))
    elements = tree.findall('./network')
    for element in elements:
        aggregate_hrn = element.values()[0]
        aggregate_rspecs[aggregate_hrn] = rspec 

    # get the callers hrn
    valid_cred = api.auth.checkCredentials(creds, 'getticket', slice_hrn)[0]
    caller_hrn = Credential(string=valid_cred).get_gid_caller().get_hrn()

    # attempt to use delegated credential first
    credential = api.getDelegatedCredential(creds)
    if not credential:
        credential = api.getCredential() 
    threads = ThreadManager()
    for (aggregate, aggregate_rspec) in aggregate_rspecs.iteritems():
        # prevent infinite loop. Dont send request back to caller
        # unless the caller is the aggregate's SM
        if caller_hrn == aggregate and aggregate != api.hrn:
            continue
        server = None
        if aggregate in api.aggregates:
            server = api.aggregates[aggregate]
        else:
            net_urn = hrn_to_urn(aggregate, 'authority')     
            # we may have a peer that knows about this aggregate
            for agg in api.aggregates:
                target_aggs = api.aggregates[agg].get_aggregates(credential, net_urn)
                if not target_aggs or not 'hrn' in target_aggs[0]:
                    continue
                # send the request to this address 
                url = target_aggs[0]['url']
                server = xmlrpcprotocol.get_server(url, api.key_file, api.cert_file, timeout=30)
                # aggregate found, no need to keep looping
                break   
        if server is None:
            continue 
        threads.run(server.GetTicket, xrn, credential, aggregate_rspec, users)

    results = threads.get_results()
    
    # gather information from each ticket 
    rspecs = []
    initscripts = []
    slivers = [] 
    object_gid = None  
    for result in results:
        agg_ticket = SfaTicket(string=result)
        attrs = agg_ticket.get_attributes()
        if not object_gid:
            object_gid = agg_ticket.get_gid_object()
        rspecs.append(agg_ticket.get_rspec())
        initscripts.extend(attrs.get('initscripts', [])) 
        slivers.extend(attrs.get('slivers', [])) 
    
    # merge info
    attributes = {'initscripts': initscripts,
                 'slivers': slivers}
    merged_rspec = merge_rspecs(rspecs) 

    # create a new ticket
    ticket = SfaTicket(subject = slice_hrn)
    ticket.set_gid_caller(api.auth.client_gid)
    ticket.set_issuer(key=api.key, subject=api.hrn)
    ticket.set_gid_object(object_gid)
    ticket.set_pubkey(object_gid.get_pubkey())
    #new_ticket.set_parent(api.auth.hierarchy.get_auth_ticket(auth_hrn))
    ticket.set_attributes(attributes)
    ticket.set_rspec(merged_rspec)
    ticket.encode()
    ticket.sign()          
    return ticket.save_to_string(save_parents=True)

def start_slice(api, xrn, creds):
    hrn, type = urn_to_hrn(xrn)

    # get the callers hrn
    valid_cred = api.auth.checkCredentials(creds, 'startslice', hrn)[0]
    caller_hrn = Credential(string=valid_cred).get_gid_caller().get_hrn()

    # attempt to use delegated credential first
    credential = api.getDelegatedCredential(creds)
    if not credential:
        credential = api.getCredential()
    threads = ThreadManager()
    for aggregate in api.aggregates:
        # prevent infinite loop. Dont send request back to caller
        # unless the caller is the aggregate's SM
        if caller_hrn == aggregate and aggregate != api.hrn:
            continue
        server = api.aggregates[aggregate]
        threads.run(server.Start, xrn, credential)
    threads.get_results()    
    return 1
 
def stop_slice(api, xrn, creds):
    hrn, type = urn_to_hrn(xrn)

    # get the callers hrn
    valid_cred = api.auth.checkCredentials(creds, 'stopslice', hrn)[0]
    caller_hrn = Credential(string=valid_cred).get_gid_caller().get_hrn()

    # attempt to use delegated credential first
    credential = api.getDelegatedCredential(creds)
    if not credential:
        credential = api.getCredential()
    threads = ThreadManager()
    for aggregate in api.aggregates:
        # prevent infinite loop. Dont send request back to caller
        # unless the caller is the aggregate's SM
        if caller_hrn == aggregate and aggregate != api.hrn:
            continue
        server = api.aggregates[aggregate]
        threads.run(server.Stop, xrn, credential)
    threads.get_results()    
    return 1

def reset_slice(api, xrn):
    """
    Not implemented
    """
    return 1

def shutdown(api, xrn, creds):
    """
    Not implemented   
    """
    return 1

def status(api, xrn, creds):
    """
    Not implemented 
    """
    return 1

def main():
    r = RSpec()
    r.parseFile(sys.argv[1])
    rspec = r.toDict()
    CreateSliver(None,'plc.princeton.tmacktestslice',rspec,'create-slice-tmacktestslice')

if __name__ == "__main__":
    main()

