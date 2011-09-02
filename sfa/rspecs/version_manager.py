import os

class VersionManager:
    default_type = 'SFA'
    default_version_num = '1'     
        
    def __init__(self):
        self.versions = []
        self.load_versions()

    def load_versions(self):
        path = os.path.dirname(os.path.abspath( __file__ ))
        versions_path = path + os.sep + 'versions'
        versions_module_path = 'sfa.rspecs.versions'
        valid_module = lambda x: os.path.isfile(os.sep.join([versions_path, x])) \
                        and not x.endswith('.pyc') and x not in ['__init__.py']
        files = [f for f in os.listdir(versions_path) if valid_module(f)]
        for filename in files:
            basename = filename.split('.')[0]
            module_path = versions_module_path +'.'+basename
            module = __import__(module_path, fromlist=module_path)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if hasattr(attr, 'version'):
                    self.versions.append(attr)

    def _get_version(self, type, version_num=None, content_type=None):
        retval = None
        for version in self.versions:
            if type is None or type.lower() == version.type.lower():
                if version_num is None or version_num == version.version:
                    if content_type is None or content_type.lower() == version.content_type.lower():
                        retval = version
        if not retval:
            raise InvalidRSpec("No such version format: %s version: %s type:%s "% (type, version_num, content_type))
        return retval

    def get_version(self, version):
        retval = None
        if isinstance(version, dict):
            retval =  self._get_version(version.get('type'), version.get('version_num'), version.get('content_type'))
        elif isinstance(version, basestring):
            version_parts = version.split(' ')     
            num_parts = len(version_parts)
            type = version_parts[0]
            version_num = None
            content_type = None
            if num_parts > 1:
                version_num = version_parts[1]
            if num_parts > 2:
                content_type = version_parts[2]
            retval = self._get_version(type, version_num, content_type) 
        else:
            logger.info("Unable to parse rspec version, using default")
            retval = self._get_version(self.default_type, self.default_version_num)   
 
        return retval

    def get_version_by_schema(self, schema):
        retval = None
        for version in self.versions:
            if schema == version.schema:
                retval = version
        if not retval:
            raise InvalidRSpec("Unkwnown RSpec schema: %s" % schema)
        return retval

if __name__ == '__main__':
    v = VersionManager()
    print v.versions
    print v.get_version('sfa 1') 
    print v.get_version('protogeni 2') 
    print v.get_version('protogeni 2 advertisement') 
    print v.get_version_by_schema('http://www.protogeni.net/resources/rspec/2/ad.xsd') 

