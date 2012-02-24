#
# Public keys are extracted from the users' SSH keys automatically and used to
# create GIDs. This is relatively experimental as a custom tool had to be
# written to perform conversion from SSH to OpenSSL format. It only supports
# RSA keys at this time, not DSA keys.
##

from sfa.util.xrn import get_authority, hrn_to_urn
from sfa.util.plxrn import email_to_hrn
from sfa.util.config import Config
from sfa.trust.certificate import convert_public_key, Keypair
from sfa.trust.trustedroots import TrustedRoots
from sfa.trust.gid import create_uuid

from sfa.storage.alchemy import dbsession
from sfa.storage.model import RegRecord, RegAuthority, RegUser

def _un_unicode(str):
   if isinstance(str, unicode):
       return str.encode("ascii", "ignore")
   else:
       return str

def _cleanup_string(str):
    # pgsql has a fit with strings that have high ascii in them, so filter it
    # out when generating the hrns.
    tmp = ""
    for c in str:
        if ord(c) < 128:
            tmp = tmp + c
    str = tmp

    str = _un_unicode(str)
    str = str.replace(" ", "_")
    str = str.replace(".", "_")
    str = str.replace("(", "_")
    str = str.replace("'", "_")
    str = str.replace(")", "_")
    str = str.replace('"', "_")
    return str

class SfaImporter:

    def __init__(self, auth_hierarchy, logger):
       self.logger=logger
       self.auth_hierarchy = auth_hierarchy
       config = Config()
       self.TrustedRoots = TrustedRoots(Config.get_trustedroots_dir(config))
       self.root_auth = config.SFA_REGISTRY_ROOT_AUTH
       self.interface_hrn = config.SFA_INTERFACE_HRN

    # check before creating a RegRecord entry as we run this over and over
    def record_exists (self, type, hrn):
       return dbsession.query(RegRecord).filter_by(hrn=hrn,type=type).count()!=0

    # record options into an OptionParser
    def add_options (self, parser):
       # no generic option
       pass

    def run (self, options):
       self.logger.info ("SfaImporter.run : no options used")
       self.create_top_level_records()

    def create_top_level_records(self):
        """
        Create top level and interface records
        """
        # create root authority
        self.create_top_level_auth_records(self.interface_hrn)

        # create s user record for the slice manager
        self.create_sm_client_record()

        # create interface records
        # xxx turning off the creation of authority+*
        # in fact his is required - used in SfaApi._getCredentialRaw
        # that tries to locate 'authority+sa'
        self.create_interface_records()

        # add local root authority's cert  to trusted list
        self.logger.info("SfaImporter: adding " + self.interface_hrn + " to trusted list")
        authority = self.auth_hierarchy.get_auth_info(self.interface_hrn)
        self.TrustedRoots.add_gid(authority.get_gid_object())

    def create_top_level_auth_records(self, hrn):
        """
        Create top level db records (includes root and sub authorities (local/remote)
        """
        # make sure parent exists
        parent_hrn = get_authority(hrn)
        if not parent_hrn:
            parent_hrn = hrn
        if not parent_hrn == hrn:
            self.create_top_level_auth_records(parent_hrn)

        # ensure key and cert exists:
        self.auth_hierarchy.create_top_level_auth(hrn)    
        # create the db record if it doesnt already exist    
        if self.record_exists ('authority',hrn): return
        auth_info = self.auth_hierarchy.get_auth_info(hrn)
        auth_record = RegAuthority(hrn=hrn, gid=auth_info.get_gid_object(),
                                   authority=get_authority(hrn))
        auth_record.just_created()
        dbsession.add (auth_record)
        dbsession.commit()
        self.logger.info("SfaImporter: imported authority (parent) %s " % auth_record)

    def create_sm_client_record(self):
        """
        Create a user record for the Slicemanager service.
        """
        hrn = self.interface_hrn + '.slicemanager'
        urn = hrn_to_urn(hrn, 'user')
        if not self.auth_hierarchy.auth_exists(urn):
            self.logger.info("SfaImporter: creating Slice Manager user")
            self.auth_hierarchy.create_auth(urn)

        if self.record_exists ('user',hrn): return
        auth_info = self.auth_hierarchy.get_auth_info(hrn)
        user_record = RegUser(hrn=hrn, gid=auth_info.get_gid_object(),
                              authority=get_authority(hrn))
        user_record.just_created()
        dbsession.add (user_record)
        dbsession.commit()
        self.logger.info("SfaImporter: importing user (slicemanager) %s " % user_record)

    def create_interface_records(self):
        """
        Create a record for each SFA interface
        """
        # just create certs for all sfa interfaces even if they
        # aren't enabled
        auth_info = self.auth_hierarchy.get_auth_info(self.interface_hrn)
        pkey = auth_info.get_pkey_object()
        hrn=self.interface_hrn
        for type in  [ 'authority+sa', 'authority+am', 'authority+sm', ]:
            urn = hrn_to_urn(hrn, type)
            gid = self.auth_hierarchy.create_gid(urn, create_uuid(), pkey)
            # for now we have to preserve the authority+<> stuff
            if self.record_exists (type,hrn): continue
            interface_record = RegAuthority(type=type, hrn=hrn, gid=gid,
                                            authority=get_authority(hrn))
            interface_record.just_created()
            dbsession.add (interface_record)
            dbsession.commit()
            self.logger.info("SfaImporter: imported authority (%s) %s " % (type,interface_record))
             