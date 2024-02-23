"""
 Copyright 2021, 2024 University Of Helsinki (The National Library Of Finland)

 Licensed under the GNU, General Public License, Version 3.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

     https://www.gnu.org/licenses/gpl-3.0.html

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
"""

from rdflib import Graph, URIRef
from lxml import etree
import argparse
import logging
import io

def validate_xml(validation_file, xml):
    with open(validation_file, 'rb') as fh:
        xmlschema_doc = etree.parse(fh)
        xmlschema = etree.XMLSchema(xmlschema_doc)
        test_xml = etree.tostring(xml, encoding='unicode', method='xml')
        string_xml = io.StringIO(test_xml)
        doc = etree.parse(string_xml)
        xmlschema.assert_(doc)

def add_subelement(element, tag, text=None):
    subelement = etree.SubElement(element, tag)
    if text:
        subelement.text = text
    return subelement

class HTMLtoURN:
    '''
    Class for mapping property URIs with URNs to XML file.

    Adapted from https://github.com/NatLibFi/Finto-data/blob/master/tools/schema-tools/html_urn_mapping.py
    '''
    def __init__(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("-ns", "--urn_namespace",
            help="URN namespace for data model", required=True)
        parser.add_argument("-p", "--url_prefix",
            help="Prefix used in HTML formatted data model", required=True)
        parser.add_argument("-i", "--input_path",
            help="Input path for turtle formatted file", required=True)
        parser.add_argument("-o", "--output_path",
            help="Output path for XML file", required=True)
        parser.add_argument("-v", "--validation_file",
            help="File path for XSD file for validating XMl")
        parser.add_argument("-ans", "--auxiliary_urn_namespaces",
            help="Auxiliary namespaces to be mapped as well, separate with a space")
        args = parser.parse_args()
        self.urn_namespace = args.urn_namespace
        self.url_prefix = args.url_prefix
        self.output_path = args.output_path
        self.input_path = args.input_path
        self.validation_file = args.validation_file

        self.auxiliary_urn_namespaces = \
            [x for y in args.auxiliary_urn_namespaces.split() if (x:=y.strip())] \
            if args.auxiliary_urn_namespaces \
            else []

        self.graph = Graph().parse(self.input_path, format="ttl")

        logformat = '%(levelname)s: %(message)s'
        logging.basicConfig(format=logformat, level=logging.INFO)

        xml = self.create_xml()
        if self.validation_file:
            validate_xml(self.validation_file, xml)
        et = etree.ElementTree(xml)
        et.write(self.output_path, xml_declaration=True, encoding='UTF-8', pretty_print=True)

    def create_xml(self):
        root = etree.Element("records")
        etree.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        etree.register_namespace('xmlns', 'urn:nbn:se:uu:ub:epc-schema:rs-location-mapping')
        root.set('xmlns', 'urn:nbn:se:uu:ub:epc-schema:rs-location-mapping')
        root.set('{http://www.w3.org/2001/XMLSchema-instance}schemaLocation',
                 'urn:nbn:se:uu:ub:epc-schema:rs-location-mapping http://urn.kb.se/resolve?urn=urn:nbn:se:uu:ub:epc-schema:rs-location-mapping&amp;godirectly')
        add_subelement(root, "protocol-version", '3.0')

        for s in sorted(self.graph.subjects(unique=True)):
            if isinstance(s, URIRef):
                s_str = s.toPython()
                urn_namespace = self.urn_namespace
                separator = "#"
                s_partition = s_str.partition(self.urn_namespace)
                if s_partition[1]:
                    fragment = s_partition[2].rpartition(":")[2]
                    if not fragment:
                        separator = ""
                else:
                    for x in self.auxiliary_urn_namespaces:
                        s_partition = s_str.partition(x)
                        if s_partition[1]:
                            fragment = self.graph.namespace_manager.curie(s_str, False)
                            urn_namespace = x
                            break
                    if urn_namespace == self.urn_namespace:
                        logging.info(f"Skipped mapping {s_str}")
                        continue

                record = etree.SubElement(root, "record")
                header = etree.SubElement(record, "header")
                identifier = add_subelement(header, "identifier", urn_namespace + fragment.split(":")[-1])
                destinations = etree.SubElement(header, "destinations")
                destination = etree.SubElement(destinations, "destination")
                destination.set('status', 'activated')
                url = add_subelement(destination, "url", f"{self.url_prefix}{separator}{fragment}")

        return root

if __name__ == '__main__':
    HTMLtoURN()