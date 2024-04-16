#!/usr/bin/env python3
"""
 Copyright 2022-2024 University Of Helsinki (The National Library Of Finland)

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
import copy
import contextlib
import csv
import io
import logging
import os
import pathlib
import sys
import textwrap
import time
import urllib

from argparse import ArgumentParser, Action
from lxml import etree
from lxml.etree import Element, SubElement
from rdflib import Graph, URIRef, BNode, Namespace, RDF, Literal, util, DCTERMS, FOAF, XSD
from rdflib.namespace import SKOS, RDFS, OWL
from rdflib.paths import InvPath
from rdflib.plugins.sparql.processor import prepareQuery
from typing import Any
from urllib.parse import urldefrag

def defrag_iri(iri, separator=':'):
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
BFFI = Namespace('http://urn.fi/URN:NBN:fi:schema:bffi:')
BFFIMETA = Namespace('http://urn.fi/URN:NBN:fi:schema:bffi-meta:')

HEADERS = {
    OWL.Class: 'Classes',
    OWL.ObjectProperty: 'Object Properties',
    OWL.DatatypeProperty: 'Datatype Properties',
    OWL.AnnotationProperty: 'Annotation Properties',
    '': 'Other Identifiers',
    OWL.DeprecatedClass: 'Deprecated Classes',
    OWL.DeprecatedProperty: 'Deprecated Properties',
}

HEADERS_SINGULAR = {v: (v[0] + ''.join(
    [(' ' + x.lower()) if x.isupper() else x for x in defrag_iri(k, '#')[1][1:]])
    if k != '' else 'Identifier') for (k, v) in HEADERS.items()}

TYPES = [
    OWL.Class,
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    OWL.AnnotationProperty,
    '',
    OWL.DeprecatedClass,
    OWL.DeprecatedProperty,
]

# Row labels below are ordered
ROW_HEADER_LABELS = {
    RDFS.label: 'Label',
    OWL.deprecated: 'Deprecated',
    DCTERMS.isReplacedBy: 'Is Replaced By',
    SKOS.definition: 'Definition',
    RDFS.comment: "Comment",
    RDF.type: 'Type',
    OWL.inverseOf: 'Inverse Property',
    OWL.equivalentClass: 'Equivalent Class',
    OWL.equivalentProperty: 'Equivalent Property',
    OWL.disjointWith: 'Disjoint With',
    RDFS.subClassOf: 'SubClass Of',
    InvPath(RDFS.subClassOf): 'SubClassed As',
    RDFS.subPropertyOf: 'SubProperty Of',
    InvPath(RDFS.subPropertyOf): 'SubProperties',
    RDFS.seeAlso: 'See Also',
    RDFS.domain: 'Domain',
    InvPath(RDFS.domain): 'Is in Domain Of',
    RDFS.range: 'Range',
    InvPath(RDFS.range): 'Is in Range Of',
    BFFIMETA.relatedValueVocabulary: 'Related value vocabulary',
    DCTERMS.identifier: 'Identifier',
    DCTERMS.coverage: 'Coverage',
    SCHEMA.parentOrganization: 'Parent Organization',
    SCHEMA.location: 'Location',
    SCHEMA.member: 'Has Member',
    FOAF.homepage: 'Homepage',
    BFFIMETA.broadMatch: 'Broad Match',
    BFFIMETA.closeMatch: 'Close Match',
    BFFIMETA.exactMatch: 'Exact Match',
    BFFIMETA.narrowMatch: 'Narrow Match',
    DCTERMS.modified: 'Change Notes',
}

class RDFtoHTML:
    '''
    Class for converting the OWL-based LKD data model into an HTML page.

    Adapted from https://github.com/NatLibFi/Finto-data/blob/master/tools/schema-tools/rdf_to_html.py
    to take into account quirks in LKD data model.
    '''
    def __init__(self):
        parser = ArgumentParser(description='Conversion of LKD data model from RDF to HTML')
        plArg = parser.add_argument('-pl', '--pref-label',
            help='Preferred label property, e.g., rdfs:label or <http://www.w3.org/2000/01/rdf-schema#label>', required=True)
        parser.add_argument('-l', '--language',
            help='Language code of firstly displayed language-tagged literal in HTML documentation', required=True)
        parser.add_argument('-i', '--input-path',
            help='Input path for rdf file', required=True, type=pathlib.Path)
        parser.add_argument('-o', '--output-path',
            help='Output path for html documentation file', required=True, type=pathlib.Path)
        parser.add_argument('-ns', '--namespace',
            help='Namespace of concepts in input file', required=True)
        parser.add_argument('-u', '--base-url',
            help='Base URL of published html file', required=True)
        parser.add_argument('-t', '--title',
            help='Title of HTML document')
        parser.add_argument('-d', '--description',
            help='HTML file containing description of data model to be included to output file')
        parser.add_argument("--embedded-css", default=False, action="store_true",
            help="Create a stand-alone HTML document via embedding the stylesheet rules into it")
        parser.add_argument('-rda', '--rda-vocabularies-path', type=pathlib.Path,
            help="Input path for RDA Vocabularies directory, to be used in showing human readable RDA labels")
        parser.add_argument('-m', '--metadata-path', type=pathlib.Path,
            help='Input path for a separate RDF metadata file, to be used in populating description list')
        parser.add_argument("-r", "--releases-path",
            help="Input path for separate releases csv file")
        oiArg = parser.add_argument('--other-identifiers', default='rdfs:Literal rdfs:Resource',
            help='Other identifiers to be shown in the html documentation file')
        parser.add_argument('-v', '--version',
            help='Explicit version number (in format x.y.z), used to overwrite any such thing defined in metadata file')
        parser.add_argument('-pv', '--prior-version',
            help='Explicit prior version number (in format x.y.z), used to overwrite any such thing defined by metadata file')
        args = parser.parse_args()
        self.language = args.language
        self.input_path = args.input_path
        self.output_path = args.output_path
        self.namespace = args.namespace
        self.base_url = args.base_url
        self.title = args.title
        self.embedded_css = args.embedded_css
        self.rda_path = args.rda_vocabularies_path
        self.description = args.description
        self.metadata_path = args.metadata_path
        self.releases_path = args.releases_path
        self.version = args.version
        self.prior_version = args.prior_version
        self.used_prefixes = set()
        self.graph = Graph(bind_namespaces='none')
        self.combined_graph = Graph(bind_namespaces='none')
        self.combined_graph.parse(self.input_path, format='ttl')
        # identifier for the ontology
        self.URIRef = URIRef(BFFI)

        self.used_prefixes.add('bffi-meta')

        if self.metadata_path:
            self.combined_graph.parse(self.metadata_path, format='ttl', publicID=self.URIRef)

        self.pref_label = self.parse_URIRef_arg(args.pref_label, parser, plArg)

        self.other_identifiers = [
            self.parse_URIRef_arg(x, parser, oiArg) for x in args.other_identifiers.split() if len(x)
        ]

        self.rda = {}
        if self.rda_path:
            for prefix, ns in self.combined_graph.namespaces():
                if ns.startswith(RDA):
                    dir_name = ns.split('/', 4)[3]
                    with open(f"{self.rda_path}/csv/{dir_name}/{prefix}.csv", "r", encoding="utf-8", newline="") as rdafile:
                        csvreader = csv.DictReader(rdafile, delimiter=",")
                        for line in csvreader:
                            self.rda[str(ns + line["*uri"].partition(":")[2])] = line["*label_en" if dir_name == 'Elements' else "*preferred label[0]_en"]

        self.aElems = {}

        self.parse_graph()

    def parse_URIRef_arg(self, arg_str: str, parser: ArgumentParser, action: Action) -> URIRef:
        with contextlib.redirect_stderr(io.StringIO()) as f:
            if arg_str.startswith("<") and arg_str.endswith(">"):
                # NB: does not support relative values
                ret = URIRef(arg_str[1:-1])
            else:
                ret = URIRef(arg_str)
        valid = None if (_:=f.getvalue()) else ret
        try:
            with contextlib.redirect_stderr(io.StringIO()) as f2:
                if ret != (_:=URIRef(util.from_n3(arg_str, nsm=self.combined_graph.namespace_manager))):
                    ret = _
            if valid == None and f2.getvalue():
                parser.error(f"argument {'/'.join(action.option_strings)}: invalid value: '{arg_str}'.")

        except KeyError as e:
            if e.args[0] in ["http", "https", "file"]:
                pass
            else:
                reason = f"Prefix '{e.args[0]}' is not defined. Try encapsulate value with '<' and '>' for literal meaning?"
                parser.error(f"argument {'/'.join(action.option_strings)}: invalid value: '{arg_str}'. Reason: {reason}")
        return ret

    def get_pref_label(self, subject: URIRef, graph: Graph=None, labelPropArr=None, lang=None, warn=True):
        graph = graph or self.graph
        if not labelPropArr:
            labelPropArr = [self.pref_label]
        elif type(labelPropArr) == URIRef:
            labelPropArr = [labelPropArr]
        if not lang:
            lang = self.language

        for property in labelPropArr:
            for object in graph.objects(subject, property):
                if type(object) == Literal:
                    if object.language:
                        if lang == object.language:
                            return object
                    else:
                        return object
                else:
                    return object
        if warn:
            logging.warning(f'Unable to find a label for {subject}')

    def sort_properties_with_id(self, properties):
        sorted_labels = sorted(properties.keys(), key=str.casefold)

        sorted_properties = {}
        for i, subject in enumerate(sorted_labels):
            sorted_properties.update({subject: properties[subject]})

        return sorted_properties

    def create_hyperlink_elem(self, identifier: URIRef, resort_marker_elem=None) -> etree.ElementBase:
        if identifier in self.aElems:
            return copy.copy(self.aElems[identifier])
        if identifier.startswith(self.namespace):
            dfrag = defrag_iri(identifier)
            (aElem := Element('a', attrib={'href': '#' + dfrag[1]})).text = dfrag[1]
            # test that a label exists
            self.get_pref_label(identifier)
            self.aElems[identifier] = aElem
            return copy.copy(aElem)

        aElem = Element('a', attrib={'href': (href:=str(identifier)), 'target': '_blank'}) #type: etree.ElementBase

        qname = identifier.n3(self.graph.namespace_manager)
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
        elif identifier.startswith(RDA):
            if (rda_label:=self.rda.get(href, None)):
                aElem.text += f" ({rda_label})"
            else:
                if '/termList/' in href:
                    # IRI is of form /termList/xyz where xyz already tells us enough about the label
                    pass
                else:
                    logging.warning(f"RDA label not found for {aElem.text}")
        elif (yso:=href.startswith("http://www.yso.fi")) or href.startswith("http://urn.fi"):
            # local source is of form finto/vocid/lname.ttl
            local_rdf_source = os.path.join("resolver/finto/", (_:=href.split('/' if yso else ':'))[-2], _[-1] + ".ttl")
            os.makedirs(os.path.dirname(local_rdf_source), exist_ok=True)
            if os.path.exists(local_rdf_source):
                g = Graph().parse(local_rdf_source)
            else:
                g = Graph().parse(href)
                g.serialize(destination=local_rdf_source)
                logging.info(f"Downloaded Finto.fi-based link to {local_rdf_source}.")

            if (aLabel:= self.get_pref_label(identifier, g, SKOS.prefLabel, warn=False)):
                aElem.text = aLabel
                if yso and (identifier, SKOS.inScheme, URIRef("http://www.yso.fi/onto/yso/places")) in g:
                    aElem.tail = f" (yso-paikat)"
                else:
                    aElem.tail = f" ({_[-2]})"

        elif href.startswith("https://orcid.org/"):
            local_rdf_source = os.path.join("resolver/orcid/", href.rpartition('/')[2] + ".ttl")
            os.makedirs(os.path.dirname(local_rdf_source), exist_ok=True)
            if os.path.exists(local_rdf_source):
                g = Graph().parse(local_rdf_source)
            else:
                g = Graph().parse(href)
                g.serialize(destination=local_rdf_source)
                logging.info(f"Downloaded ORCID link to {local_rdf_source}.")
                # only send 120 requests per minute
                time.sleep(0.5)
            aElem.text = g.value(identifier, RDFS.label)
        elif href.startswith("http://www.wikidata.org/"):
            local_rdf_source = os.path.join("resolver/wikidata/", href.rpartition('/')[2] + ".ttl")
            os.makedirs(os.path.dirname(local_rdf_source), exist_ok=True)
            if os.path.exists(local_rdf_source):
                g = Graph().parse(local_rdf_source)
            else:
                g = Graph().parse(href)
                g.serialize(destination=local_rdf_source)
                logging.info(f"Downloaded Wikidata link to {local_rdf_source}.")
                # only send 120 requests per minute
                time.sleep(0.5)
            if (aLabel:= self.get_pref_label(identifier, g, SKOS.prefLabel, warn=False)):
                aElem.text = aLabel
        elif "://isni.org/isni/" in href:
            local_rdf_source = os.path.join("resolver/isni/", (isni_id:=href.rpartition('/')[2]) + "-wikidata.ttl")
            os.makedirs(os.path.dirname(local_rdf_source), exist_ok=True)
            isni_lit = Literal(" ".join(textwrap.wrap(isni_id, 4)))
            if os.path.exists(local_rdf_source):
                g = Graph().parse(local_rdf_source)
            else:
                # ISNI does not readily serve RDF, use Wikidata instead
                q = prepareQuery('''CONSTRUCT {
    ?s wdt:P213 ?isni.
    ?s rdfs:label ?label.
    ?s wdtn:P244 ?lc.
    ?s wdtn:P8980 ?finaf.
}
WHERE {
    SERVICE <https://query.wikidata.org/sparql> {
        ?s wdt:P213 ?isni .
        ?s rdfs:label ?label .
        OPTIONAL {?s wdtn:P244 ?lc}
        OPTIONAL {?s wdtn:P8980 ?finaf}
    }
}''', initNs = { 'rdfs': RDFS, 'wdt': URIRef("http://www.wikidata.org/prop/direct/"), 'wdtn': (wdtn:=Namespace("http://www.wikidata.org/prop/direct-normalized/")) }
                )

                g = Graph().query(q, initBindings={'isni': isni_lit}).graph
                g.serialize(destination=local_rdf_source, format="ttl")
                logging.info(f"Downloaded ISNI link to {local_rdf_source}.")
                # only send 120 requests per minute
                time.sleep(0.5)
            if (len((_:=list(g.subjects(object=isni_lit, unique=True))))) == 1:
                if (aLabel:=self.get_pref_label(_[0], g, RDFS.label)):
                    aElem.text = aLabel
                    aElem.tail = " (isni)"

        if identifier in self.other_identifiers:
            aElem.attrib['href'] = '#' + aElem.text
            del aElem.attrib['target']
        if resort_marker_elem is not None:
            resort_marker_elem.set('resort', "true")

        if not (ns:=qname.split(':')[0]).startswith('<http') and aElem.text.startswith(ns+':'):
            self.used_prefixes.add(ns)

        self.aElems[identifier] = aElem
        return copy.copy(aElem)

    def create_contents(self, html_elem, header: str, properties):
        SubElement(html_elem, 'h2', id=header.replace(' ', '')).text = header
        ul_elem = SubElement(html_elem, 'ul')
        for idx, subject in enumerate(properties):
            result = defrag_iri(subject)
            if result:
                # FIXME fragment = result[1]
                fragment = result[1] if result[0] == str(self.URIRef) else subject.n3(self.graph.namespace_manager)
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
                if result[0] != str(self.URIRef): # FIXME
                    result = (result[0], subject.n3(self.graph.namespace_manager))
                table = SubElement(tableContainerDiv, 'table', id=result[1])
                tablerow = SubElement(table, 'tr', attrib={'class': 'trHeading'})
                SubElement(tablerow, 'td', attrib={'class': 'key'}).text = HEADERS_SINGULAR[header] + ':'
                td_value = SubElement(tablerow, 'td', attrib={'class': 'value'}) #type: etree.ElementBase
                SubElement(td_value, 'a', href='#' + result[1]).text = result[1]
                if header.startswith("Deprecated"):
                    td_value[0].tail = " (deprecated)"

                if (partition:=str(subject).partition("http://urn.fi/"))[1] and not partition[0]:
                    table.append(etree.fromstring(f'<tr><td class="key">URN</td><td class="value"><div><a href="{subject}">{partition[2]}</a></div></td></tr>'))
                else:
                    table.append(etree.fromstring(f'<tr><td class="key">IRI</td><td class="value"><div>{subject}</div></td></tr>'))
                for prop in properties[subject]:
                    # only show types in 'Other Identifiers' section
                    if prop == RDF.type and header != "Other Identifiers":
                        continue
                    tablerow = SubElement(table, 'tr')
                    (td_key:=SubElement(tablerow, 'td')).text = ROW_HEADER_LABELS[prop]

                    td_key.set('class', 'key')
                    td_value_orig = SubElement(tablerow, 'td', attrib={'class': 'value'}) #type: etree.ElementBase

                    for idx, value in enumerate(properties[subject][prop]):
                        td_value = SubElement(td_value_orig, 'div')
                        if type(value) == URIRef:
                            aElem = self.create_hyperlink_elem(value, resort_marker_elem=td_value_orig)
                            href = aElem.attrib['href']
                            td_value.append(aElem)

                            if prop == RDFS.subClassOf:
                                if href[0] == "#":
                                    aElem.set('class', 'todo')

                            elif type(prop) == InvPath and ((dom:=prop==InvPath(RDFS.domain)) or prop == InvPath(RDFS.range)):
                                tablerow.set('class', "isInDomainOf" if dom else "isInRangeOf")
                                aElem.tail = (aElem.tail or '') + (" → " if dom else " ← ")
                                for node in self.graph.objects(value, RDFS.range if dom else RDFS.domain):
                                    if type(node) == URIRef:
                                        td_value.append(self.create_hyperlink_elem(node))
                                    elif type(node) == BNode:
                                        aElem.tail += "{"
                                        unionOf = self.graph.value(node, OWL.unionOf, any=False)
                                        union_len = len(list(self.graph.items(unionOf)))
                                        for idx2, x in enumerate(self.graph.items(unionOf), start=1):
                                            td_value.append((_:=self.create_hyperlink_elem(x)))
                                            if idx2 < union_len:
                                                _.tail = (_.tail or '') + ", "
                                            else:
                                                _.tail = (_.tail or '') + "}"
                                    else:
                                        logging.warning("Encountered literal, skipping in {value} {prop} {node}")

                        elif type(value) == BNode:
                            unionOf = self.graph.value(value, OWL.unionOf, any=False)
                            union_len = len(list(self.graph.items(unionOf)))
                            td_value.text = 'Union of '

                            for idx2, x in enumerate(self.graph.items(unionOf), start=2):
                                td_value.append((_:=self.create_hyperlink_elem(x)))
                                if idx2 < union_len:
                                    _.tail = (_.tail or '') + ", "
                                elif idx2 == union_len:
                                    _.tail = (_.tail or '') + ' and '

                        else:
                            #type(value) == Literal:
                            if value.datatype == XSD.boolean:
                                rawText = "Yes" if str(value) == "true" else "No"
                            else:
                                rawText = str(value) + (f" ({value.language})" if value.language != None else '')

                            if prop == DCTERMS.modified:
                                rawText = f"{rawText[:10]}: {rawText[12:-1]}" 

                            try:
                                litText = etree.fromstring(rawText)
                                td_value.append(litText)
                            except etree.XMLSyntaxError:
                                try:
                                    litText = etree.fromstring(rawText)
                                    td_value.append(litText)
                                except etree.XMLSyntaxError:
                                    td_value.text = rawText

                    if td_value_orig.get('resort', None):
                        td_value_orig[:] = sorted(td_value_orig[:], key=lambda _: (_[0].text or '') + (_[0].tail or ''))
                        del td_value_orig.attrib['resort']

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
        data_model = {} # type: dict[URIRef, InvPath]

        transitive_prop_list = [
            RDFS.subClassOf,
            InvPath(RDFS.subClassOf),
            RDFS.subPropertyOf,
            InvPath(RDFS.subPropertyOf),
        ]

        q = prepareQuery(
            'SELECT ?s ?p WHERE { ?s ?p ?o . ?o owl:unionOf ?o2 . ?o2 rdf:rest*/rdf:first ?o3 .}',
            initNs = { 'owl': OWL, 'rdf': RDF }
        )

        for ns in self.graph.namespaces():
            self.graph.namespace_manager.bind(ns[0], ns[1])
        for t in TYPES:
            data_model[t] = {}
            for subject in (self.graph.subjects(RDF.type, t) if t != '' else self.other_identifiers):
                if type(subject) == BNode:
                    # Not supported at the moment
                    continue

                fragment = None
                result = defrag_iri(subject)
                if result:
                    fragment = result[1]
                pref_label = self.get_pref_label(subject, warn=False)
                if not pref_label and subject in self.other_identifiers:
                    # FIXME: refactor
                    pref_label = subject.n3(self.graph.namespace_manager)
                if pref_label and fragment:
                    properties = dict((x, set(self.graph.objects(subject, x))) for x in ROW_HEADER_LABELS.keys())

                    for obj, prop in self.graph.query(q, initBindings={'o3': subject}):
                        properties[InvPath(prop)].add(obj)

                    for pred in ROW_HEADER_LABELS.keys():
                        if len(properties[pred]) == 0:
                            del properties[pred]
                            continue

                        if pred in transitive_prop_list:
                            for obj in self.graph.transitive_objects(subject, pred):
                                if subject != obj and not obj.startswith("http://id.loc.gov/ontologies/"):
                                    properties[pred].add(obj)

                        properties[pred] = sorted(
                            properties[pred],
                            key=lambda k: (
                                (lang:=None if not isinstance(k, Literal) or k.datatype else k.language or "") != self.language,
                                lang,
                                k
                            )
                        )

                    data_model[(t if t else '')][subject] = properties
                else:
                    logging.warning('PrefLabel or URI fragment missing from %s. Skipping.' % subject)

        html_elem = Element('html') # type: etree.ElementBase
        head_elem = SubElement(html_elem, 'head') # type: etree.ElementBase
        if self.title:
            SubElement(head_elem, 'title').text = self.title
        SubElement(head_elem, 'meta', attrib={
            'http-equiv': 'Content-Type',
            'content': 'text/html; charset=utf-8',
        })

        if self.embedded_css:
            SubElement(head_elem, 'style').text = pathlib.Path('stylesheet.css').read_text()
        else:
            SubElement(head_elem, 'link', rel='stylesheet', href='stylesheet.css')

        SubElement(head_elem, 'script').text = \
'''
function hideSuperclassProps(){Array.from(document.getElementsByClassName('superclassProps')).forEach(function(i){i.classList.add('hide'); let e; if ((e=i.previousElementSibling).innerHTML.length == 1) {e.innerHTML = "⯈";}})}

function showSuperclassProps(){Array.from(document.getElementsByClassName('superclassProps')).forEach(function(i){i.classList.remove('hide'); let e; if ((e=i.previousElementSibling).innerHTML.length == 1) {e.innerHTML = "⯆";}})}

function toggleElemSuperclassProps(elem){let ret; elem.parentElement.querySelectorAll(".superclassProps").forEach(function(i){ret=i.classList.toggle('hide');}); elem.innerHTML = ret ? "⯈" : "⯆";}

document.addEventListener("DOMContentLoaded", function(){hideSuperclassProps(); let b=document.body; setTimeout(function(){b.removeAttribute('style');}, 0);});

'''

        # FIXME: simplify above using css classes on parent element and rules based on that
        body_elem = SubElement(html_elem, 'body', attrib={'class': 'no-js', 'style': 'visibility:hidden'}) # type: etree.ElementBase
        SubElement(body_elem, 'script').text = 'document.body.classList.remove("no-js")';
        if self.description:
            description_tree = etree.parse(self.description, etree.HTMLParser(encoding='utf-8')) # type: etree._ElementTree
            if self.releases_path and self.version:
                with open(self.releases_path, "r", encoding="utf-8", newline="") as releases_file:
                    csvreader = csv.DictReader(releases_file, delimiter=",")
                    for row in csvreader:
                        if row['owl:versionInfo'] == self.version:
                            for lang in ['fi', 'en']:
                                prevpElem = description_tree.xpath(f'//p[@id="description-general-{lang}"]')[0] # type: etree.ElementBase
                                (pElem:=Element('p', attrib={'id': f'description-version-specific-{lang}'})).text = row[f'html-{lang}']
                                prevpElem.addnext(pElem)
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

        divItem = self.createDlItemForProperty(DCTERMS.publisher, graph=self.combined_graph, dt_text='Publisher', external_dl=True)
        if len(divItem) > 1:
            dl_elem.append(divItem)

        divItem = self.createDlItemForProperty(DCTERMS.contributor, graph=self.combined_graph, dt_text='Contributor', external_dl=True)
        if len(divItem) > 1:
            dl_elem.append(divItem)

        SubElement(body_elem, 'p').text = 'Copyright: © The National Library of Finland, 2022-2024'

        SubElement(body_elem, 'p', attrib={'class': 'fw-bold'}).text = 'Prefixes in this document'

        dl_prefix_elem = SubElement(body_elem, 'dl', attrib={'class': 'prefixes'})

        SubElement(body_elem, 'p', attrib={'class': 'fw-bold margin-top-20'}).text = 'Document view settings'
        button_panel = SubElement(body_elem, 'div', attrib={'class': 'button-panel'})
        SubElement(button_panel, 'button', attrib={'onclick': 'showSuperclassProps();'}).text = 'Show superclass properties'
        SubElement(button_panel, 'button', attrib={'onclick': 'hideSuperclassProps();'}).text = 'Hide superclass properties'

        for t in data_model:
            data_model[t] = self.sort_properties_with_id(data_model[t])

        for t in data_model:
            if data_model[t]:
                self.create_contents(body_elem, HEADERS[t], data_model[t])
        for t in data_model:
            if data_model[t]:
                self.create_properties(body_elem, HEADERS[t], data_model[t])

        # copy domain and range values from superclasses to subclasses
        for todo in body_elem.findall(".//a[@class='todo']"):
            todo: etree.ElementBase
            todo_id = todo.attrib['href'][1:]

            superClassElem = body_elem.find(f"./div/table[@id='{todo_id}']")
            for i, k in enumerate(['isInRangeOf', 'isInDomainOf']):
                ulElem = Element('ul', attrib={'class': f'superclassProps {"outwards" if i == 1 else "inwards"}'})
                for propDivContainer in superClassElem.findall(f".//tr[@class='{k}']/td/div"):
                    # only copy first link
                    b = copy.copy(propDivContainer[0])
                    # drop false positives
                    if b.text == None:
                        continue
                    # drop redundant tail
                    b.tail = None
                    li = SubElement(ulElem, 'li')
                    li.append(b)
                if len(ulElem):
                    todo.addnext(ulElem)
            del todo.attrib['class']

            if todo.getnext() is not None:
                (buttonElem:=Element('button', attrib={'onclick': 'toggleElemSuperclassProps(this);'})).text = '⯆'
                todo.addnext(buttonElem)

        for prefix in sorted(self.used_prefixes):
            nsm = self.combined_graph.namespace_manager
            dt_prefix_div = f'<div><dt>{prefix}</dt><dd>{nsm.expand_curie(prefix+":")}</dd></div>'
            dl_prefix_elem.append(etree.fromstring(dt_prefix_div))

        etree.indent(html_elem)
        with open(self.output_path, 'wb') as output:
            output.write(etree.tostring(html_elem, encoding='utf-8', doctype='<!DOCTYPE html>', method='html'))

        # remove duplicate dct:description triples, prefer more specific ones defined in self.graph
        for literal in self.graph[self.URIRef:DCTERMS.description:]:
            for _ in self.combined_graph.objects(self.URIRef, DCTERMS.description):
                if literal.startswith(_) and len(literal) > len(_):
                    self.combined_graph.remove((self.URIRef, DCTERMS.description, _))
                    break

        self.combined_graph.serialize(format='turtle', destination='LKD-combined.ttl')

    def createDlItemForProperty(self, prop : URIRef, graph: Graph=None, dt_text=None, dd_value=None, dd_type=None, subject=None, external_dl=False) -> etree.ElementBase:
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
                    if (aLabel := self.get_pref_label(object, graph, warn=False)):
                        aElem.text = aLabel
                    if not aLabel and external_dl:
                        aElem2 = self.create_hyperlink_elem(object)
                        aElem.text = aElem2.text
                        del aElem2
                else:
                    if object.language:
                        logging.warning('Not implemented: language tagged literal')
                    else:
                        dd.text = str(object)
        return div

if __name__ == '__main__':
    RDFtoHTML()