# Linkitetty kirjastodata (LKD)
Linked library data project (LKD)

Project coordinated by Kansalliskirjasto - The National Library of Finland

Project homepage https://www.kiwi.fi/display/LKD

Project ID http://www.wikidata.org/entity/Q124635303

## About the LKD data model

This BIBFRAME data model is based on the BIBFRAME 2.4.0 data model published by the Library of Congress. The model has been supplemented with categories and properties from RDA Registry, as well as additions based on the Finnish description guidelines. A notable difference to the Library of Congress BIBFRAME data model is that LKD data model splits bf:Work into disjoint classes bffi:Work and bffi:Expression corresponding to the structure of RDA classes.

Namespece of the model <http://urn.fi/URN:NBN:fi:schema:bffi:>   Preferred prefix "bffi".

## Versions
Test version 0.1.0, published on 2023-01-26, comprises of the RDA elements determined by the Finnish cataloguing levels. The identifiers used are temporary and the model is not ready for use.

Test version 0.2.0, published on 2023-05-26, comprises of the RDA elements determined by the Finnish cataloguing levels. The identifiers used are temporary and the model is not ready for use. Compared to the 0.1 versions of the data model, this one contains a new approach to titles as well as a number of minor corrections. We have changed the mapping properties we are not entirely satisfied with this approach, either. The translations of the various terms have been updated but the work on these is still partly incomplete.

Test version 0.3.0, published on 2023-11-03, comprises of the RDA elements determined by the Finnish cataloguing levels. The identifiers used are temporary and the model is not ready for use. Compared to the 0.2 versions of the data model, this one contains a new set of linking properties used for linking to RDA as well as corrections to said links, a more coherent approach to titles, and a host of minor corrections. We temporarily left Swedish labels out of this version as we intend to check and correct them systematically and introduce them back into a future version.

Test version 0.3.1, published on 2024-01-12, includes subclasses of lkd:Work and lkd:Expression which have close matches to the subclasses of BIBFRAME Work. For handling various Title types we have added the lkd:TitleNote class and the lkd:titleNote property.

In test version 0.4.0, published on 2024-02-23, we have moved from temporary identifiers to permanent URN identifiers. In addition, a new prefix bffi: has been introduced. The version also completes the division of bf:Work and its subclasses into bffi:Work and bffi:Expression and their subclasses. The allocation of properties used with bf:Work is still in progress. This version also includes a new bffi-meta:relatedValueVocabulary property used to denote a concept group in a value vocabulary that contains instances of a given class.

In test version 0.5.0, published on 2024-04-16, we have added properties related to cartographic information and collections dividing them between subclasses of bffi:Work and bffi:Expression according to the RDA description rules. We have added more mappings to the value vocabularies in the Metadata Thesaurus using the bffi-meta:relatedValueVocabulary -annotation. In this version mappings to the BIBFRAME data model have been re-specified and an effort has been made to mark a relationship for all resources. If the relationship is not equivalent, the relationship annotations of the bffi-meta: ontology have been used. Change notes have been added to document changes between versions and deprecated resources are displayed at the bottom of the page.

In test version 0.6.0, published on 2024-06-19, we added the classes and properties related to administrative metadata, classes and properties related to classifications, and some other properties (bffi:credits, bffi:dimension, bffi:layout). To enable recording the title source we introduced a class and property. For conversions, we added the bffi:marcKey property to store the original MARC field information.

## Conversion
In addtion to the data model this project aims to create MARC21 to BFFI conversion rules and conversion software to implement them. Backward conversion from BFFI to MARC21 will be implemented, too.
