import sys
import xmlrpclib
import socket
from urlparse import urlparse
from sfa.util.sfalogging import logger
try:
    from nova import db
    from nova import flags
    from nova import context
    from nova.auth.manager import AuthManager
    from nova.compute.manager import ComputeManager
    from nova.network.manager import NetworkManager
    from nova.scheduler.manager import SchedulerManager
    from nova.image.glance import GlanceImageService
    has_nova = True
except:
    has_nova = False


class InjectContext:
    """
    Wraps the module and injects the context when executing methods 
    """     
    def __init__(self, proxy, context):
        self.proxy = proxy
        self.context = context
    
    def __getattr__(self, name):
        def func(*args, **kwds):
            result=getattr(self.proxy, name)(self.context, *args, **kwds)
            return result
        return func

class NovaShell:
    """
    A simple native shell to a nova backend. 
    This class can receive all nova calls to the underlying testbed
    """
    
    # dont care about limiting calls yet 
    direct_calls = []
    alias_calls = {}


    # use the 'capability' auth mechanism for higher performance when the PLC db is local    
    def __init__ ( self, config ) :
        url = config.SFA_PLC_URL
        # try to figure if the url is local
        is_local=False    
        hostname=urlparse(url).hostname
        if hostname == 'localhost': is_local=True
        # otherwise compare IP addresses; 
        # this might fail for any number of reasons, so let's harden that
        try:
            # xxx todo this seems to result in a DNS request for each incoming request to the AM
            # should be cached or improved
            url_ip=socket.gethostbyname(hostname)
            local_ip=socket.gethostbyname(socket.gethostname())
            if url_ip==local_ip: is_local=True
        except:
            pass


        if is_local and has_nova:
            logger.debug('nova access - native')
            # load the config
            flags.FLAGS(['foo', '--flagfile=/etc/nova/nova.conf', 'foo', 'foo'])
            # instantiate managers 
            self.auth_manager = AuthManager()
            self.compute_manager = ComputeManager()
            self.network_manager = NetworkManager()
            self.scheduler_manager = SchedulerManager()
            self.db = InjectContext(db, context.get_admin_context())
            self.image_manager = InjectContext(GlanceImageService(), context.get_admin_context())
        else:
            self.auth = None
            self.proxy = None
            logger.debug('nova access - REST')
            raise SfaNotImplemented('nova access - Rest')