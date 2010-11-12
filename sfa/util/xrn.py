import re

from sfa.util.faults import *
from sfa.util.sfalogging import sfa_logger

# for convenience and smoother translation - we should get rid of these functions eventually 
def get_leaf(hrn): return Xrn(hrn).get_leaf()
def get_authority(hrn): return Xrn(hrn).get_authority_hrn()
def urn_to_hrn(urn): xrn=Xrn(urn); return (xrn.hrn, xrn.type)
def hrn_to_urn(hrn,type): return Xrn(hrn, type=type).urn

class Xrn:

    ########## basic tools on HRNs
    # split a HRN-like string into pieces
    # this is like split('.') except for escaped (backslashed) dots
    # e.g. hrn_split ('a\.b.c.d') -> [ 'a\.b','c','d']
    @staticmethod
    def hrn_split(hrn):
        return [ x.replace('--sep--','\\.') for x in hrn.replace('\\.','--sep--').split('.') ]

    # e.g. hrn_leaf ('a\.b.c.d') -> 'd'
    @staticmethod
    def hrn_leaf(hrn): return Xrn.hrn_split(hrn)[-1]

    # e.g. hrn_auth_list ('a\.b.c.d') -> ['a\.b', 'c']
    @staticmethod
    def hrn_auth_list(hrn): return Xrn.hrn_split(hrn)[0:-1]
    
    # e.g. hrn_auth ('a\.b.c.d') -> 'a\.b.c'
    @staticmethod
    def hrn_auth(hrn): return '.'.join(Xrn.hrn_auth_list(hrn))
    
    # e.g. escape ('a.b') -> 'a\.b'
    @staticmethod
    def escape(token): return re.sub(r'([^\\])\.', r'\1\.', token)
    # e.g. unescape ('a\.b') -> 'a.b'
    @staticmethod
    def unescape(token): return token.replace('\\.','.')
        
    URN_PREFIX = "urn:publicid:IDN"

    ########## basic tools on URNs
    @staticmethod
    def urn_full (urn):
        if urn.startswith(Xrn.URN_PREFIX): return urn
        else: return Xrn.URN_PREFIX+URN
    @staticmethod
    def urn_meaningful (urn):
        if urn.startswith(Xrn.URN_PREFIX): return urn[len(Xrn.URN_PREFIX):]
        else: return urn
    @staticmethod
    def urn_split (urn):
        return Xrn.urn_meaningful(urn).split('+')

    ####################
    # the local fields that are kept consistent
    # self.urn
    # self.hrn
    # self.type
    # self.path
    # provide either urn, or (hrn + type)
    def __init__ (self, xrn, type=None):
        if not xrn: xrn = ""
        # user has specified xrn : guess if urn or hrn
        if xrn.startswith(Xrn.URN_PREFIX):
            self.hrn=None
            self.urn=xrn
            self.urn_to_hrn()
        else:
            self.urn=None
            self.hrn=xrn
            self.type=type
            self.hrn_to_urn()
# happens all the time ..
#        if not type:
#            sfa_logger().debug("type-less Xrn's are not safe")

    def get_urn(self): return self.urn
    def get_hrn(self): return self.hrn
    def get_type(self): return self.type
    def get_hrn_type(self): return (self.hrn, self.type)

    def _normalize(self):
        if self.hrn is None: raise SfaAPIError, "Xrn._normalize"
        if not hasattr(self,'leaf'): 
            self.leaf=Xrn.hrn_split(self.hrn)[-1]
        # self.authority keeps a list
        if not hasattr(self,'authority'): 
            self.authority=Xrn.hrn_auth_list(self.hrn)

    def get_leaf(self):
        self._normalize()
        return self.leaf

    def get_authority_hrn(self): 
        self._normalize()
        return '.'.join( self.authority )
    
    def get_authority_urn(self): 
        self._normalize()
        return ':'.join( [Xrn.unescape(x) for x in self.authority] )
    
    def urn_to_hrn(self):
        """
        compute tuple (hrn, type) from urn
        """
        
#        if not self.urn or not self.urn.startswith(Xrn.URN_PREFIX):
        if not self.urn.startswith(Xrn.URN_PREFIX):
            raise SfaAPIError, "Xrn.urn_to_hrn"

        parts = Xrn.urn_split(self.urn)
        type=parts.pop(2)
        # Remove the authority name (e.g. '.sa')
        if type == 'authority': parts.pop()

        # convert parts (list) into hrn (str) by doing the following
        # 1. remove blank parts
        # 2. escape dots inside parts
        # 3. replace ':' with '.' inside parts
        # 3. join parts using '.' 
        hrn = '.'.join([Xrn.escape(part).replace(':','.') for part in parts if part]) 

        self.hrn=str(hrn)
        self.type=str(type)
    
    def hrn_to_urn(self):
        """
        compute urn from (hrn, type)
        """

#        if not self.hrn or self.hrn.startswith(Xrn.URN_PREFIX):
        if self.hrn.startswith(Xrn.URN_PREFIX):
            raise SfaAPIError, "Xrn.hrn_to_urn, hrn=%s"%self.hrn

        if self.type == 'authority':
            self.authority = Xrn.hrn_split(self.hrn)
            name = 'sa'   
        else:
            self.authority = Xrn.hrn_auth_list(self.hrn)
            name = Xrn.hrn_leaf(self.hrn)

        authority_string = self.get_authority_urn()

        if self.type == None:
            urn = "+".join(['',authority_string,name])
        else:
            urn = "+".join(['',authority_string,self.type,name])
        
        self.urn = Xrn.URN_PREFIX + urn

    def dump_string(self):
        result="-------------------- XRN\n"
        result += "URN=%s\n"%self.urn
        result += "HRN=%s\n"%self.hrn
        result += "TYPE=%s\n"%self.type
        result += "LEAF=%s\n"%self.get_leaf()
        result += "AUTH(hrn format)=%s\n"%self.get_authority_hrn()
        result += "AUTH(urn format)=%s\n"%self.get_authority_urn()
        return result
        
