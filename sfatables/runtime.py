#!/usr/bin/python

import sys
import os
import pdb
import libxml2

from optparse import OptionParser
from sfatables import commands
from sfatables.globals import *
from sfatables.commands.List import *
from sfatables.xmlrule import *

class SFATablesRules:
    def __init__(self, chain_name):
        self.active_context = {}
        self.contexts = None # placeholder for rspec_manger
        self.sorted_rule_list = []
        self.final_processor = '__sfatables_wrap_up__.xsl'
        chain_dir_path = os.path.join(sfatables_config,chain_name)
        rule_list = List().get_rule_list(chain_dir_path)
        for rule_number in rule_list:
            self.sorted_rule_list = self.sorted_rule_list + [XMLRule(chain_name, rule_number)]
        return

    def wrap_up(self, doc):
        filepath = os.path.join(sfatables_config, 'processors', self.final_processor)

        if not os.path.exists(filepath):
            raise Exception('Could not find final rule filter')

        styledoc = libxml2.parseFile(filepath)
        style = libxslt.parseStylesheetDoc(styledoc)
        result = style.applyStylesheet(doc, None)
        stylesheet_result = style.saveResultToString(result)
        style.freeStylesheet()
        doc.freeDoc()
        result.freeDoc()

        return stylesheet_result

    def set_context(self, request_context):
        self.active_context = request_context
        return

    def create_xml_node(self, name, context_dict):
        node = libxml2.newNode(name)
        for k in context_dict.keys():
            if (type(context_dict[k])==dict):
                childNode = self.create_xml_node(k, context_dict[k])
                node.addChild(childNode)
            else:
                childNode = libxml2.newNode(k)
                childNode.addContent(context_dict[k])
                node.addChild(childNode)
        return node
                
    def add_request_context_to_rspec(self, doc):
        p = doc.xpathNewContext()
        context = p.xpathEval("//RSpec")
        if (not context):
            raise Exception('Request is not an rspec')
        else:
            # Add the request context
            requestNode = self.create_xml_node('request-context',self.active_context)
            context[0].addChild(requestNode)
        p.xpathFreeContext()
        return doc

    
    def apply(self, rspec):
        if (self.sorted_rule_list):
            doc = libxml2.parseDoc(rspec)
            doc = self.add_request_context_to_rspec(doc)

            intermediate_rspec = doc

            for rule in self.sorted_rule_list:
                (matched,intermediate_rspec) = rule.apply_interpreted(intermediate_rspec)
                if (rule.terminal and matched):
                    break

            final_rspec = self.wrap_up(intermediate_rspec) 
        else:
            final_rspec = rspec

        return final_rspec

def main():
    incoming = SFATablesRules('INCOMING')
    incoming.set_context({'sfa':{'user':{'hrn':'plc.princeton.sapanb'}}})

    outgoing = SFATablesRules('OUTGOING')
    print "%d rules loaded for INCOMING chain"%len(incoming.sorted_rule_list)
    print incoming.sorted_rule_list[0].processors

    print "%d rules loaded for OUTGOING chain"%len(outgoing.sorted_rule_list)
    print outgoing.sorted_rule_list[0].processors

    rspec = open(sys.argv[1]).read()
    newrspec = incoming.apply(rspec)
    print newrspec
    return

if __name__=="__main__":
    main()
