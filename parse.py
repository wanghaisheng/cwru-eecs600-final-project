#!/usr/bin/env python
import json
import sys
import re
from nltk import *
from nltk.tag.sequential import RegexpTagger,SequentialBackoffTagger
#from nltk.parse.chart import ChartParser
from nltk.chunk.regexp import *
from datetime import timedelta

class MedicineTagger(SequentialBackoffTagger):
    """
    Load a list of medicines in, so they can be tagged as DRUGs
    """
    def __init__(self, list_of_drugs, backoff=None):
        SequentialBackoffTagger.__init__(self, backoff)
        drug_list = [ x.strip() for x in open(list_of_drugs, 'r')]
        self.drugs = {}
        # HashTable it for O(1) lookup
        for drug in drug_list:
            self.drugs[drug] = 1

    def choose_tag(self, tokens, index, history=None):
        if tokens[index].lower() in self.drugs:
            return "DRUG"
        else:
            return None
        
tokens = [
    # Tokens for finding prescriptions
    # VBB = "Verb for Begin" (or anything that indicates that patient was not taking the medicine.)
    ('^[0-9]+$', 'NUM'),
    ('^(mg|ml|meg)$', 'UNITS'),
    ('^[0-9\.]+(mg|meq|ml)$', 'DOSAGE'),
    ('^([Ss]tart|[Bb]egin|[Ii]ncrease)$','VBB'),
    # Tokens for finding frequency
    #FLB = "Frequency Label"
    #FRB = "Frequency Adverb"
    ('^([fF]requency)$', 'FLB'),
    ('^([Dd]aily|[Ww]eekly|[Mm]onthly|[Rr]arely|[Oo]ccasionally)$', 'FRB'),   
    ('^([Oo]nce|[Tt]wice)$', 'FRB'),
    ('^([Ee]very)$', 'FRB'),
    ('^(QHS|TID|BID|b\.i\.d(\.)?)$', 'FRB'),
    # Tokens for finding durations
    # PER = "Time Period"
    ('^([Ss]econd(s)?|[Mm]inute(s)?|[Hh]our(s)?)$', 'PER'),
    ('^([Dd]ay(s)?|[Ww]eek(s)?)$', 'PER'),
    # Tokens for finding semiology
    # SEMLB = "Semiology Label"
    # SEMEV = "Semiology Event"
    # BODP = "Body Part"
    ('^([Ss]emiology)$','SEMLB'),
    ('^([Rr]ight|[Ll]eft)$','JJ'),
    ('^([Ee]pisode(s)?)|([Ss]pasm(s)?)$','SEMEV'),
    ('^([Ff]ace|[Aa]rm|[Ll]eg|[Mm]otor)$','BODP'),
    # Tokens for finding comorbidity
    # COMLB = "Comorbidity Label"
    # HEADER: necessary to end previous section
    ('^(([Cc]omorbidit(y|ies))|[Cc]ondition(s)?)$','COMLB'),
    ('^Types/Evolution/Frequency/Age$','HEADER'),
    # EPZLB = "Epileptogenic Zone Label"
    ('^Epileptogenic$','EPZLB')
]

parse_rules = r"""
    # Rules for finding frequency & duration
    FRBP:      {<FRB><IN><JJ>}                      # "Daily while hospitalized"
    FRBP:      {<IN><DT>?<PER>}                      # "in a day", "in the day", "per day", "a day"
    FREQUENCY:      {<FRB><PER>}                        # "every day"
    FREQUENCY: {<CD><TO><CD><FRBP>}                 # "two to three in a day"
               {<NUM><.><NUM><FRBP>}                # "20-30 per day"
    FREQUENCY:      {<FRB><DT><PER>}                      # "twice a day"

    # Rules for finding prescriptions
    DOSAGE: {<NUM><UNITS>}                                #Chunk the dosages of medicines together.
    PRESCRIPTION: {<NNP|VBG|DRUG>+<DOSAGE><FRB>?}                   #Chunk the medicine with the quantity.
                  {<DOSAGE><IN>(<NNP>|<NNPS|DRUG>)+<FRB|FRBP>?}      # "250 mg of Topamax ER daily"
                  {<DOSAGE><IN>(<NNP>|<NNPS|DRUG>)+<FREQUENCY>?}     # "250 mg of Topamax ER daily"
    REGIMEN:      {<DOSAGE><FREQUENCY>}                         # 50mg daily
                  {<PRESCRIPTION><FREQUENCY>}                   # 50mg Coumadin daily
                  {<VBZ><IN><NNP|DRUG>}                              # "is on [drug]"
    PRESCRIPTION: {<NN>*<REGIMEN>}                              # sodium citrade solution 50ml
    FREGIMEN:     {<TO>?<VBB|VB><TO|IN>?<REGIMEN>}              # "to begin [regimen]"
    REGIMENLIST:  {(<REGIMEN|DRUG><,>)+<REGIMEN|DRUG>}
    PRESCRIPTIONLIST: {(<PRESCRIPTION><,>)+<PRESCRIPTION>}

    # Rules for finding semiology
    BODPP:      {<JJ>?<BODP>}
    BODPLIST:   {((<BODPP>(<,>|<CC>)?)+<BODPP>)}
    SEMITEM:    {(<BODPLIST>|<JJ>+|<NNP>)<SEMEV>}
    SEMIOLOGY:  {<NN>?<SEMLB>(<:>((<NUM><:>)?<SEMITEM>)+)}

    # Rules for finding comorbidity
    FULLHEADER: {<NNP><HEADER>}
    COMORBIDITY:    (<NNP>+|<JJ>)<COMLB><:>{(<..?.?.?>+<,>?)+}

    # Rules for finding Epileptogenic Zone
    EPILEPTOGENIC: <EPZLB><NNP><:>{<.*>+?}(<.*><:>|<SEMIOLOGY>|(<NNP>+|<JJ>)<COMLB><:>)
"""
def frequency_text(tuple_list):
    """
    Pass in a list like
    [((u'Daily', 'FRB'), 'FRBP'), ((u'while', 'IN'), 'FRBP'), ((u'hospitalized', 'JJ'), 'FRBP')]
    or
    [((u'Topamax', 'DRUG'), 'PRESCRIPTION'), ((u'100mg', 'DOSAGE'), 'PRESCRIPTION'), ((u'BID', 'FRB'), 'FREQUENCY')]
    from a prescription.
    """
    all_chains = [[]]
    for i in tuple_list:
        if i[1] == "FREQUENCY":
            all_chains[-1].append(i[0][0])
        else:
            if len(all_chains[-1]) > 0:
                all_chains.append([])
    return [ " ".join(x) for x in all_chains ]

def anything_useful(section_name, item):
    """
    Pass in to this method the section name and a tree or tuple generated by a sentence
    in that section and this method will spit out something useful if it exists.

    This method exists because certain sections have useful things, like the
    "CLASSIFICATION OF PAROXYSMAL EPISODES" section only has one frequency.
    """
    if (re.search("CLASSIFICATION", section_name) != None):
        # Then this is the section which contains the seizure frequency
        if isinstance(item, nltk.tree.Tree):
            if item.node == "FREQUENCY" or item.node == "FRBP":
                print "Seizure Frequency: " + flatten_regimen(item)
            elif item.node == "PRESCRIPTION":
                print "Medication: " + flatten_regimen(item)
            elif item.node == "PRESCRIPTIONLIST":
                for s in item.subtrees():
                    if s.node == "PRESCRIPTION":
                        print "Medication: " + flatten_regimen(s)
            elif item.node == "REGIMEN":
                print "Medication: " + flatten_regimen(item)
            elif item.node == "SEMIOLOGY":
                for s in item.subtrees():
                    if s.node == "SEMITEM":
                        print "Epileptic Semiology: " + flatten_regimen(s)
            elif item.node == "COMORBIDITY":
                coms = flatten_regimen(item).split(",")
                for s in coms:
                    print "Comorbidity: " + s.strip()
            elif item.node == "EPILEPTOGENIC":
                print "Epileptogenic Zone: " + flatten_regimen(item)
            #f = frequency_text(item.pos())
            #if f != None:
            #    print "Seizure History: %s" % (" ".join(f))
    if (re.search("HISTORY", section_name) != None):
        # Then this is the section which contains prior medications.
        if isinstance(item, nltk.tree.Tree):
            if item.node == "REGIMEN":
                print "Medication: " + flatten_regimen(item)
            elif item.node == "PRESCRIPTION":
                print "Medication: " + flatten_regimen(item)
            elif item.node == "PRESCRIPTIONLIST":
                for s in item.subtrees():
                    if s.node == "PRESCRIPTION":
                        print "Medication: " + flatten_regimen(s)

def flatten_regimen(r):
    return " ".join([i[0][0] for i in r.pos()])
    
def parse_sections(sections):
    for section_name, lines in sections.iteritems():
        backup_tagger = nltk.data.load('taggers/maxent_treebank_pos_tagger/english.pickle')
        medicines = MedicineTagger("drugs.txt", backup_tagger)
        tagger = RegexpTagger(tokens,medicines)

        sents = sent_tokenize(" ".join(lines))
        sents = [ tagger.tag(nltk.word_tokenize(s)) for s in sents ]
        #prev = []
        #w = word_tokenize(s)
        #for i in range(0,len(w)):
        #    prev.append(tagger.choose_tag(w, i, prev))
        #print ",".join([j or "" for j in prev])

        p = nltk.RegexpParser(parse_rules)
        for i in range(0,len(sents)):
            #print sents[i]
            result = p.parse(sents[i])
            if (len(sys.argv) > 2 and sys.argv[2] == 'debug'):
                print result
            for child in result:
                # The only trees will be the ones we created.
                #if isinstance(child, nltk.tree.Tree):
                anything_useful(section_name, child)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.argv.append("P007.clean.json")
    f = open(sys.argv[1], 'r')
    json_data = json.load(f)
    parse_sections(json_data)
