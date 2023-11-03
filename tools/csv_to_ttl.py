#!/usr/bin/env python3
"""
 Copyright 2023 University Of Helsinki (The National Library Of Finland)

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

import rdflib # separate import for triggering autocomplete behavior in IDE
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, XSD, NamespaceManager
from rdflib.util import from_n3

# treat these CSV cell values as empty/missing
EMPTY_COL_VALS = set(["", "#N/A", "N/A", "?"])

class DataModelConverter:
    def __init__(self):
        parser = argparse.ArgumentParser(description="CSV to TTL converter to be used in LKD data model conversion")
        parser.add_argument("-i", "--input-path",
            help="Input path for LKD csv file", required=True)
        parser.add_argument("-o", "--output-path",
            help="Output path for data model", required=True)
        parser.add_argument("-p", "--prefixes-path",
            help="Input path for prefixes file to be used in processing the csv file", required=True)
        parser.add_argument("-ns", "--namespace",
            help="Namespace for lkd prefix in output file. If given, overrides any other value")
        parser.add_argument("-url", "--publishing-url",
            help="Base URL for published data model", default="http://schema.finto.fi/lkd/")
        parser.add_argument("-m", "--metadata-path",
            help="Input path for separate data model metadata file")
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
        self.prefixes_path = args.prefixes_path
        self.namespace = args.namespace
        self.publishing_url = args.publishing_url
        self.metadata_path = args.metadata_path
        self.releases_path = args.releases_path
        self.write_rdfxml = args.write_rdfxml
        self.version = args.version
        self.prior_version = args.prior_version

        self.graph = Graph(bind_namespaces='none').parse(self.prefixes_path)

        if self.namespace:
            self.graph.bind('lkd', self.namespace)

        # identifier for the LKD ontology
        lkdURIRef = URIRef(self.graph.namespace_manager.expand_curie('lkd:'))

        if self.metadata_path:
            self.graph.parse(self.metadata_path, format="ttl", publicID=lkdURIRef)

        self.nsm = NamespaceManager(self.graph, 'none')

        if self.releases_path and self.version:
            with open(self.releases_path, "r", encoding="utf-8", newline="") as releases_file:
                csvreader = csv.DictReader(releases_file, delimiter=",")
                for row in csvreader:
                    if row['owl:versionInfo'] == self.version:
                        to_be_removed = []
                        for literal in self.graph.objects(lkdURIRef, DCTERMS.description):
                            if (desc_end := row['dct:description-' + (lang:=literal.language)]):
                                self.graph.add(
                                    (lkdURIRef, DCTERMS.description, Literal(' '.join([literal, desc_end]), lang ))
                                )
                                to_be_removed.append((lkdURIRef, DCTERMS.description, literal))
                        for triple in to_be_removed:
                            self.graph.remove(triple)
                        break

        curdate = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        if (lkdURIRef, DCTERMS.issued, None) not in self.graph and self.version:
            self.graph.add((lkdURIRef, DCTERMS.issued, Literal(curdate[:10], datatype=XSD.date)))

        if self.version:
            versionIRI = self.publishing_url + self.version.replace(".", "-") + "/"
            self.graph.remove((lkdURIRef, OWL.versionIRI, None))
            self.graph.add((lkdURIRef, OWL.versionIRI, URIRef(versionIRI)))

            self.graph.remove((lkdURIRef, OWL.versionInfo, None))
            self.graph.add((lkdURIRef, OWL.versionInfo, Literal(self.version)))

        if self.prior_version:
            prior_version = self.publishing_url + self.prior_version.replace(".", "-") + "/"
            self.graph.remove((lkdURIRef, OWL.priorVersion, None))
            self.graph.add((lkdURIRef, OWL.priorVersion, URIRef(prior_version)))

        # always update modified date
        self.graph.remove((lkdURIRef, DCTERMS.modified, None))
        self.graph.add((lkdURIRef, DCTERMS.modified, Literal(curdate, datatype=XSD.dateTime)))

        self.convertCSV()
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

    def convertCSV(self):
        """
        Converts the CSV document and adds resulting triples to the conversion-specific graph.
        """
        LKD = rdflib.Namespace(self.nsm.expand_curie('lkd:'))
        with open(self.input_path, "r", encoding="utf-8", newline="") as csvfile:
            csvreader = csv.DictReader(csvfile, delimiter=",")

            # initialize previous row variable
            prevRow = dict((x, "") for x in csvreader.fieldnames)

            for row in csvreader:
                # strip all column values before use and map special values to empty strings
                row = dict((x, _) if (_ := y.strip()) not in EMPTY_COL_VALS else (x, "") for (x, y) in row.items())

                # drop unwanted rows
                if row["skos:historyNote"] == "lkd-v0.1: not included":
                    continue
                if row["lkd status"] not in ["published", "planned"]:
                    continue

                id = row["lkd-id"]

                if not id.startswith("lkd:"):
                    raise ValueError("LKD-id is not within the lkd: namespace: " + id)
                lkd_id = LKD[id[4:]]

                # labels
                self.graph.add((lkd_id, RDFS.label, Literal(row["lkd rdfs:label-en"], "en")))
                self.graph.add((lkd_id, RDFS.label, Literal(row["lkd rdfs:label-fi"], "fi")))
                #self.graph.add((lkd_id, RDFS.label, Literal(row["lkd rdfs:label-sv"], "sv")))

                # domain
                domainCol = "lkd rdfs:domain"
                if (lkd_domain := row[domainCol]) and (id != prevRow["lkd-id"] or lkd_domain != prevRow[domainCol]):
                    self.processComplexCol(lkd_id, RDFS.domain, lkd_domain)

                # range
                rangeCol = "lkd rdfs:range"
                if (lkd_range := row[rangeCol]) and (id != prevRow["lkd-id"] or lkd_range != prevRow[rangeCol]):
                    self.processComplexCol(lkd_id, RDFS.range, lkd_range)

                # type
                lkd_type = row["lkd: rdf:type"]
                if (lkd_id_isClass:=lkd_type == "owl:Class"):
                    self.graph.add((lkd_id, RDF.type, OWL.Class))
                elif lkd_type in ["owl:ObjectProperty", "owl:SymmetricProperty"]:
                    self.graph.add((lkd_id, RDF.type, OWL[lkd_type[4:]]))
                    self.graph.add((lkd_id, RDF.type, OWL.ObjectProperty))
                    if (lkd_id, RDFS.range, None) not in self.graph:
                        # set rdfs:range to rdfs:Resource in case no range specified (handled previously)
                        self.graph.add((lkd_id, RDFS.range, RDFS.Resource))
                elif lkd_type == "owl:DatatypeProperty":
                    self.graph.add((lkd_id, RDF.type, OWL.DatatypeProperty))
                    empty = True  # helper variable for checking out if rdfs:range is empty
                    for range in self.graph.objects(lkd_id, RDFS.range):
                        empty = False
                        if range != RDFS.Literal:
                            raise ValueError(f"Property {lkd_id} has rdfs:range of {lkd_range} (expected rdfs:Literal due to rdf:type owl:DatatypeProperty)")
                    if empty:
                        # set rdfs:range to rdfs:Literal in case no range specified (handled previously)
                        self.graph.add((lkd_id, RDFS.range, RDFS.Literal))
                else:
                    raise ValueError(f"{lkd_id} had an unexpected type value, got {lkd_type}")

                # LKD to BF mapping
                lkd_map_bf = row["LKD-BF-owl-mapping"]
                if lkd_map_bf not in ["owl:equivalentClass", "owl:equivalentProperty", "rdfs:subClassOf", "rdfs:subPropertyOf", "rdfs:seeAlso"]:
                    if not lkd_map_bf in EMPTY_COL_VALS:
                        raise ValueError(f"Mapping property from {lkd_id} to BIBFRAME had an unexpected value, got: {lkd_map_bf}")
                    else:
                        # missing values may pass
                        pass
                else:
                    self.graph.add((lkd_id, self.from_n3(lkd_map_bf), URIRef(row["bibframeURI"])))

                # LKD to RDA mapping
                lkd_map_rda = row["LKD-RDA-owl-mapping"]
                if lkd_map_rda not in ["lkd:broadMatch", "lkd:closeMatch", "lkd:exactMatch", "lkd:narrowMatch", "rdfs:seeAlso"]:
                    if not lkd_map_rda in EMPTY_COL_VALS:
                        raise ValueError(f"Mapping property from {lkd_id} to RDA had an unexpected value, got: {lkd_map_rda}")
                    else:
                        # missing values may pass
                        pass
                elif row["rdaURI"] in EMPTY_COL_VALS:
                    # missing values may pass
                    pass
                else:
                    for item in [_.strip() for _ in row["rdaURI"].split("|")]:
                        long_iri = self.graph.namespace_manager.expand_curie(item) if not item.startswith("http") else item
                        self.graph.add((lkd_id, self.from_n3(lkd_map_rda), URIRef(long_iri)))
                        # test that classes match with RDA classes and vice versa for properties
                        if not (rdaURI_isClass:=long_iri.startswith("http://rdaregistry.info/Elements/c/") and lkd_id_isClass):
                            # let termList values pass for now
                            if "/termList/" not in long_iri:
                                ValueError(f"{lkd_id} is a class but has RDA relationship to something other than to a RDA class!")
                        elif rdaURI_isClass and not lkd_id_isClass:
                            ValueError(f"{lkd_id} is not a class but has RDA relationship to a RDA class!")

                # subclasses
                lkd_subclass = row["lkd: rdfs:subClassOf"]
                for item in [_.strip() for _ in lkd_subclass.split(",") if lkd_subclass]:
                    self.graph.add((lkd_id, RDFS.subClassOf, self.from_n3(item)))

                # subproperties
                lkd_subproperty = row["lkd: rdfs:subPropertyOf"]
                for item in [_.strip() for _ in lkd_subproperty.split(",") if lkd_subproperty]:
                    self.graph.add((lkd_id, RDFS.subPropertyOf, self.from_n3(item)))

                #inverse of
                lkd_inverse_of = row["lkd: owl:inverseOf"]
                if lkd_inverse_of:
                    self.graph.add((lkd_id, OWL.inverseOf, self.from_n3(lkd_inverse_of)))
                    self.graph.add((self.from_n3(lkd_inverse_of), OWL.inverseOf, lkd_id))

                lkd_disjoint_with = row["lkd: owl:disjointWith"]
                if lkd_disjoint_with:
                    self.graph.add((lkd_id, OWL.disjointWith, self.from_n3(lkd_disjoint_with)))
                    self.graph.add((self.from_n3(lkd_disjoint_with), OWL.disjointWith, lkd_id))

                # update the previous row variable for the next iteration
                prevRow = row

    def serialize(self):
        """
        Serializes the complete data model graph as TTL.
        """
        self.graph.serialize(format="ttl", destination=self.output_path)

if __name__ == "__main__":
    DataModelConverter()
