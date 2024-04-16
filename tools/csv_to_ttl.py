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

import argparse
import csv
import datetime
import logging
import os

import rdflib # separate import for triggering autocomplete behavior in IDE
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD, NamespaceManager
from rdflib.plugins.sparql.processor import prepareQuery
from rdflib.util import from_n3

# treat these CSV cell values as empty/missing
EMPTY_COL_VALS = set(["", "#N/A", "N/A", "?"])

class DataModelConverter:
    def __init__(self):
        parser = argparse.ArgumentParser(description="CSV to TTL converter to be used in LKD data model (Finnish BIBFRAME) conversion")
        parser.add_argument("-i", "--input-path",
            help="Input path for LKD csv file", required=True)
        parser.add_argument("-o", "--output-path",
            help="Output path for data model", required=True)
        parser.add_argument('-O', '--log',
            help='Log file name. Default is to use standard error')
        parser.add_argument('-D', '--debug', default=False, action="store_true",
            help='Show debug output')
        parser.add_argument("-p", "--prefixes-path",
            help="Input path for prefixes file to be used in processing the csv file", required=True)
        parser.add_argument("-url", "--publishing-url",
            help="Base URL for published data model", default="http://schema.finto.fi/bffi/")
        parser.add_argument("-m", "--metadata-path",
            help="Input path for separate data model metadata file")
        parser.add_argument("-c", "--change-notes-path",
            help="Input path for separate change notes csv file")
        parser.add_argument("-r", "--releases-path",
            help="Input path for separate releases csv file")
        parser.add_argument("--write-rdfxml", default=False, action="store_true",
            help="Serialize as RDF/XML (.rdf), too")
        parser.add_argument("-v", "--version",
            help="Explicit version number (in x.y.z format)")
        parser.add_argument("-pv", "--prior-version",
            help="Explicit prior version number (in x.y.z format)")
        args = parser.parse_args()
        self.input_path = args.input_path
        self.output_path = args.output_path
        self.debug = args.debug
        self.log = args.log
        self.prefixes_path = args.prefixes_path
        self.publishing_url = args.publishing_url
        self.metadata_path = args.metadata_path
        self.change_notes_path = args.change_notes_path
        self.releases_path = args.releases_path
        self.write_rdfxml = args.write_rdfxml
        self.version = args.version
        self.prior_version = args.prior_version

        self.graph = Graph(bind_namespaces='none').parse(self.prefixes_path)
        self.meta_graph = Graph(bind_namespaces='none')
        self.cnotes_graph = Graph(bind_namespaces='none')
        self.bf_graph = Graph()
        self.versioning_dates = {}

        # configure logging, messages to stderr by default
        logformat = '%(levelname)s: %(message)s'
        loglevel = logging.INFO
        if self.debug:
            loglevel = logging.DEBUG
        if self.log:
            logging.basicConfig(filename=self.log,
                                format=logformat, filemode='w+', level=loglevel)
        else:
            logging.basicConfig(format=logformat, level=loglevel)

        # identifier for the ontology
        self.URIRef = bffiURIRef = URIRef(self.graph.namespace_manager.expand_curie('bffi:'))
        self.meta_URIRef = URIRef(self.graph.namespace_manager.expand_curie('bffi-meta:'))

        if self.metadata_path:
            self.meta_graph.parse(self.metadata_path, format="ttl")
            self.graph += self.meta_graph

        self.nsm = NamespaceManager(self.graph, 'none')

        if self.releases_path and self.version:
            with open(self.releases_path, "r", encoding="utf-8", newline="") as releases_file:
                csvreader = csv.DictReader(releases_file, delimiter=",")
                for row in csvreader:
                    version_info = row['owl:versionInfo'].strip()
                    if (issued_date:=row['dct:issued'].strip()):
                        self.versioning_dates[version_info] = Literal(issued_date, datatype=XSD.date)

                    if version_info == self.version:
                        if issued_date:
                            self.graph.add(
                                (bffiURIRef, DCTERMS.issued, self.versioning_dates[version_info])
                            )
                        to_be_removed = []
                        for literal in self.graph.objects(bffiURIRef, DCTERMS.description):
                            if (desc_end := row['dct:description-' + (lang:=literal.language)].strip()):
                                self.graph.add(
                                    (bffiURIRef, DCTERMS.description, Literal(' '.join([literal, desc_end]), lang ))
                                )
                                to_be_removed.append((bffiURIRef, DCTERMS.description, literal))
                        for triple in to_be_removed:
                            self.graph.remove(triple)

        curdate = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        if (bffiURIRef, DCTERMS.issued, None) not in self.graph and self.version:
            self.graph.add((bffiURIRef, DCTERMS.issued, Literal(curdate[:10], datatype=XSD.date)))

        if self.version:
            versionIRI = self.publishing_url + self.version.replace(".", "-") + "/"
            self.graph.remove((bffiURIRef, OWL.versionIRI, None))
            self.graph.add((bffiURIRef, OWL.versionIRI, URIRef(versionIRI)))

            self.graph.remove((bffiURIRef, OWL.versionInfo, None))
            self.graph.add((bffiURIRef, OWL.versionInfo, Literal(self.version)))

        if self.prior_version:
            prior_version = self.publishing_url + self.prior_version.replace(".", "-") + "/"
            self.graph.remove((bffiURIRef, OWL.priorVersion, None))
            self.graph.add((bffiURIRef, OWL.priorVersion, URIRef(prior_version)))

        # always update modified date
        self.graph.remove((bffiURIRef, DCTERMS.modified, None))
        self.graph.add((bffiURIRef, DCTERMS.modified, Literal(curdate, datatype=XSD.dateTime)))

        if self.change_notes_path and self.versioning_dates:
            self.processChangeNotesCSV()

        self.convertCSV()

        bffi_subjects = set(self.graph.subjects())

        for cnote_subject in self.cnotes_graph.subjects(unique=True):
            if cnote_subject not in bffi_subjects:
                # change note defined for nonexistent bffi subject
                logging.warning(f"{cnote_subject} has only a change note stated about it")
                continue
            cnote_depr = (cnote_subject, OWL.deprecated, Literal(True)) in self.graph
            depr_notice_shown = False
            for cnoteLit in self.cnotes_graph[cnote_subject:DCTERMS.modified:]:
                if cnote_depr and not str(cnoteLit)[12:].startswith("Deprecated"):
                    if not depr_notice_shown:
                        logging.debug(f"{cnote_subject} is deprecated, dropping non-essential change notes")
                        depr_notice_shown = True
                    continue
                else:
                    self.graph.add((cnote_subject, DCTERMS.modified, cnoteLit))

        for relation in self.graph.objects(bffiURIRef, DCTERMS.relation):
            if (
                isinstance(relation, URIRef)
                and (relation_str:=relation.toPython()).startswith("http://id.loc.gov/ontologies/")
                and relation_str[-1] == "/"
            ):
                local_bf_source = os.path.join(os.path.dirname(__file__), relation.split("/")[-2] + ".ttl")
                if os.path.exists(local_bf_source):
                    bf_graph = Graph().parse(local_bf_source)
                else:
                    bf_graph = Graph().parse(relation)
                    bf_graph.serialize(destination=local_bf_source)
                    logging.info(f"Downloaded LoC ontology file to {local_bf_source}.")
                bf_definition_prefix = "BFLC definition: " if "bflc" in relation_str else "BIBFRAME definition: "

                for bffi_subject, bf_object in self.graph[:OWL.equivalentClass|OWL.equivalentProperty:]:
                    for bf_definition in bf_graph[bf_object:SKOS.definition]:
                        self.graph.add((bffi_subject, SKOS.definition, Literal(bf_definition_prefix + bf_definition, 'en')))
                self.bf_graph += bf_graph
        self.validate()
        self.serialize()
        if self.write_rdfxml:
            if self.output_path[-4:] == ".ttl":
                self.graph.serialize(format="xml", destination=self.output_path[:-4]+".rdf",)
            else:
                self.graph.serialize(format="xml", destination=self.output_path+".rdf")

    def from_n3(self, s: str):
        """
        Adds converter-specific namespace manager to the original rdflib.util.from_n3 function.

        Parameters:
            s (str): an n3 string as defined by rdflib

        Returns:
            An rdflib identifier corresponding to the given n3 string
        """
        return from_n3(s, nsm=self.nsm)

    def processComplexCol(self, s: URIRef, p: URIRef, o: str) -> None:
        """
        Process a column value that may require owl:unionOf structure to be constructed.

        Adds triples to the converter-specific graph whilst processing.

        Parameters:
            s (URIRef): triple subject
            p (URIRef): triple predicate
            o (str): triple object (may require owl:unionOf expansion in case of complex value)
        """
        # values starting with "[" are expected to be unions and are expected
        # to have their items separated by commas
        if o.startswith("["):
            if not o.endswith("]"):
                raise ValueError(f"Found union start (square bracket) without union end in {s} {p} {o}!")
            stripped = o[1:-1].strip()
            if "[" in stripped or "]" in stripped:
                raise ValueError(f"There is no support for nested brackets! Got {s} {p} {o}")
            # strip and drop empty values
            union_items = [item for _ in stripped.split(",") if (item := _.strip(" {}"))]
            if len(union_items) < 2:
                raise ValueError(f"Expanded union had less than two elements in it! Got {s} {p} {o}")
            expanded_items = [self.graph.namespace_manager.expand_curie(item) if not item.startswith("http") else item for item in union_items]
            joined_items = "> <".join(expanded_items)
            data_to_be_parsed = f"<{s}> <{p}> [ a <{OWL.Class}> ; <{OWL.unionOf}> ( <{joined_items}> ) ] ."
            self.graph.parse(data=data_to_be_parsed)
        else:
            # single value expected
            self.graph.add((s, p, self.from_n3(o)))

    def _validateOntology(self, s):
        # TODO: add more tests
        curie = self.nsm.curie(s)
        if str(self.graph.value(s, DCTERMS.modified))[:10] < str(self.graph.value(s, DCTERMS.issued)):
            logging.warning(f"{curie} is modified before issued!")

    def validate(self):
        # validate for some identified issues in the past, add more as necessary
        # TODO: refactor, add more tests
        q2 = prepareQuery(
            'SELECT DISTINCT ?o WHERE { ?s ?p ?o . ?s ?p2 ?o . FILTER(STR(?p) < STR(?p2) && (?p != rdfs:domain && ?p2 != rdfs:range))}',
            initNs = { 'rdfs': RDFS }
        )

        for s in sorted(self.graph.subjects(unique=True), key=str.casefold):
            if not isinstance(s, URIRef):
                continue
            (prefix, ns_uriref, name) = qname_partition = self.nsm.compute_qname(s)
            if not ns_uriref in [self.URIRef, self.meta_URIRef]:
                continue
            curie = ':'.join([prefix, name])
            if (s, RDF.type, OWL.Ontology) in self.graph:
                self._validateOntology(s)
                continue

            # common tests
            # TODO: refactor
            if not (s, RDFS.label, None) in self.graph:
                logging.warning(f"{curie} is missing labels!")

            for result_row in self.graph.query(q2, initBindings={'s': s}):
                logging.warning(f"{curie} has more than 1 relationship with {self.nsm.curie(result_row['o'])}")

            for o in self.graph.objects(s):
                if str(o).startswith(str(self.URIRef)) and not (o, None, None) in self.graph:
                    logging.warning(f"{curie} object {self.nsm.curie(o)} is missing triples!")

            for modified in self.graph[s:DCTERMS.modified:]:
                if str(modified).endswith(" (New)"):
                    break
            else:
                if self.version:
                    logging.warning(f"{curie} is missing (New) timestamp!")
            if (depr:=((s, OWL.deprecated, Literal(True)) in self.graph)):
                if (None, None, s) in self.graph:
                    logging.warning(f"{curie} is deprecated but is in object position!")

            if (s, RDF.type, OWL.Class) in self.graph or (s, RDF.type, OWL.DeprecatedClass) in self.graph:
                if name[:1].islower():
                    logging.warning(f"{curie} is expected to start with uppercase!")
            elif name[:1].isupper():
                logging.warning(f"{curie} is expected to start with lowercase!")

            if (s, RDF.type, OWL.ObjectProperty) in self.graph:
                for (s2, o2) in self.graph[:s:]:
                    if isinstance(o2, Literal): 
                        logging.warning(f"{curie} may not have literal value object!")
            if (s, RDF.type, OWL.DatatypeProperty) in self.graph:
                if not (s, RDFS.range, RDFS.Literal) in self.graph:
                    logging.warning(f"{curie} should have rdfs:Literal as range!")
                for o in self.graph[s:RDFS.range:]:
                    if not o == RDFS.Literal:
                        logging.warning(f"{curie} should have rdfs:Literal as range!")
                for (s2, o2) in self.graph[:s:]:
                    if not isinstance(o2, Literal): 
                        logging.warning(f"{curie} may not have non-literal value object!")
                pass
            if (s, RDF.type, OWL.AnnotationProperty) in self.graph:
                if (s, RDFS.range|RDFS.domain, None) in self.graph:
                    logging.warning(f"{curie} is not allowed to have property axioms!")

    def processChangeNotesCSV(self):
        """
        Processes the change notes CSV document and adds resulting triples to the change notes graph for later usage.
        """
        if self.version:
            versionTuple = tuple(self.version.split("."))
            if len(versionTuple) != 3:
                logging.warning("Version numbering does not match MAJOR.MINOR.PATCH model. Disabling checks")
                versionTuple = (0, 0, 0)
        else:
            versionTuple = (0, 0, 0)

        with open(self.change_notes_path, "r", encoding="utf-8", newline="") as csvfile:
            csvreader = csv.DictReader(csvfile, delimiter=",")

            for row in csvreader:
                row = dict((x, y.strip()) for (x, y) in row.items())
                if not row['changeNote']:
                    continue

                cnote_iri = self.nsm.expand_curie(row['lkd-id'])
                change_version = row["version"].strip("v")
                cnote_version_tuple = tuple(change_version.split("."))

                if len(cnote_version_tuple) != 3:
                    logging.warning(f"{cnote_iri} change version {change_version} does not match MAJOR.MINOR.PATCH model")
                elif cnote_version_tuple > versionTuple:
                    # drop change notes determined to be in a future version
                    continue

                change_date_str = str(self.versioning_dates[change_version])

                for note in self.cnotes_graph[cnote_iri:DCTERMS.modified:]:
                    if str(note).startswith(change_date_str):
                        logging.warning(f"Multiple change notes detected for {cnote_iri} in version {change_version}")

                cnote_str = f"{change_date_str} ({row['changeNote']})"
                self.cnotes_graph.add((cnote_iri, DCTERMS.modified, Literal(cnote_str)))

    def convertCSV(self):
        """
        Converts the CSV document and adds resulting triples to the conversion-specific graph.
        """
        BFFI = rdflib.Namespace(self.nsm.expand_curie('bffi:'))
        BFFIMETA = rdflib.Namespace(self.nsm.expand_curie('bffi-meta:'))
        with open(self.input_path, "r", encoding="utf-8", newline="") as csvfile:
            csvreader = csv.DictReader(csvfile, delimiter=",")

            # initialize previous row variable
            prevRow = dict((x, "") for x in csvreader.fieldnames)

            for row in csvreader:
                # strip all column values before use and map special values to empty strings
                row = dict((x, _) if (_ := y.strip()) not in EMPTY_COL_VALS else (x, "") for (x, y) in row.items())

                # drop unwanted rows
                if row["lkd status"] not in ["published", "planned", "deprecated"]:
                    continue

                id = row["lkd-id"]

                if not id.startswith("bffi:"):
                    raise ValueError("BFFI-id is not within the bffi: namespace: " + id)
                bffi_id = BFFI[id[5:]]

                # modified - new
                if (bffi_new_version:=row["julkaisuversio"].strip("v")):
                    while len(bffi_new_version.split(".")) < 3:
                        bffi_new_version += ".0"
                    if bffi_new_version.startswith("0.") and int(bffi_new_version.split(".")[1]) < 4 or bffi_new_version == "0.4.0":
                        self.graph.add(
                            (bffi_id, DCTERMS.modified, Literal("2024-02-23 (New)"))
                        )
                    else:
                        if self.versioning_dates:
                            self.graph.add(
                                (bffi_id, DCTERMS.modified, Literal(str(self.versioning_dates[bffi_new_version]) + " (New)"))
                            )

                # labels
                self.graph.add((bffi_id, RDFS.label, Literal(row["lkd rdfs:label-en"], "en")))
                self.graph.add((bffi_id, RDFS.label, Literal(row["lkd rdfs:label-fi"], "fi")))
                #self.graph.add((bffi_id, RDFS.label, Literal(row["lkd rdfs:label-sv"], "sv")))

                # domain
                domainCol = "lkd rdfs:domain"
                if (bffi_domain := row[domainCol]) and (id != prevRow["lkd-id"] or bffi_domain != prevRow[domainCol]):
                    self.processComplexCol(bffi_id, RDFS.domain, bffi_domain)

                # range
                rangeCol = "lkd rdfs:range"
                if (bffi_range := row[rangeCol]) and (id != prevRow["lkd-id"] or bffi_range != prevRow[rangeCol]):
                    self.processComplexCol(bffi_id, RDFS.range, bffi_range)

                # related value vocabulary
                bffi_rvv = row["bffi-meta:relatedValueVocabulary"]
                for item in [_.strip() for _ in bffi_rvv.split(",") if bffi_rvv]:
                    self.graph.add((bffi_id, BFFIMETA.relatedValueVocabulary, self.from_n3(item)))

                # type
                bffi_type = row["bffi: rdf:type"]
                if (bffi_id_isClass:=bffi_type == "owl:Class"):
                    self.graph.add((bffi_id, RDF.type, OWL.Class))
                elif bffi_type in ["owl:ObjectProperty", "owl:SymmetricProperty"]:
                    self.graph.add((bffi_id, RDF.type, OWL[bffi_type[4:]]))
                    self.graph.add((bffi_id, RDF.type, OWL.ObjectProperty))
                    if (bffi_id, RDFS.range, None) not in self.graph:
                        # set rdfs:range to rdfs:Resource in case no range specified (handled previously)
                        self.graph.add((bffi_id, RDFS.range, RDFS.Resource))
                elif bffi_type == "owl:DatatypeProperty":
                    self.graph.add((bffi_id, RDF.type, OWL.DatatypeProperty))
                    empty = True  # helper variable for checking out if rdfs:range is empty
                    for range in self.graph.objects(bffi_id, RDFS.range):
                        empty = False
                        if range != RDFS.Literal:
                            raise ValueError(f"Property {bffi_id} has rdfs:range of {bffi_range} (expected rdfs:Literal due to rdf:type owl:DatatypeProperty)")
                    if empty:
                        # set rdfs:range to rdfs:Literal in case no range specified (handled previously)
                        self.graph.add((bffi_id, RDFS.range, RDFS.Literal))
                else:
                    raise ValueError(f"{bffi_id} had an unexpected type value, got {bffi_type}")

                # LKD to BF mapping
                bffi_map_bf = row["LKD-BF-owl-mapping"]
                if bffi_map_bf not in ["owl:equivalentClass", "owl:equivalentProperty", "bffi-meta:exactMatch", "bffi-meta:closeMatch", "bffi-meta:broadMatch"]:
                    if not bffi_map_bf in EMPTY_COL_VALS:
                        raise ValueError(f"Mapping property from {bffi_id} to BIBFRAME had an unexpected value, got: {bffi_map_bf}")
                    else:
                        # missing values may pass
                        pass
                else:
                    if not (bibframeURI:=row["bibframeURI"]) in EMPTY_COL_VALS:
                        self.graph.add((bffi_id, self.from_n3(bffi_map_bf), URIRef(bibframeURI)))

                # LKD to RDA mapping
                bffi_map_rda = row["LKD-RDA-mapping"]
                if bffi_map_rda not in ["bffi-meta:broadMatch", "bffi-meta:closeMatch", "bffi-meta:exactMatch", "bffi-meta:narrowMatch", "rdfs:seeAlso", "bffi-meta:relatedValueVocabulary"]:
                    if not bffi_map_rda in EMPTY_COL_VALS:
                        raise ValueError(f"Mapping property from {bffi_id} to RDA had an unexpected value, got: {bffi_map_rda}")
                    else:
                        # missing values may pass
                        pass
                elif row["rdaURI"] in EMPTY_COL_VALS:
                    # missing values may pass
                    pass
                else:
                    for item in [_.strip() for _ in row["rdaURI"].split("|")]:
                        long_iri = self.graph.namespace_manager.expand_curie(item) if not item.startswith("http") else item
                        self.graph.add((bffi_id, self.from_n3(bffi_map_rda), URIRef(long_iri)))
                        # test that classes match with RDA classes and vice versa for properties
                        if not (rdaURI_isClass:=long_iri.startswith("http://rdaregistry.info/Elements/c/") and bffi_id_isClass):
                            # let termList values pass for now
                            if "/termList/" not in long_iri:
                                ValueError(f"{bffi_id} is a class but has RDA relationship to something other than to a RDA class!")
                        elif rdaURI_isClass and not bffi_id_isClass:
                            ValueError(f"{bffi_id} is not a class but has RDA relationship to a RDA class!")

                # subclasses
                bffi_subclass = row["bffi: rdfs:subClassOf"]
                for item in [_.strip() for _ in bffi_subclass.split(",") if bffi_subclass]:
                    self.graph.add((bffi_id, RDFS.subClassOf, self.from_n3(item)))

                # subproperties
                bffi_subproperty = row["bffi: rdfs:subPropertyOf"]
                for item in [_.strip() for _ in bffi_subproperty.split(",") if bffi_subproperty]:
                    self.graph.add((bffi_id, RDFS.subPropertyOf, self.from_n3(item)))

                #inverse of
                bffi_inverse_of = row["bffi: owl:inverseOf"]
                if bffi_inverse_of:
                    self.graph.add((bffi_id, OWL.inverseOf, self.from_n3(bffi_inverse_of)))
                    self.graph.add((self.from_n3(bffi_inverse_of), OWL.inverseOf, bffi_id))

                bffi_disjoint_with = row["bffi: owl:disjointWith"]
                if bffi_disjoint_with:
                    self.graph.add((bffi_id, OWL.disjointWith, self.from_n3(bffi_disjoint_with)))
                    self.graph.add((self.from_n3(bffi_disjoint_with), OWL.disjointWith, bffi_id))

                if row["lkd status"] == "deprecated":
                    if (bffi_id, RDF.type, OWL.Class) in self.graph:
                        self.graph.remove((bffi_id, RDF.type, None))
                        self.graph.add((bffi_id, RDF.type, OWL.DeprecatedClass))
                    else:
                        self.graph.remove((bffi_id, RDF.type, None))
                        self.graph.add((bffi_id, RDF.type, OWL.DeprecatedProperty))

                    for pred, obj in self.graph.predicate_objects(subject=bffi_id):
                        if pred not in [RDFS.label, DCTERMS.modified, RDF.type]:
                            self.graph.remove((bffi_id, pred, None))

                    self.graph.add((bffi_id, OWL.deprecated, Literal(True)))
                    bffi_replacedBy = row["replacedBy"]
                    for item in [_.strip() for _ in bffi_replacedBy.split(",") if bffi_replacedBy]:
                        self.graph.add((bffi_id, DCTERMS.isReplacedBy, self.from_n3(item)))

                # update the previous row variable for the next iteration
                prevRow = row

    def serialize(self):
        """
        Serializes the complete data model graph as TTL.
        """
        self.graph.serialize(format="ttl", destination=self.output_path)

if __name__ == "__main__":
    DataModelConverter()
