## BFFI Changelog

### BFFI v. 1.1.0

Link: <https://schema.finto.fi/bffi/1-1-0/>

* New Classes
  * bffi:DramaticRole
  * bffi:EnsembleSize
  * bffi:GroovePitch
  * bffi:GrooveWidth
  * bffi:KeyMode
  * bffi:MediumComponent
  * bffi:MediumComponentQualifier
  * bffi:MediumOfPerformance
  * bffi:Mode
  * bffi:ReferenceSource
  * bffi:Tempo

* New Properties
  * bffi:dramaticRole
  * bffi:ensembleSize
  * bffi:groupAap
  * bffi:keyMode
  * bffi:keyModeOfRepresentativeExpression
  * bffi:mediumComponent
  * bffi:mediumComponentQualifier
  * bffi:mediumOfPerformance
  * bffi:mode
  * bffi:modeOfIssuance
  * bffi:numberOfHands
  * bffi:phonogramDate
  * bffi:referenceSource
  * bffi:tempo
  * bffi:usesMediumOfPerformance

* Deprecated Classes and properties
  * bffi:GrooveCutting:	Replaced by bffi:GroovePitch and bffi:GrooveWidth as subclasses of bffi:GrooveCharacteristic
  * bffi:issuance: Replaced by bffi:extensionPlan and bffi:modeOfIssuance
  * bffi:TitleSource: Replaced by bffi:RecordingSource	

* Changes to existing Classes and properties
  * bffi:Content: Added related value vocabulary
  * bffi:content: Removed related value vocabulary
  * bffi:contribution: Changed the Finnish and English labels
  * bffi:dateOfRepresentativeExpression: Changed the superproperty to bffi:date
  * bffi:IntendedAudience: Added scope notes in Finnish and English
  * bffi:partName: Changed the Finnish label
  * bffi:partNumber: Changed RDA mapping to close match and changed the Finnish label
  * bffi:responsibilityStatement: Corrected the RDA mapping	Corrected the RDA mapping from "has statement of responsibility relating to title proper" to "has statement of responsibility".
  * bffi:SeriesExpression: Corrected a typo in the Finnish label
  * bffi:SeriesWork: Changed the value of superclass to bffi:MonographWork	
  * bffi:subject: Corrected the RDA mapping to cover all the subject properties in RDA
  * bffi:summary: Added RDA mapping
  * bffi:Temporal: Added related value vocabulary
  * bffi:timePeriodOfCreation: Added definitions in Finnish and English
  * bffi:validDate: Removed mapping to RDA as there is no suitable RDA element

### BFFI v. 1.0.0

Initial Release

Link: <https://schema.finto.fi/bffi/1-0-0/>
bffi:validDate	1.1.0	Removed mapping to RDA as there is no suitable RDA element	
bffi:dramaticRole	1.1.0		Added new property bffi:dramaticRole
bffi:DramaticRole	1.1.0		Added new class bffi:DramaticRole
