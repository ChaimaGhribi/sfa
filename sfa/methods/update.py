### $Id$
### $URL$

from sfa.util.faults import *
from sfa.util.method import Method
from sfa.util.parameter import Parameter, Mixed
from sfa.trust.auth import Auth
from sfa.util.record import GeniRecord
from sfa.util.debug import log

class update(Method):
    """
    Update an object in the registry. Currently, this only updates the
    PLC information associated with the record. The Geni fields (name, type,
    GID) are fixed.
    
    @param cred credential string specifying rights of the caller
    @param record a record dictionary to be updated

    @return 1 if successful, faults otherwise 
    """

    interfaces = ['registry']
    
    accepts = [
        Parameter(str, "Credential string"),
        Parameter(dict, "Record dictionary to be updated")
        ]

    returns = Parameter(int, "1 if successful")
    
    def call(self, cred, record_dict):
        self.api.auth.check(cred, "update")
        record = GeniRecord(dict = record_dict)
        type = record.get_type()
        self.api.auth.verify_object_permission(record.get_name())
        auth_name = self.api.auth.get_authority(record.get_name())
        if not auth_name:
            auth_name = record.get_name()
        table = self.api.auth.get_auth_table(auth_name)

        # make sure the record exists
        existing_record_list = table.resolve(type, record.get_name())
        if not existing_record_list:
            raise RecordNotFound(record.get_name())
        existing_record = existing_record_list[0]

        # Update_membership needs the membership lists in the existing record
        # filled in, so it can see if members were added or removed
        self.api.fill_record_info(existing_record)

         # Use the pointer from the existing record, not the one that the user
        # gave us. This prevents the user from inserting a forged pointer
        pointer = existing_record.get_pointer()

        # update the PLC information that was specified with the record

        if (type == "authority"):
            self.api.plshell.UpdateSite(self.api.plauth, pointer, record)

        elif type == "slice":
            hrn=record.get_name()
            pl_record=self.api.geni_fields_to_pl_fields(type, hrn, record)
            self.api.plshell.UpdateSlice(self.api.plauth, pointer, pl_record)

        elif type == "user":
            # SMBAKER: UpdatePerson only allows a limited set of fields to be
            #    updated. Ideally we should have a more generic way of doing
            #    this. I copied the field names from UpdatePerson.py...
            update_fields = {}
            all_fields = record
            for key in all_fields.keys():
                if key in ['first_name', 'last_name', 'title', 'email',
                           'password', 'phone', 'url', 'bio', 'accepted_aup',
                           'enabled']:
                    update_fields[key] = all_fields[key]
            self.api.plshell.UpdatePerson(self.api.plauth, pointer, update_fields)

        elif type == "node":
            self.api.plshell.UpdateNode(self.api.plauth, pointer, record)

        else:
            raise UnknownGeniType(type)

        # update membership for researchers, pis, owners, operators
        self.api.update_membership(existing_record, record)

        return 1
