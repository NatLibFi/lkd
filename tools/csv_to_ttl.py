#!/usr/bin/env python3

import argparse
import csv
import datetime

import rdflib  # separate import for triggering autocomplete behavior in IDE
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, XSD, NamespaceManager
from rdflib.util import from_n3

# extra prefixes (besides the ones defined in metadata file) to be used in conversion
PREFIXES_DATA = """
@prefix bf: <http://id.loc.gov/ontologies/bibframe/> .
@prefix bflc: <http://id.loc.gov/ontologies/bflc/> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mts: <http://urn.fi/URN:NBN:fi:au:mts:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdaa: <http://rdaregistry.info/Elements/a/> .
@prefix rdaad: <http://rdaregistry.info/Elements/a/datatype/> .
@prefix rdaao: <http://rdaregistry.info/Elements/a/object/> .
@prefix rdac: <http://rdaregistry.info/Elements/c/> .
@prefix rdaco: <http://rdaregistry.info/termList/RDAContentType/> .
@prefix rdaed: <http://rdaregistry.info/Elements/e/datatype/> .
@prefix rdaeo: <http://rdaregistry.info/Elements/e/object/> .
@prefix rdafnv: <http://rdaregistry.info/termList/noteForm/> .
@prefix rdafmn: <http://rdaregistry.info/termList/MusNotation/> .
@prefix rdae: <http://rdaregistry.info/Elements/e/> .
@prefix rdai: <http://rdaregistry.info/Elements/i/> .
@prefix rdam: <http://rdaregistry.info/Elements/m/> .
@prefix rdamt: <http://rdaregistry.info/termList/RDAMediaType/> .
@prefix rdan: <http://rdaregistry.info/Elements/n/> .
@prefix rdand: <http://rdaregistry.info/Elements/n/datatype/> .
@prefix rdano: <http://rdaregistry.info/Elements/n/object/> .
@prefix rdap: <http://rdaregistry.info/Elements/p/> .
@prefix rdapd: <http://rdaregistry.info/Elements/p/datatype/> .
@prefix rdapo: <http://rdaregistry.info/Elements/p/object/> .
@prefix rdat: <http://rdaregistry.info/Elements/t/> .
@prefix rdatd: <http://rdaregistry.info/Elements/t/datatype/> .
@prefix rdau: <http://rdaregistry.info/Elements/u/> .
@prefix rdaw: <http://rdaregistry.info/Elements/w/> .
@prefix rdawd: <http://rdaregistry.info/Elements/w/datatype/> .
@prefix rdawo: <http://rdaregistry.info/Elements/w/object/> .
@prefix rdax: <http://rdaregistry.info/Elements/x/> .
@prefix rdaxd: <http://rdaregistry.info/Elements/x/datatype/> .
@prefix rdaxo: <http://rdaregistry.info/Elements/x/object/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""

# treat these CSV cell values as empty/missing
EMPTY_COL_VALS = set(["", "#N/A"])


class DataModelConverter:
    def __init__(self):
        parser = argparse.ArgumentParser(description="CSV to TTL converter to be used in LKD data model conversion")
        parser.add_argument("-i", "--input-path",
            help="Input path for LKD csv file", required=True)
        parser.add_argument("-o", "--output-path",
            help="Output path for data model", required=True)
        parser.add_argument("-ns", "--namespace",
            help="Namespace for lkd prefix in output file", default="http://example.org/lkd/")
        parser.add_argument("-url", "--publishing-url",
            help="Base URL for published data model", default="http://schema.finto.fi/lkd/")
        parser.add_argument("-m", "--metadata-path",
            help="Input path for separate data model metadata file")
        parser.add_argument("-v", "--version",
            help="Explicit version number (in x.y.z format)")
        parser.add_argument("-pv", "--prior-version",
            help="Explicit prior version number (in x.y.z format)")
        args = parser.parse_args()
        self.input_path = args.input_path
        self.output_path = args.output_path
        self.namespace = args.namespace
        self.publishing_url = args.publishing_url
        self.metadata_path = args.metadata_path
        self.version = args.version
        self.prior_version = args.prior_version

        if self.metadata_path:
            self.graph = rdflib.Graph().parse(self.metadata_path, format="ttl")
        else:
            self.graph = rdflib.Graph()

        self.graph.parse(data=PREFIXES_DATA)
        self.graph.bind("lkd", self.namespace)

        self.nsm = NamespaceManager(self.graph)

        # identifier for the LKD ontology
        lkdURIRef = URIRef(self.namespace)

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
        LKD = rdflib.Namespace(self.namespace)
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

                id = row["lkd-id"]

                if not id.startswith("lkd:"):
                    raise ValueError("LKD-id is not within the lkd: namespace: " + id)
                lkd_id = LKD[id[4:]]

                # labels
                self.graph.add((lkd_id, RDFS.label, Literal(row["lkd rdfs:label-fi"], "fi")))
                self.graph.add((lkd_id, RDFS.label, Literal(row["lkd rdfs:label-sv"], "sv")))

                # LKD to BF mapping
                lkd_map_bf = row["mapping LKD to BF"]
                if lkd_map_bf not in ["skos:exactMatch", "skos:closeMatch", "skos:broadMatch", "skos:narrowMatch"]:
                    raise ValueError(f"Mapping property from {lkd_id} to BIBFRAME had an unexpected value, got: {lkd_map_bf}")
                self.graph.add((lkd_id, self.from_n3(lkd_map_bf), URIRef(row["bibframe-id"])))

                # LKD to RDA mapping
                lkd_map_rda = row["mapping LKD to RDA"]
                if lkd_map_rda not in ["skos:exactMatch", "skos:closeMatch", "skos:broadMatch", "skos:narrowMatch"]:
                    if not lkd_map_rda in EMPTY_COL_VALS:
                        raise ValueError(f"Mapping property from {lkd_id} to RDA had an unexpected value, got: {lkd_map_bf}")
                    else:
                        # missing values may pass
                        pass
                else:
                    self.graph.add((lkd_id, self.from_n3(lkd_map_rda), URIRef(row["RDA-id"])))

                # domain
                domainCol = "lkd rdfs:domain"
                if (lkd_domain := row[domainCol]) and (id != prevRow["lkd-id"] or lkd_domain != prevRow[domainCol]):
                    self.processComplexCol(lkd_id, RDFS.domain, lkd_domain)

                # range
                rangeCol = "lkd rdfs:range"
                if (lkd_range := row[rangeCol]) and (id != prevRow["lkd-id"] or lkd_range != prevRow[rangeCol]):
                    self.processComplexCol(lkd_id, RDFS.range, lkd_range)

                # type
                lkd_type = row["rdf:type"]
                if lkd_type == "owl:Class":
                    self.graph.add((lkd_id, RDF.type, OWL.Class))
                elif lkd_type == "owl:ObjectProperty":
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

                # subclasses
                lkd_subclass = row["rdfs:subClassOf"]
                for item in [_.strip() for _ in lkd_subclass.split(",") if lkd_subclass]:
                    self.graph.add((lkd_id, RDFS.subClassOf, self.from_n3(item)))

                # subproperties
                lkd_subproperty = row["rdfs:subPropertyOf"]
                for item in [_.strip() for _ in lkd_subproperty.split(",") if lkd_subproperty]:
                    self.graph.add((lkd_id, RDFS.subPropertyOf, self.from_n3(item)))

                # update the previous row variable for the next iteration
                prevRow = row

    def serialize(self):
        """
        Serializes the complete data model graph as TTL.
        """
        self.graph.serialize(format="ttl", destination=self.output_path)


if __name__ == "__main__":
    DataModelConverter()
