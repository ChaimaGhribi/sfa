from sfa.util.faults import *
from sfa.util.namespace import *
from sfa.util.method import Method
from sfa.util.parameter import Parameter
from sfa.trust.credential import Credential

class Resolve(Method):
    """
    Lookup a URN and return information about the corresponding object.
    @param slice_urn (string) URN of slice to renew
    @param credentials ([string]) of credentials
    
    """
    interfaces = ['registry']
    accepts = [
        Parameter(str, "URN"),
        Parameter(type([str]), "List of credentials"),
        ]
    returns = Parameter(bool, "Success or Failure")

    def call(self, xrn, creds):
        for cred in creds:
            try:
                self.api.auth.check(cred, 'resolve')
                # Make sure it's an authority and not a user
                if cred.get_gid_caller().get_type() != 'authority':
                    raise 'NotAuthority'
                found = True
                break
            except:
                continue
                
        if not found:
            raise InsufficientRights('Resolve: Credentials either did not verify, were no longer valid, or did not have appropriate privileges')
        

        manager_base = 'sfa.managers'

        if self.api.interface in ['registry']:
            mgr_type = self.api.config.SFA_REGISTRY_TYPE
            manager_module = manager_base + ".registry_manager_%s" % mgr_type
            manager = __import__(manager_module, fromlist=[manager_base])
            return manager.Resolve(self.api, xrn, creds)
               
        return {}