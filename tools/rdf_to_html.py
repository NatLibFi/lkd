#!/usr/bin/env python3
"""
 Copyright 2021-2023 University Of Helsinki (The National Library Of Finland)

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
import argparse
import csv
import logging

from lxml import etree
from lxml.etree import Element, SubElement
from rdflib import Graph, URIRef, BNode, Namespace, RDF, Literal, util, DCTERMS, FOAF
from rdflib.namespace import SKOS, RDFS, OWL
from rdflib.paths import InvPath
from rdflib.plugins.sparql.processor import prepareQuery
from typing import Any
from urllib.parse import urldefrag

def defrag_iri(iri, separator='/'):
    result = urldefrag(iri)
    if result:
        tag = result[0]
        fragment = result[1]
        if not fragment and separator in iri:
            idx = iri.rfind(separator)
            tag = iri[:idx + 1]
            fragment = iri[idx + 1:]
    return (tag, fragment)

SCHEMA = Namespace('http://schema.org/')
RDA = Namespace('http://rdaregistry.info/')
BF = Namespace('http://id.loc.gov/ontologies/bibframe/')

HEADERS = {OWL.Class: 'Classes',
           OWL.ObjectProperty: 'Object Properties',
           OWL.DatatypeProperty: 'Datatype Properties',
           OWL.AnnotationProperty: 'Annotation Properties',
           '': 'Other Identifiers'}

HEADERS_SINGULAR = {v: (v[0] + ''.join(
    [(' ' + x.lower()) if x.isupper() else x for x in defrag_iri(k, '#')[1][1:]])
    if k != '' else 'Identifier') for (k, v) in HEADERS.items()}

TYPES = [OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty, '']

# Row labels below are ordered
# Note: conversions from InvPath to str are used because of rdflib issue #2242
ROW_HEADER_LABELS = {
    'IRI': '',
    RDFS.label: 'Label',
    RDF.type: 'Type',
    OWL.inverseOf: 'Inverse Property',
    OWL.equivalentClass: 'Equivalent Class',
    OWL.equivalentProperty: 'Equivalent Property',
    OWL.disjointWith: 'Disjoint With',
    RDFS.subClassOf: 'SubClass Of',
    InvPath(RDFS.subClassOf).n3(): 'SubClassed As',
    InvPath(RDFS.range).n3(): 'Is in Range Of',
    RDFS.subPropertyOf: 'SubProperty Of',
    InvPath(RDFS.subPropertyOf).n3(): 'SubProperties',
    RDFS.seeAlso: 'See Also',
    RDFS.domain: 'Domain',
    InvPath(RDFS.domain).n3(): 'Is in Domain Of',
    RDFS.range: 'Range',
    DCTERMS.identifier: 'Identifier',
    DCTERMS.coverage: 'Coverage',
    SCHEMA.parentOrganization: 'Parent Organization',
    SCHEMA.location: 'Location',
    SCHEMA.member: 'Has Member',
    FOAF.homepage: 'Homepage',
    SKOS.broadMatch: 'Broader Match',
    SKOS.closeMatch: 'Close Match',
    SKOS.exactMatch: 'Exact Match',
    SKOS.narrowMatch: 'Narrow Match',
}

class RDFtoHTML:
    '''
    Class for converting the OWL-based LKD data model into an HTML page.

    Adapted from https://github.com/NatLibFi/Finto-data/blob/master/tools/schema-tools/rdf_to_html.py
    to take into account quirks in LKD data model.
    '''
    def __init__(self):
        parser = argparse.ArgumentParser(description='Conversion of LKD data model from RDF to HTML')
        parser.add_argument('-pl', '--pref-label',
            help='Property name for preferred labels, e.g., skos:prefLabel', required=True)
        parser.add_argument('-l', '--language',
            help='Language code of main language used in HTML documentation', required=True)
        parser.add_argument('-i', '--input-path',
            help='Input path for rdf file', required=True)
        parser.add_argument('-o', '--output-path',
            help='Output path for html documentation file', required=True)
        parser.add_argument('-ns', '--namespace',
            help='Namespace of concepts in input file', required=True)
        parser.add_argument('-u', '--base-url',
            help='Base URL of published html file', required=True)
        parser.add_argument('-t', '--title',
            help='Title of HTML document')
        parser.add_argument('-d', '--description',
            help='HTML file containing description of data model to be included to output file')
        parser.add_argument('-m', '--metadata-path',
            help='Input path for a separate RDF metadata file, to be used in populating description list')
        parser.add_argument("-r", "--releases-path",
            help="Input path for separate releases csv file")
        parser.add_argument('--other-identifiers', default='lkd:NatLibFi lkd:lkdProject',
            help='Other identifiers to be shown in the html documentation file')
        parser.add_argument('-v', '--version',
            help='Explicit version number (in format x.y.z), used to overwrite any such thing defined in metadata file')
        parser.add_argument('-pv', '--prior-version',
            help='Explicit prior version number (in format x.y.z), used to overwrite any such thing defined by metadata file')
        args = parser.parse_args()
        self.language = args.language
        self.pref_label = args.pref_label
        self.input_path = args.input_path
        self.output_path = args.output_path
        self.namespace = args.namespace
        self.base_url = args.base_url
        self.title = args.title
        self.description = args.description
        self.metadata_path = args.metadata_path
        self.releases_path = args.releases_path
        self.version = args.version
        self.prior_version = args.prior_version
        self.used_prefixes = set()
        self.graph = Graph(bind_namespaces='none')
        self.combined_graph = Graph(bind_namespaces='none')
        self.combined_graph.parse(self.input_path, format='ttl')
        # identifier for the LKD ontology
        self.URIRef = URIRef(self.combined_graph.namespace_manager.expand_curie('lkd:'))

        if self.metadata_path:
            self.combined_graph.parse(self.metadata_path, format='ttl', publicID=self.URIRef)

        self.other_identifiers = [
            URIRef(util.from_n3(x, nsm=self.combined_graph.namespace_manager)) for x in args.other_identifiers.split()
        ]

        self.parse_graph()

    def get_pref_label(self, subject, graph=None):
        graph = graph or self.graph
        for probj in graph.predicate_objects(subject):
            prop = probj[0]
            obj = probj[1]
            prop_ns = prop.n3(graph.namespace_manager)
            if prop_ns == self.pref_label:
                if Literal(probj[1]).language:
                    if self.language == Literal(probj[1]).language:
                        return(obj)
                else:
                    return(obj)

    def sort_properties_with_id(self, properties):
        sorted_labels = sorted(properties.keys(), key=str.casefold)

        sorted_properties = {}
        for i, subject in enumerate(sorted_labels):
            sorted_properties.update({subject: properties[subject]})

        return sorted_properties

    def sort_properties_with_label(self, properties):
        unsorted_properties = {}
        for prop in properties:
            pref_label = self.get_pref_label(prop, graph=self.graph)
            unsorted_properties[pref_label] = {prop: properties[prop]}
        sorted_labels = sorted(unsorted_properties.keys(), key=str.casefold)
        sorted_properties = {}
        for pref_label in sorted_labels:
            sorted_properties.update(unsorted_properties[pref_label])
        return sorted_properties

    def create_hyperlink_elem(self, identifier) -> etree.ElementBase:
        if identifier.startswith(self.namespace):
            dfrag = defrag_iri(identifier)
            (aElem := Element('a', attrib={'href': '#' + dfrag[1]})).text = dfrag[1]
        else:
            aElem = Element('a', attrib={'href': str(identifier), 'target': '_blank'})
            qname = identifier.n3(self.graph.namespace_manager)
            if not (ns:=qname.split(':')[0]).startswith('<http'):
                self.used_prefixes.add(ns)
            aElem.text = str(qname)

            if identifier.startswith('http://id.loc.gov/ontologies/'):
                # As BF and BFLC links serve RDF by default, change href to HTML representation
                addr_end_ind = identifier.rfind('/')
                aElem.set('href',
                    identifier[:addr_end_ind] +
                    '.html#' +
                    ('c_' if identifier[addr_end_ind+1].isupper() else 'p_') +
                    identifier[addr_end_ind+1:]
                )
        return aElem

    def create_contents(self, html_elem, header: str, properties):
        SubElement(html_elem, 'h2', id=header.replace(' ', '')).text = header
        ul_elem = SubElement(html_elem, 'ul')
        for idx, subject in enumerate(properties):
            result = defrag_iri(subject)
            if result:
                fragment = result[1]
                text = fragment
                (anchor:=SubElement(SubElement(ul_elem, 'li'), 'a', href='#' + fragment)).text = text 
                if idx < len(properties) - 1:
                    anchor.tail = ', '

    def create_properties(self, html_elem, header, properties):
        SubElement(html_elem, 'h2').text = header
        tableContainerDiv = SubElement(html_elem, 'div', attrib={'class': 'tableContainer'})
        for subject in properties:
            result = defrag_iri(subject)
            if result:
                table = SubElement(tableContainerDiv, 'table', id=result[1])
                tablerow = SubElement(table, 'tr', attrib={'class': 'trHeading'})
                SubElement(tablerow, 'td', attrib={'class': 'key'}).text = HEADERS_SINGULAR[header] + ':'
                td_value = SubElement(tablerow, 'td', attrib={'class': 'value'})
                SubElement(td_value, 'a', href='#' + result[1]).text = result[1]

                for prop in properties[subject]:
                    if prop == RDF.type and next(reversed(HEADERS.values())) != header:
                        continue
                    tablerow = SubElement(table, 'tr')
                    if type(prop) == URIRef or prop != 'IRI':
                        if (rowLabel:=ROW_HEADER_LABELS[prop]):
                            (td_key:=SubElement(tablerow, 'td')).text = rowLabel
                        else:
                            root = self.tag(prop)
                            td_key = SubElement(tablerow, 'td')
                            td_key.append(root)
                    else:
                        (td_key:=SubElement(tablerow, 'td')).text = prop

                    td_key.set('class', 'key')
                    td_value_orig = SubElement(tablerow, 'td', attrib={'class': 'value'})

                    for idx, value in enumerate(properties[subject][prop]):
                        td_value = SubElement(td_value_orig, 'div')
                        if type(value) in [URIRef, InvPath]:
                            if prop == 'IRI':
                                td_value.text = value
                            else:
                                root = self.create_hyperlink_elem(value)
                                if idx < len(properties[subject][prop]) - 1:
                                    root.tail = ', ' if not root.tail else root.tail + ', '
                                td_value.append(root)
                        elif type(value) == BNode:
                            a = list(self.graph.objects(value, OWL.unionOf))
                            if len(a) == 1:
                                unionOf = list(self.graph.items(a[0]))
                                td_value.text = 'Union of '
                                union_len = len(unionOf) - 2

                                for idx2, x in enumerate(unionOf):
                                    union_aElem = self.create_hyperlink_elem(x)
                                    if idx2 < union_len:
                                        union_aElem.tail = ', '
                                    elif idx2 == union_len:
                                        union_aElem.tail = ' and '
                                    td_value.append(union_aElem)
                            else:
                                logging.warning(
                                    'Multiple owl:unionOf structures detected for %s %s %s, skipping' % subject, prop, value
                                )
                        else:
                            if Literal(value).language:
                                value = str(value) + ' (' + Literal(value).language + ')'

                            text = str(value)

                            if idx < len(properties[subject][prop]) - 1:
                                text += ', '

                            try:
                                text = etree.fromstring(text)
                                td_value.append(text)
                            except etree.XMLSyntaxError:
                                try:
                                    text = etree.fromstring(text)
                                    td_value.append(text)
                                except etree.XMLSyntaxError:
                                    td_value.text = text

                #Add back to header list and top links
                backToDiv = SubElement(tableContainerDiv, 'div', attrib={'class': 'backToTop'})
                backToDiv.text = '['

                aListTop = SubElement(backToDiv, 'a', attrib={'href': '#' + header.replace(' ', '')})
                aListTop.text = 'Back to ' + header + ' list'
                aListTop.tail = '] ['

                backToDiv.append(aListTop)
                backToTopA = SubElement(backToDiv, 'a', attrib={'href': '#'})
                backToTopA.text = 'Back to top'
                backToTopA.tail = ']'
                backToDiv.append(backToTopA)

    def parse_graph(self):
        self.graph.parse(self.input_path, format='ttl')
        data_model = {} # type: dict[URIRef, Any]
        inverse_prop_list = set()
        sort_order_list = list(ROW_HEADER_LABELS.keys())
        for key, val in ROW_HEADER_LABELS.items():
            if type(key) == str:
                inverse_prop_list.add(URIRef(key[2:-1]))

        q = prepareQuery(
            'SELECT ?s ?p WHERE { ?s ?p ?o . ?o owl:unionOf ?o2 . ?o2 rdf:rest*/rdf:first ?o3 .}',
            initNs = { 'owl': OWL, 'rdf': RDF }
        )

        for ns in self.graph.namespaces():
            self.graph.namespace_manager.bind(ns[0], ns[1])
        for t in TYPES:
            data_model[t] = {}
            for subject in (self.graph.subjects(RDF.type, t) if t != '' else self.other_identifiers):
                fragment = None
                result = defrag_iri(subject)
                if result:
                    fragment = result[1]
                pref_label = self.get_pref_label(subject)
                if type(subject) == BNode:
                    # Not supported at the moment
                    continue

                if pref_label and fragment:
                    sorted_properties  = {}
                    sorted_properties['IRI'] = [subject]
                    pref_labels = []
                    other_properties = []
                    for prop, obj in self.graph.predicate_objects(subject):
                        prop_ns = prop.n3(self.graph.namespace_manager)
                        language = _ if (_:=Literal(obj).language) else None
                        prop_dict = {'language': language, 'prop': prop, 'obj': obj}
                        if prop_ns == self.pref_label:
                            pref_labels.append(prop_dict)
                        else:
                            other_properties.append(prop_dict)

                    for obj, prop in filter(lambda w: w[1] in inverse_prop_list, self.graph.subject_predicates(subject)):
                        prop_dict = {'language': None, 'prop': InvPath(prop).n3(), 'obj': obj}
                        other_properties.append(prop_dict)

                    for obj, prop in self.graph.query(q, initBindings={'o3': subject}):
                        prop_dict = {'language': None, 'prop': InvPath(prop).n3(), 'obj': obj}
                        other_properties.append(prop_dict)

                    sorted_languages = sorted(pref_labels, key=lambda k: (  
                        k['language'] != self.language,
                        k['language']
                    ))

                    for sl in sorted_languages:
                        if sl['prop'] in sorted_properties:
                            sorted_properties[sl['prop']].append(sl['obj'])
                        else:
                            sorted_properties[sl['prop']] = [sl['obj']]

                    other_properties = sorted(other_properties, key=lambda k: (  
                        k['prop'], k['obj']
                    ))

                    for sl in other_properties:
                        if sl['prop'] in sorted_properties:
                            sorted_properties[sl['prop']].append(sl['obj'])
                        else:
                            sorted_properties[sl['prop']] = [sl['obj']]

                    sorted_properties = dict(sorted(sorted_properties.items(), key=lambda x: sort_order_list.index(x[0]))) 
                    data_model[(t if t else '')][subject] = sorted_properties

                else:
                    logging.warning('PrefLabel or URI fragment missing from %s' % subject)                      

        html_elem = Element('html') # type: etree.ElementBase
        head_elem = SubElement(html_elem, 'head') # type: etree.ElementBase
        if self.title:
            SubElement(head_elem, 'title').text = self.title
        SubElement(head_elem, 'meta', attrib={
            'http-equiv': 'Content-Type',
            'content': 'text/html; charset=utf-8',
        })

        SubElement(head_elem, 'link', rel='stylesheet', href='stylesheet.css')

        body_elem = SubElement(html_elem, 'body') # type: etree.ElementBase
        if self.description:
            description_tree = etree.parse(self.description, etree.HTMLParser(encoding='utf-8')) # type: etree._ElementTree
            if self.releases_path and self.version:
                with open(self.releases_path, "r", encoding="utf-8", newline="") as releases_file:
                    csvreader = csv.DictReader(releases_file, delimiter=",")
                    for row in csvreader:
                        if row['owl:versionInfo'] == self.version:
                            for lang in ['fi', 'en']:
                                pElem = description_tree.xpath(f'//p[@id="description-general-{lang}"]')[0]
                                pElem[-1].tail += ' ' + row[f'html-{lang}']

            body_elem.extend(description_tree.find('body'))

        SubElement(body_elem, 'hr')
        SubElement(body_elem, 'p', attrib={'class': 'fw-bold'}).text = 'Tietomallidokumentaatio - Description Document'
        dl_elem = SubElement(body_elem, 'dl')

        if self.version:
            version = self.base_url + self.version.replace('.', '-') + '/'
            self.combined_graph.remove((self.URIRef, OWL.versionIRI, None))
            self.combined_graph.add((self.URIRef, OWL.versionIRI, URIRef(version)))
            divItem = self.createDlItemForProperty(
                OWL.versionIRI,
                dt_text='This version',
                dd_value=version,
                dd_type='a'
            )
            dl_elem.append(divItem)

        divItem = self.createDlItemForProperty(
            URIRef('latestVersion', self.URIRef),
            dt_text='Latest version',
            dd_value=self.base_url,
            dd_type='a'
        )
        dl_elem.append(divItem)

        if self.prior_version:
            version = self.base_url + self.prior_version.replace('.', '-') + '/'
            self.combined_graph.remove((self.URIRef, OWL.priorVersion, None))
            self.combined_graph.add((self.URIRef, OWL.priorVersion, URIRef(version)))
            divItem = self.createDlItemForProperty(
                OWL.priorVersion,
                dt_text='Previous version',
                dd_value=version,
                dd_type='a'
            )
            dl_elem.append(divItem)

        divItem = self.createDlItemForProperty(DCTERMS.modified, graph=self.combined_graph, dt_text='Last modified', dd_type=Literal)
        dl_elem.append(divItem)

        self.combined_graph.remove((self.URIRef, OWL.versionInfo, None))
        self.combined_graph.add((self.URIRef, OWL.versionInfo, Literal(self.version)))
        divItem = self.createDlItemForProperty(OWL.versionInfo, graph=self.combined_graph, dt_text='Version', dd_type=Literal)
        dl_elem.append(divItem)

        if (self.URIRef, DCTERMS.issued, None) in self.combined_graph:
            divItem = self.createDlItemForProperty(DCTERMS.issued, graph=self.combined_graph, dt_text='Issued', dd_type=Literal)
            dl_elem.append(divItem)

        divItem = self.createDlItemForProperty(DCTERMS.relation, graph=self.combined_graph, dt_text='Relation', dd_type=URIRef)
        if len(divItem) > 1:
            dl_elem.append(divItem)

        divItem = self.createDlItemForProperty(DCTERMS.license, graph=self.combined_graph, dt_text='License', dd_type=URIRef)
        if len(divItem) > 1:
            dl_elem.append(divItem)

        divItem = self.createDlItemForProperty(DCTERMS.publisher, graph=self.combined_graph, dt_text='Publisher')
        if len(divItem) > 1:
            dl_elem.append(divItem)

        divItem = self.createDlItemForProperty(DCTERMS.contributor, graph=self.combined_graph, dt_text='Contributor')
        if len(divItem) > 1:
            dl_elem.append(divItem)

        SubElement(body_elem, 'p').text = 'Copyright: © The National Library of Finland, 2023'

        SubElement(body_elem, 'p', attrib={'class': 'fw-bold'}).text = 'Prefixes in this document'

        dl_prefix_elem = SubElement(body_elem, 'dl', attrib={'class': 'prefixes'})

        for t in data_model:
            data_model[t] = self.sort_properties_with_id(data_model[t])

        for t in data_model:
            if data_model[t]:
                self.create_contents(body_elem, HEADERS[t], data_model[t])
        for t in data_model:
            if data_model[t]:
                self.create_properties(body_elem, HEADERS[t], data_model[t])

        for prefix in sorted(self.used_prefixes):
            nsm = self.combined_graph.namespace_manager
            dt_prefix_div = f'<div><dt>{prefix}</dt><dd>{nsm.expand_curie(prefix+":")}</dd></div>'
            dl_prefix_elem.append(etree.fromstring(dt_prefix_div))

        etree.indent(html_elem)
        with open(self.output_path, 'wb') as output:
            output.write(etree.tostring(html_elem, encoding='utf-8', doctype='<!DOCTYPE html>'))

        # remove duplicate dct:description triples, prefer more specific ones defined in self.graph
        for literal in self.graph[self.URIRef:DCTERMS.description:]:
            for _ in self.combined_graph.objects(self.URIRef, DCTERMS.description):
                if literal.startswith(_) and len(literal) > len(_):
                    self.combined_graph.remove((self.URIRef, DCTERMS.description, _))
                    break

        self.combined_graph.serialize(format='turtle', destination='LKD-combined.ttl')        

    def createDlItemForProperty(self, prop : URIRef, graph: Graph=None, dt_text=None, dd_value=None, dd_type=None, subject=None) -> etree.ElementBase:
        if subject == None:
            subject = self.URIRef
        #dd_type means expected type
        div = Element('div')
        (dt := SubElement(div, 'dt')).text = dt_text if dt_text else ''
        if dd_type == 'a':
            # special case for raw links
            (dd := SubElement(div, 'dd'))
            aElem = SubElement(dd, 'a', {'href': dd_value, 'class': 'version-dl-margin'})
            aElem.text = dd_value
            if prop in [OWL.versionIRI, OWL.priorVersion, URIRef('latestVersion', self.URIRef)]:
                dd[-1].tail = '('
                (aElem2 := SubElement(dd, 'a', {'href': dd_value + 'lkd.ttl'})).text = 'Turtle'
                dd[-1].tail = ', '
                (aElem3 := SubElement(dd, 'a', {'href': dd_value + 'lkd.rdf'})).text = 'RDF/XML'

                dd[-1].tail = ')'
        elif dd_type == Literal:
            objects = list(graph.objects(subject, prop))
            for object in objects:
                objectType = type(object)
                if objectType in [URIRef, BNode]:
                    (dd := SubElement(div, 'dd')).text = str(object)
                else:
                    #objectType == Literal:
                    if object.language:
                        logging.warning('Not implemented: language tagged literal')
                    else:
                        (dd := SubElement(div, 'dd')).text = str(object)
        else:
            # dd_type == URIRef:
            # or BNode
            objects = list(graph.objects(subject, prop))
            for object in objects:
                dd = SubElement(div, 'dd')
                if type(object) != Literal:
                    if object.startswith(self.namespace):
                        dfrag = defrag_iri(object)
                        aElem = SubElement(dd, 'a', attrib={'href': '#' + dfrag[1]})
                        aElem.text = dfrag[1]
                    else:
                        aElem = SubElement(dd, 'a', attrib={'href': str(object), 'target': '_blank'})
                        aElem.text = object
                    # Use human readable value, if possible
                    if (aLabel := self.get_pref_label(object, graph)):
                        aElem.text = aLabel
                else:
                    if object.language:
                        logging.warning('Not implemented: language tagged literal')
                    else:
                        dd.text = str(object)
        return div

if __name__ == '__main__':
    RDFtoHTML()