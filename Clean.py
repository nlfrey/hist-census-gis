from multiprocessing import Pool
import pandas as pd
import rpy2.robjects as robjects
import sys
import time
from termcolor import colored, cprint
from colorama import AnsiToWin32, init
from microclean.STclean import *
from microclean.HNclean import *

def clean_microdata(city_info):

	city = city_info[0]
	state = city_info[1]
	year = city_info[2]
	start_total = time.time()

	HN_SEQ = {}
	ED_ST_HN_dict = {}

	#Save to logfile
#	init()
#	sys.stdout = open(file_path + "/%s/logs/%s_Cleaning.log" % (str(year),city.replace(' ','')+state),'wb')

	cprint('%s Automated Cleaning\n' % (city), attrs=['bold'], file=AnsiToWin32(sys.stdout))

	# Load city
	df, load_time = load_city(city.replace(' ',''),state,year)

	# Pre-clean street names
	df, preclean_time = preclean_street(df,city)    

	# Use pre-cleaned street names to get house number sequences
	street_var = 'street_precleaned'
	HN_SEQ[street_var], ED_ST_HN_dict[street_var] = get_HN_SEQ(df,year,street_var,debug=True)
	df['hn_outlier1'] = df.apply(lambda s: is_HN_OUTLIER(s['ed'],s[street_var],s['hn'],ED_ST_HN_dict[street_var]),axis=1)

	# Load Steve Morse Street-ED data
	sm_all_streets, sm_st_ed_dict, sm_ed_st_dict = load_steve_morse(df,city,state,year,flatten=True)

	# Use house number sequences to fill in blank street names
	df, fix_blanks_info1 = fix_blank_st(df,city,HN_SEQ,'street_precleaned',sm_st_ed_dict)
	num_blank_street_names1, num_blank_street_singletons1, per_singletons1, num_blank_street_fixed1, per_blank_street_fixed1, blank_fix_time1 = fix_blanks_info1

	# Get exact matches
	df, exact_info = find_exact_matches(df,city,'street_precleanedHN',sm_all_streets,sm_st_ed_dict)
	num_records, num_passed_validation, prop_passed_validation, num_failed_validation, prop_failed_validation, num_pairs_failed_validation, num_pairs, prop_pairs_failed_validation, exact_matching_time = exact_info 

	# Get fuzzy matches
	df, fuzzy_info, problem_EDs = find_fuzzy_matches(df,city,'street_precleanedHN',sm_all_streets,sm_ed_st_dict)
	num_fuzzy_matches, prop_fuzzy_matches, fuzzy_matching_time = fuzzy_info

	# Use fuzzy matches to get house number sequences
	street_var = 'street_post_fuzzy'
	df[street_var] = df['street_precleanedHN']
	df.loc[df['sm_fuzzy_match_bool'],street_var] = df['sm_fuzzy_match']

	HN_SEQ[street_var], ED_ST_HN_dict[street_var] = get_HN_SEQ(df,year,street_var,debug=True)
	df['hn_outlier2'] = df.apply(lambda s: is_HN_OUTLIER(s['ed'],s[street_var],s['hn'],ED_ST_HN_dict[street_var]),axis=1)

	# Use house number sequences to fill in blank street names
	df, fix_blanks_info2 = fix_blank_st(df,city,HN_SEQ,'street_post_fuzzy',sm_st_ed_dict)
	num_blank_street_names2, num_blank_street_singletons2, per_singletons2, num_blank_street_fixed2, per_blank_street_fixed2, blank_fix_time2 = fix_blanks_info2

	cprint("Overall matches of any kind\n",attrs=['underline'],file=AnsiToWin32(sys.stdout))

	# Initialize cases as having no match
	df['overall_match'] = ''
	df['overall_match_type'] = 'NoMatch'
	df['overall_match_bool'] = False

	df.loc[df['sm_fuzzy_match_bool'],'overall_match'] = df['street_post_fuzzy']
	df.loc[df['sm_exact_match_bool'] & df['sm_ed_match_bool'],'overall_match'] = df['street_precleanedHN']

	df.loc[df['sm_fuzzy_match_bool'],'overall_match_type'] = 'FuzzySM'
	df.loc[df['sm_exact_match_bool'] & df['sm_ed_match_bool'],'overall_match_type'] = 'ExactSM'

	df.loc[(df['overall_match_type'] == 'ExactSM') | (df['overall_match_type'] == 'FuzzySM'),'overall_match_bool'] = True 

	num_overall_matches = np.sum(df['overall_match_bool'])
	cprint("Overall matches: "+str(num_overall_matches)+" of "+str(num_records)+" total cases ("+str(round(100*float(num_overall_matches)/float(num_records),1))+"%)\n",file=AnsiToWin32(sys.stdout))

	end_total = time.time()
	total_time = round(float(end_total-start_total)/60,1)
	cprint("Total processing time for %s: %s\n" % (city,total_time),'cyan',attrs=['bold'],file=AnsiToWin32(sys.stdout))

	problem_EDs = list(set(problem_EDs))
	print("Problem EDs: %s" % (problem_EDs))

	#	sys.stdout.close()

	problem_EDs_present = False
	if len(problem_EDs) > 0:
		problem_EDs_present = True

	df['check_hn'] = df['hn_outlier2']
	df['check_st'] = ~df['overall_match_bool']
	df['check_ed'] = np.where(df['sm_exact_match_bool'] & ~df['sm_ed_match_bool'],True,False)

	# Set priority level for residual cases

	def enum_check_seq(df):

		df['check_bool'] = np.where(df['check_hn'] | df['check_st'],True,False)
		df['enum_seq'] = 0

		prev = 0
		splits = np.append(np.where(np.diff(df['check_bool']) != 0)[0],len(df['check_bool'])-1)

		num = 0
		enum_check_list = []
		for split in splits:
		    enum_check_list.append(np.arange(1,df['check_bool'].size+1,1)[prev:split])
		    prev = split
		
		for i in range(len(enum_check_list)):
			df.ix[list(enum_check_list[i]),'enum_seq'] = i

		return df

	df = enum_check_seq(df)

	resid_case_counts = df.groupby(['enum_seq'])
	enum_seq_counts_dict = resid_case_counts.size().to_dict()
	enum_seq_check_dict = resid_case_counts['check_bool'].mean().to_dict()

	#	Clean_priority: 
	#
	#	1 = >100 cases in sequence (either HN or ST)
	#	2 = >50 cases in sequence (either HN or ST)
	#	3 = >20 cases in sequence (either HN or ST)
	#	4 = >10 cases in sequence (either HN or ST)
	#	5 = >5 cases in sequence (either HN or ST)
	# 	6 = >1 case in sequence (either HN or ST)
	#	7 = 1 case in sequence (either HN or ST)
	#	9 = Blank HN and blank ST

	def assign_priority(enum):
		count = enum_seq_counts_dict[enum]
		check = enum_seq_check_dict[enum]
		if check:
			if count == 1:
				priority = 7	
			if count > 1:
				priority = 6	
			if count >= 5:
				priority = 5
			if count >= 10:
				priority = 4
			if count >= 20:
				priority = 3	
			if count >= 50:
				priority = 2																				
			if count >= 100:
				priority = 1
		else:
			priority = None		
		return priority	

	priority = {}
	for enum,_ in resid_case_counts:
		priority[enum] = assign_priority(enum)
 
	num_priority = {}
	for i in range(1,8):
		num_priority[i] = len([k for k,v in priority.items() if v == i])

	df['clean_priority'] = df['enum_seq'].apply(assign_priority)

#	df['st_and_hn_blank'] = False
#	df.loc[(np.isnan(df['hn'])) & (df['street_precleanedHN']==''), 'st_and_hn_blank'] = True
#	df.loc[df['st_and_hn_blank'],'clean_priority'] = 9

	priority_counts = df.groupby(['clean_priority']).size().to_dict()

	# Save full dataset 
	city_file_name = city.replace(' ','') + state
	file_name_all = file_path + '/%s/autocleaned/%s_AutoCleaned.csv' % (str(year),city_file_name)
	df.to_csv(file_name_all)

	# Save only a subset of variables for students to use when cleaning

	df = df.replace({'check_hn' : { True : 'yes', False: ''}, 
		'check_st' : { True : 'yes', False: ''},
		'check_ed' : { True : 'yes', False: ''}})

	if year==1940:
		student_vars = ['image_id','line_num','institution','ed','hhid','hhorder','rel_id','pid','dn','hn','street_raw','street_precleanedHN','check_hn','check_st','clean_priority']
	if year==1930:
		student_vars = ['index','image_id','line_num','institution','ed','block','hhid','rel_id','pid','dn','hn','street_raw','street_precleanedHN','check_hn','check_st','clean_priority']
	
	df_forstudents = df[student_vars]
	file_name_students = file_path + '/%s/forstudents/%s_ForStudents.csv' % (str(year),city_file_name)
	df_forstudents.to_csv(file_name_students)

	# Generate remaining dashboard variables

	num_hn_outliers1 = 	df['hn_outlier1'].sum()  
	num_hn_outliers2 = 	df['hn_outlier2'].sum() 
	num_resid_check_st = len(df[df['check_st'] & ~df['check_hn']])
	prop_resid_check_st = float(num_resid_check_st)/num_records
	num_resid_check_hn = len(df[~df['check_st'] & df['check_hn']])
	prop_resid_check_hn = float(num_resid_check_hn)/num_records
	num_resid_check_st_hn = len(df[df['check_st'] & df['check_hn']])
	prop_resid_check_st_hn = float(num_resid_check_st_hn)/num_records

	num_blank_street_fixed = num_blank_street_fixed1 + num_blank_street_fixed2
	prop_blank_street_fixed = float(num_blank_street_fixed)/num_records

	num_resid_st = len(df[df['check_st']]) - num_blank_street_fixed 
	prop_resid_st = float(num_resid_st)/num_records
#	num_resid_hn = len(df[df['check_hn']])
#	prop_resid_hn = float(num_resid_hn)/num_records
#	num_resid_st_hn = len(df[df['check_st'] | df['check_hn']]) 
#	prop_resid_st_hn = float(num_resid_st_hn)/float(num_records)

	num_resid_hn_total = num_resid_check_hn + num_resid_check_st_hn
	prop_resid_hn_total = prop_resid_check_hn + prop_resid_check_st_hn
	num_resid_total = num_resid_check_st + num_resid_check_st_hn + num_resid_check_hn
	prop_resid_total = prop_resid_check_st + prop_resid_check_st_hn + prop_resid_check_hn

	blank_fix_time = blank_fix_time1 + blank_fix_time2

	info = [year, city, state, num_records, 
		prop_passed_validation, prop_fuzzy_matches, prop_blank_street_fixed, prop_resid_st,
		'', 
		city, state, num_passed_validation, num_fuzzy_matches, num_blank_street_fixed, num_resid_st,
		'', 
		city, state, prop_resid_check_hn, prop_resid_check_st_hn, prop_resid_hn_total,
		'',
		city, state, num_resid_check_hn, num_resid_check_st_hn, num_resid_hn_total,
		'',		
		city, state, prop_resid_check_hn, prop_resid_check_st_hn, prop_resid_check_st, prop_resid_total,
		'',
		city, state, num_resid_check_hn, num_resid_check_st_hn, num_resid_check_st, num_resid_total,
		'',
		city, state, priority_counts[1],priority_counts[2],priority_counts[3],priority_counts[4],priority_counts[5],priority_counts[6],priority_counts[7],sum(priority_counts.values()),
		'',
		city, state, num_priority[1],num_priority[2],num_priority[3],num_priority[4],num_priority[5],num_priority[6],num_priority[7],sum(num_priority.values()),
		'',
		city, state, problem_EDs_present, num_failed_validation, prop_failed_validation, 
		num_pairs_failed_validation, num_pairs, prop_pairs_failed_validation, 
		'',		
		city, state, num_hn_outliers1, num_blank_street_names1, num_blank_street_singletons1, per_singletons1,   
		num_hn_outliers2, num_blank_street_names2, num_blank_street_singletons2, per_singletons2, 
		'',
		city, state, load_time, preclean_time, exact_matching_time, fuzzy_matching_time, 
		blank_fix_time, total_time] 

	return info 

file_path = '/home/s4-data/LatestCities' 
city_info_file = file_path + '/CityInfo.csv' 
city_info_df = pd.read_csv(city_info_file)
city_info_list = city_info_df[['city_name','state_abbr']].values.tolist()

year = int(sys.argv[1])
#year = 1930

for i in city_info_list:                
	i.append(year)

'''
temp =[]
for i in city_info_list:
	temp.append(clean_microdata(i))
'''	

pool = Pool(8)
temp = pool.map(clean_microdata, city_info_list)
pool.close()

names = ['Year', 'City', 'State', 'NumCases',
	'propExactMatchesValidated','propFuzzyMatches','propBlankSTfixed','propResidSt',
	'',
	'City', 'State','ExactMatchesValidated','FuzzyMatches','BlankSTfixed','ResidSt',
	'',
	'City', 'State','propCheckHn','propCheckStHn','propCheckHnTotal',
	'',
	'City', 'State','CheckHn','CheckStHn','CheckHnTotal',
	'',
	'City', 'State','propCheckHn','propCheckStHn','propCheckSt','propCheckTotal',
	'',
	'City', 'State','CheckHn','CheckStHn','CheckSt','CheckTotal',
	'',
	'City', 'State','100+','50-99','20-49','10-19','5-9','2-4','1','TotalPriority',
	'',
	'City', 'State','st 100+','st 50-99','st 20-49','st 10-19','st 5-9','st 2-4','st 1','StTotalPriority'
	'',
	'City', 'State','ProblemEDs', 'ExactMatchesFailed','propExactMatchesFailed',
	'StreetEDpairsFailed','StreetEDpairsTotal','propStreedEDpairsFailed',
	'',
	'City', 'State','HnOutliers1','StreetNameBlanks1','BlankSingletons1','PerSingletons1',
	'HnOutliers2','StreetNameBlanks2','BlankSingletons2','PerSingletons2',
	'',
	'City', 'State','LoadTime','PrecleanTime','ExactMatchingTime','FuzzyMatchingTime',
	'BlankFixTime','TotalTime']
df = pd.DataFrame(temp,columns=names)

dfSTprop = df.ix[:,1:9].sort_values(by='propResidSt').reset_index()
dfSTnum = df.ix[:,9:16].sort_values(by='ResidSt',ascending=False).reset_index()
dfHNprop = df.ix[:,16:22].sort_values(by='propCheckHnTotal').reset_index()
dfHNnum = df.ix[:,22:28].sort_values(by='CheckHnTotal',ascending=False).reset_index()
dfRprop =df.ix[:,28:35].sort_values(by='propCheckTotal').reset_index()
dfRnum = df.ix[:,35:42].sort_values(by='CheckTotal',ascending=False).reset_index()
dfPriority = df.ix[:,42:53].sort_values(by='TotalPriority',ascending=False).reset_index()
dfnumPriority = df.ix[:,53:64].sort_values(by='StTotalPriority',ascending=False).reset_index()
dfED = df.ix[:,64:74].reset_index()
dfFixBlank = df.ix[:,74:85].reset_index()
dfTime = df.ix[:,85:93].sort_values(by='TotalTime',ascending=False).reset_index()

dashboard = pd.concat([dfSTprop,dfSTnum,dfHNprop,dfHNnum,dfRprop,dfRnum,dfPriority,dfED,dfFixBlank,dfTime],axis=1)
del dashboard['index']

csv_file = file_path + '/%s/CleaningSummary%s.csv' % (str(year),str(year))
dashboard.to_csv(csv_file)

#convert_dta_cmd = "stata -b do ConvertToStataForStudents%s.do" % (str(year))
#os.system(convert_dta_cmd)
