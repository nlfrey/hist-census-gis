#
#	Name: 		STclean.py
#	Authors: 	Chris Graziul
#
#	Input:		file_name - File name of city file, saved in Stata 13 (or below) format
#	Output:		<file_name>_autocleaned.csv - City file with addresses cleaned 
#
#	Purpose:	This is the master script for automatically cleaning addresses before
#				manually cleaning the file using Ancestry images. Large functions will
#				eventually become separate scripts that will be further refined and
#				called from this script.
#

#   To do list: 1. Identify/flag institutions
#               2. Fix blank street names (naive)

from __future__ import print_function
import urllib
import re
import os
import sys
import time
import math
import pickle
import numpy as np
import pandas as pd
import fuzzyset
from termcolor import colored, cprint
from colorama import AnsiToWin32, init
from microclean.STstandardize import *
from microclean.HNclean import *

file_path = '/home/s4-data/LatestCities' 

#Pretty output for easy reading
class color:
   PURPLE = '\033[95m'
   CYAN = '\033[96m'
   DARKCYAN = '\033[36m'
   BLUE = '\033[94m'
   GREEN = '\033[92m'
   YELLOW = '\033[93m'
   RED = '\033[91m'
   BOLD = '\033[1m'
   UNDERLINE = '\033[4m'
   END = '\033[0m'

#
# Step 1: Load data
#

def load_city(city,state,year):

    start = time.time()

    try:
        file_name = city + state
        df = pd.read_stata(file_path + '/%s/%s.dta' % (str(year),file_name), convert_categoricals=False)
    except:
        print('Error loading %s raw data' % (city))
   
    if len(df) == 0:
        print('Error loading %s raw data' % (city))  

    end = time.time()

    num_records = len(df)

    load_time = round(float(end-start)/60,1)
    cprint('Loading data for %s took %s' % (city,load_time), 'cyan', attrs=['dark'], file=AnsiToWin32(sys.stdout))

    #Save a pristine copy for debugging
    #df_save = df

    #The original variable names change from census to census

    #
    # Street
    #

    if year == 1940:
        df['street_raw'] = df['indexed_street']
    if year == 1930:
        df['street_raw'] = df['self_residence_place_streetaddre']
    if year == 1920:
        df['street_raw'] = df['indexed_street']
    if year == 1910:
        df['street_raw'] = df['Street']

    #
    # ED
    #

    if year == 1940:
#        df['ed'] = df['derived_enumdist']
        df['ed'] = df['indexed_enumeration_district']
        df['ed'] = df['ed'].str.split('-').str[1]
    if year == 1930:
        df['ed'] = df['indexed_enumeration_district']
    if year == 1920:
        df['ed'] = df['general_enumeration_district']
    if year == 1910:
        df['ed'] = df['EnumerationDistrict']

    #Strip leading zeroes from EDs
    df['ed'] = df['ed'].astype(str)
    df['ed'] = df['ed'].str.split('.').str[0]
    df['ed'] = df['ed'].str.lstrip('0')

    #
    # House number
    #

    if year == 1940:
        df['hn_raw'] = df['general_house_number']
    if year == 1930:
        df['hn_raw'] = df['general_house_number_in_cities_o']
    if year == 1920:
        df['hn_raw'] = df['general_housenumber']
    if year == 1910:
        df['hn_raw'] = df['HouseNumber']    

    df['hn'], df['hn_flag'] = zip(*df['hn_raw'].map(standardize_hn))
    df['hn'] = df['hn'].apply(make_int)  

    #
    # Image ID
    #

    if year==1940:
        df['image_id'] = df['stableurl']
    if year==1930:
        df['image_id'] = df['imageid']

    #
    # Line number
    #

    if year==1940:
        df['line_num'] = df['general_line_number']
    if year==1930:
        df['line_num'] = df['indexed_line_number'].apply(make_int)

    #
    # Dwelling number
    #

    if year==1940:
        df['dn'] = None    
    if year==1930:
        df['dn'] = df['general_dwelling_number']

    #
    # Family ID
    #
 
    if year==1940:
        df['fam_id'] = None
    if year==1930:
        df['fam_id'] = df['general_family_number']

    #
    # Block ID
    #
 
    if year==1930:
        df['block'] = df['general_block']

    #
    # Institution (name)
    #
 
    if year==1940:
        df['institution'] = df['general_institution']
    if year==1930:
        df['institution'] = df['general_institution']

    #
    # Rel ID
    #
 
    if year==1940:
        df['rel_id'] = None
    if year==1930:
        df['rel_id'] = df['general_RelID']

    #
    # Household ID
    #

    if year==1940:
        df['hhid_raw'] = df['hhid']
        df['hhid'] = df['hhid_numeric']
    if year==1930:
        df['hhid'] = df['general_HOUSEHOLD_ID']

    #
    # PID
    #    

    if year==1940:
        df['pid'] = None
    if year==1930:
        df['pid'] = df['pid']
    
    # Sort by image_id and line_num (important for HN)
    df = df.sort_values(['image_id','line_num'])
    df.index = range(0,len(df))

    return df, load_time

#
# Step 2: Preclean data
#

def preclean_street(df,city,state,year):

    start = time.time()

    #Create dictionary for (and run precleaning on) unique street names
    grouped = df.groupby(['street_raw'])
    cleaning_dict = {}
    for name,_ in grouped:
        cleaning_dict[name] = standardize_street(name)
    
    #Use dictionary create st (cleaned street), DIR (direction), NAME (street name), and TYPE (street type)
    df['street_precleaned'] = df['street_raw'].apply(lambda s: cleaning_dict[s][0])
    df['DIR'] = df['street_raw'].apply(lambda s: cleaning_dict[s][1])
    df['NAME'] = df['street_raw'].apply(lambda s: cleaning_dict[s][2])
    df['TYPE'] = df['street_raw'].apply(lambda s: cleaning_dict[s][3])

    sm_all_streets, sm_st_ed_dict_nested, sm_ed_st_dict = load_steve_morse(df,city,state,year)

    #Create dictionary {NAME:num_NAME_versions}
    num_NAME_versions = {k:len(v) for k,v in sm_st_ed_dict_nested.items()}
    #Flatten for use elsewhere
    sm_st_ed_dict = {k:v for d in [v for k,v in sm_st_ed_dict_nested.items()] for k,v in d.items()}
    #For bookkeeping when validating matches using ED 
    microdata_all_streets = np.unique(df['street_precleaned'])
    for st in microdata_all_streets:
        if st not in sm_all_streets:
            sm_st_ed_dict[st] = None

    #If no TYPE, check if NAME is unique (and so we can assume TYPE = "St")
    def replace_singleton_names_w_st(st,NAME,TYPE):
        try:
            if num_NAME_versions[NAME] == 1 & TYPE == '':
                TYPE = "St"
                st = st + " St"
            return st, TYPE    
        except:
            return st, TYPE

    df['street_precleaned'], df['DIR'] = zip(*df.apply(lambda x: replace_singleton_names_w_st(x['street_precleaned'],x['NAME'],x['TYPE']), axis=1))

    end = time.time()
    preclean_time = round(float(end-start)/60,1)

    cprint('Precleaning street names for %s took %s\n' % (city,preclean_time), 'cyan', attrs=['dark'], file=AnsiToWin32(sys.stdout))
    
    preclean_info = sm_all_streets, sm_st_ed_dict, sm_ed_st_dict, preclean_time

    return df, preclean_info

#
# Step 3: Get Steve Morse street-ed data
#

def load_steve_morse(df,city,state,year):

    #NOTE: This dictionary must be built independently of this script
    sm_st_ed_dict_file = pickle.load(open(file_path + '/%s/sm_st_ed_dict%s.pickle' % (str(year),str(year)),'rb'))
    sm_st_ed_dict_nested = sm_st_ed_dict_file[(city,'%s' % (state.lower()))]

    #Flatten dictionary
    temp = {k:v for d in [v for k,v in sm_st_ed_dict_nested.items()] for k,v in d.items()}

    #Capture all Steve Morse streets in one list
    sm_all_streets = temp.keys()

    #
    # Build a Steve Morse (sm) ED-to-Street (ed_st) dictionary (dict)
    #

    sm_ed_st_dict = {}
    #Initialize a list of street names without an ED in Steve Morse
    sm_ed_st_dict[''] = []
    for st, eds in temp.items():
        #If street name has no associated EDs (i.e. street name not found in Steve Morse) 
        #then add to dictionary entry for no ED
        if eds is None:
            sm_ed_st_dict[''].append(st)
        else:
            #For every ED associated with a street name...
            for ed in eds:
                #Initalize an empty list if ED has no list of street names yet
                sm_ed_st_dict[ed] = sm_ed_st_dict.setdefault(ed, [])
                #Add street name to the list of streets
                sm_ed_st_dict[ed].append(st)

    return sm_all_streets, sm_st_ed_dict_nested, sm_ed_st_dict

#
# Step X: Matching steps
#

def check_ed_match(microdata_ed,microdata_st,sm_st_ed_dict):
    if (microdata_st is None) or (sm_st_ed_dict[microdata_st] is None):
        return False
    else:
        if microdata_ed in sm_st_ed_dict[microdata_st]:
            return True
        else:
            return False

def find_exact_matches(df,city,street,sm_all_streets,sm_st_ed_dict):

    num_records = len(df)

    cprint("Exact matching algorithm \n",attrs=['underline'],file=AnsiToWin32(sys.stdout))

    start = time.time()

    #
    # Check for exact matches between Steve Morse ST and microdata ST
    #

    df['sm_exact_match_bool'] = df[street].apply(lambda s: s in sm_all_streets)
    sm_exact_matches = np.sum(df['sm_exact_match_bool'])
    if num_records == 0:
        num_records += 1
    cprint("Exact matches before ED validation: "+str(sm_exact_matches)+" of "+str(num_records)+" cases ("+str(round(100*float(sm_exact_matches)/float(num_records),1))+"%)",file=AnsiToWin32(sys.stdout))

    #
    # Validate exact matches by comparing Steve Morse ED to microdata ED
    #

    df['sm_ed_match_bool'] = df.apply(lambda s: check_ed_match(s['ed'],s[street],sm_st_ed_dict), axis=1)

    #Validation of exact match fails if microdata ED and Steve Morse ED do not match
    failed_validation = df[(df.sm_exact_match_bool==True) & (df.sm_ed_match_bool==False)]
    num_failed_validation = len(failed_validation)
    #Validation of exact match succeeds if microdata ED and Steve Morse ED are the same
    passed_validation = df[(df.sm_exact_match_bool==True) & (df.sm_ed_match_bool==True)]
    num_passed_validation = len(passed_validation)

    #Keep track of unique street-ED pairs that have failed versus passed validation
    num_pairs_failed_validation = len(failed_validation.groupby(['ed',street]).count())
    num_pairs_passed_validation = len(passed_validation.groupby(['ed',street]).count())
    num_pairs = num_pairs_failed_validation + num_pairs_passed_validation
    end = time.time()
    exact_matching_time = round(float(end-start)/60,1)

    if sm_exact_matches == 0:
        sm_exact_matches += 1
    cprint("Failed ED validation: "+str(num_failed_validation)+" of "+str(sm_exact_matches)+" cases with exact name matches ("+str(round(100*float(len(failed_validation))/float(sm_exact_matches),1))+"%)",'red',file=AnsiToWin32(sys.stdout))
    cprint("Exact matches after ED validation: "+str(num_passed_validation)+" of "+str(num_records)+" cases ("+str(round(100*float(num_passed_validation)/float(num_records),1))+"%)",file=AnsiToWin32(sys.stdout))
    if num_pairs == 0:
        num_pairs += 1
    cprint("Cases failing ED validation represent "+str(num_pairs_failed_validation)+" of "+str(num_pairs)+" total Street-ED pairs ("+str(round(100*float(num_pairs_failed_validation)/float(num_pairs),1))+"%)\n",'yellow',file=AnsiToWin32(sys.stdout))
    cprint("Exact matching and ED validation for %s took %s\n" % (city,exact_matching_time), 'cyan', attrs=['dark'], file=AnsiToWin32(sys.stdout))

    prop_passed_validation = float(num_passed_validation)/float(num_records)
    prop_failed_validation = float(num_failed_validation)/float(num_records)
    prop_pairs_failed_validation = float(num_pairs_failed_validation)/float(num_pairs)

    exact_info = [num_records, num_passed_validation, prop_passed_validation, 
        num_failed_validation, prop_failed_validation, num_pairs_failed_validation, 
        num_pairs, prop_pairs_failed_validation,exact_matching_time]

    return df, exact_info

def find_fuzzy_matches(df,city,street,sm_all_streets,sm_ed_st_dict,check_too_similar=False):

    num_records = len(df)

    cprint("Fuzzy matching algorithm \n",attrs=['underline'],file=AnsiToWin32(sys.stdout))

    start = time.time()

    #
    # Find the best matching Steve Morse street name
    #

    #Create a set of all streets for fuzzy matching (create once, call on)
    sm_all_streets_fuzzyset = fuzzyset.FuzzySet(sm_all_streets)

    #Keep track of problem EDs
    problem_EDs = []

    #Function to check if street names differ by one character
    def diff_by_one_char(st1,st2):
        if len(st1) == len(st2):
            st1chars = list(st1)
            st2chars = list(st2)
            #Check how many characters differ, return True if only 1 character difference
            if sum([st1chars[i]!=st2chars[i] for i in range(len(st1chars))]) == 1:
                return True
            else:
                return False
        else:
            return False

    #Fuzzy matching algorithm
    def sm_fuzzy_match(street,ed):
        
        #Return null if street is blank
        if street == '':
            return ['','',False]

        #Microdata ED may not be in Steve Morse, if so then add it to problem ED list and return null
        try:
            sm_ed_streets = sm_ed_st_dict[ed]
            sm_ed_streets_fuzzyset = fuzzyset.FuzzySet(sm_ed_streets)
        except:
            problem_EDs.append(ed)
            return ['','',False]
        
        #Step 1: Find best match among streets associated with microdata ED
        try:
            best_match_ed = sm_ed_streets_fuzzyset[street][0]
        except:
            return ['','',False]

        #Step 2: Find best match among all streets
        try:
            best_match_all = sm_all_streets_fuzzyset[street][0]
        except:
            return ['','',False]    

        #Step 3: If both best matches are the same, return as best match
        if (best_match_ed[1] == best_match_all[1]) & (best_match_ed[0] >= 0.5):
            #Check how many other streets in ED differ by one character
            if check_too_similar:
                too_similar = sum([diff_by_one_char(st,best_match_ed[1]) for st in sm_ed_streets])
                if too_similar == 0:
                    return [best_match_ed[1],best_match_ed[0],True]
                else:
                    return['','',False]
            else: 
                return [best_match_ed[1],best_match_ed[0],True]
        else:
            return ['','',False]

    #Create dictionary based on Street-ED pairs for faster lookup using helper function
    df_no_validated_exact_match = df[~(df['sm_exact_match_bool'] & df['sm_ed_match_bool'])]
    df_grouped = df_no_validated_exact_match.groupby([street,'ed'])
    sm_fuzzy_match_dict = {}
    for st_ed,_ in df_grouped:
    	sm_fuzzy_match_dict[st_ed] = sm_fuzzy_match(st_ed[0],st_ed[1])

    #Helper function (necessary since dictionary built only for cases without validated exact matches)
    def get_fuzzy_match(exact_match,ed_match,street,ed):
        #Only look at cases without validated exact match
        if not (exact_match & ed_match):
            #Need to make sure "Unnamed" street doesn't get fuzzy matched
            if 'Unnamed' in street:
                return ['','',False]
            #Get fuzzy match    
            else:
                return sm_fuzzy_match_dict[street,ed]
        #Return null if exact validated match
        else:
            return ['','',False]

    #Get fuzzy matches 
    df['sm_fuzzy_match'], df['sm_fuzzy_match_score'], df['sm_fuzzy_match_bool'] = zip(*df.apply(lambda x: get_fuzzy_match(x['sm_exact_match_bool'],x['sm_ed_match_bool'],x[street],x['ed']), axis=1))

    #Compute number of cases without validated exact match
    passed_validation = df[(df.sm_exact_match_bool==True) & (df.sm_ed_match_bool==True)]
    num_passed_validation = len(passed_validation)
    num_current_residual_cases = num_records - num_passed_validation

    #Generate fuzzy_info
    num_fuzzy_matches = np.sum(df['sm_fuzzy_match_bool'])
    prop_sm_fuzzy_matches = float(num_fuzzy_matches)/num_records
    end = time.time()
    fuzzy_matching_time = round(float(end-start)/60,1)
    fuzzy_info = [num_fuzzy_matches, prop_sm_fuzzy_matches, fuzzy_matching_time, problem_EDs]

    cprint("Fuzzy matches (using microdata ED): "+str(num_fuzzy_matches)+" of "+str(num_current_residual_cases)+" unmatched cases ("+str(round(100*float(num_fuzzy_matches)/float(num_current_residual_cases),1))+"%)\n",file=AnsiToWin32(sys.stdout))
    cprint("Fuzzy matching for %s took %s\n" % (city,fuzzy_matching_time),'cyan',attrs=['dark'],file=AnsiToWin32(sys.stdout))

    return df, fuzzy_info

def fix_blank_st(df,city,HN_seq,street,sm_st_ed_dict):

    cprint("Fixing blank street names using house number sequences\n",attrs=['underline'],file=AnsiToWin32(sys.stdout))

    start = time.time()
    
    # Identify cases with blank street names
    df_STblank = df[df[street]=='']
    num_blank_street_names = len(df_STblank)    
    # Get indices of cases with blank street names
    STblank_indices = df_STblank.index.values
    # Create dictionary {k = index of blank street name : v = house number sequence}
    def get_range(blank_index):
        for i in HN_seq[street]:
            if i[0] <= blank_index <= i[1]:
                return i
    STblank_HNseq_dict = {}
    for blank_index in STblank_indices:
        STblank_HNseq_dict[blank_index] = get_range(blank_index)
    # Create list of ranges that contain cases with blank street names
    HNseq_w_blanks = [list(x) for x in set(tuple(x) for x in STblank_HNseq_dict.values())]
    # Create list of HNseq ranges with blanks
    seq_ranges_w_blanks = [range(i[0],i[1]+1) for i in HNseq_w_blanks]
    # Create singleton list
    singleton_list = [i for i in STblank_indices if len(range(STblank_HNseq_dict[i][0],STblank_HNseq_dict[i][1])) == 0]    
    # Create dictionary to hold {keys = frozenset(seq_ranges) : values = <assigned street name> }
    df['%sHN' % (street)] = df[street]
    for i in seq_ranges_w_blanks:
        # Select part of df with the blank street name
        df_seq_streets = df.ix[i[0]:i[-1],['ed',street,'hn']]
        # Collect street names (this will include '')
        seq_street_names = df_seq_streets[street].unique().tolist()
        # Count how many cases of each street name, store in dictionary
        street_count_dict = df_seq_streets.groupby([street]).count().to_dict().values()[0]
        ed_list = df_seq_streets['ed'].unique().tolist()
        # If sequence has only blank street names, leave street as blank
        if len(seq_street_names) == 1:
            continue
        # If sequence has one street name, replace blanks with that street name:
        if len(seq_street_names) == 2:
            seq_street_names.remove('')
            potential_street_name = seq_street_names[0]
            # Only change name if sequence does not span EDs and street-ED can be validated
            for ed in ed_list:
                if check_ed_match(ed,potential_street_name,sm_st_ed_dict) or ed == '':
                    df.ix[i,'%sHN' % (street)] = potential_street_name
            continue        
        # If sequence has one blank and more than one street name:
        else:
            non_blank_entries = len(df_seq_streets[df_seq_streets[street]!=''])
            for name in seq_street_names:
                # Choose a street name only if it constitutes at least 50% of non-blank street name entries
                if float(street_count_dict[name])/float(non_blank_entries) > 0.5:
                    potential_street_name = name
                    for ed in ed_list:
                        if check_ed_match(ed,potential_street_name,sm_st_ed_dict) or ed == '':
                            df.ix[i,'%sHN' % (street)] = potential_street_name

    df_STblank_post = df[df['%sHN' % (street)]=='']
    num_blank_street_names_post = len(df_STblank_post)    
    num_blank_street_fixed = num_blank_street_names - num_blank_street_names_post

    end = time.time()

    cprint("Found %s cases with blank street names" % (str(num_blank_street_names)),file=AnsiToWin32(sys.stdout))
 
    num_blank_street_singletons = len(singleton_list)
    per_singletons = round(100*float(num_blank_street_singletons)/float(num_blank_street_names),1)
    cprint("Of these cases, "+str(num_blank_street_singletons)+" ("+str(per_singletons)+"%% of blanks) were singletons",file=AnsiToWin32(sys.stdout))

    per_blank_street_fixed = round(100*float(num_blank_street_fixed)/float(len(df)),1)
    cprint("Of non-singleton cases, "+str(num_blank_street_fixed)+" ("+str(per_blank_street_fixed)+"%% of all cases) could be fixed using HN sequences",file=AnsiToWin32(sys.stdout))

    blank_fix_time = round(float(end-start)/60,1)
    cprint("Fixing blank streets for %s took %s\n" % (city,blank_fix_time),'cyan',attrs=['dark'],file=AnsiToWin32(sys.stdout))

    fix_blanks_info = [num_blank_street_names, num_blank_street_singletons, per_singletons, num_blank_street_fixed, per_blank_street_fixed, blank_fix_time]

    return df, fix_blanks_info
