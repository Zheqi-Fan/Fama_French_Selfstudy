# To add a new cell, type '#%%'
# To add a new markdown cell, type '#%% [markdown]'
#%%
##########################################
# Fama French Factors
# September 29 2019
# Edited by Xinyu LIU
# Originally from Qingyi (Freda) Song Drechsler
##########################################

import pandas as pd
import numpy as np
import datetime as dt
import wrds
import psycopg2 
import matplotlib.pyplot as plt
from dateutil.relativedelta import *
from pandas.tseries.offsets import *
from pandas.core.frame import DataFrame
from scipy import stats
import datetime

###################
# Connect to WRDS #
###################
conn = wrds.Connection(wrds_username='dachxiu')
#make it a constant portal by creating ppass

###################
# Compustat Block #
###################
comp = conn.raw_sql("""
                    select gvkey, datadate, at, pstkl, txditc,
                    pstkrv, seq, pstk
                    from comp.funda
                    where indfmt='INDL' 
                    and datafmt='STD'
                    and popsrc='D'
                    and consol='C'
                    and datadate >= '01/01/1959'
                    """)
#ctrl+/ make comments for multiple lines
##################
# Meanings of variables
##################
# gvkey 	Char	6	Global Company Key
# datadate 	Num	8	Data Date
# at 	Num	8	Assets - Total
# pstkl 	Num	8	Preferred Stock - Liquidating Value
# txditc 	Num	8	Deferred Taxes and Investment Tax Credit
# pstkrv 	Num	8	Preferred Stock - Redemption Value
# seq 	Num	8	Stockholders Equity - Parent
# pstk 	Num	8	Preferred/Preference Stock (Capital) - Total

#convert datadate to date fmt
comp['datadate']=pd.to_datetime(comp['datadate']) 
comp['year']=comp['datadate'].dt.year
#eg:from 2015-02-04（dtype: object） to 2015-02-04(datetime64[ns])
#create a new column for 'year'


# create preferrerd stock
comp['ps']=np.where(comp['pstkrv'].isnull(), comp['pstkl'], comp['pstkrv'])
comp['ps']=np.where(comp['ps'].isnull(),comp['pstk'], comp['ps'])
comp['ps']=np.where(comp['ps'].isnull(),0,comp['ps'])
#manipulate ps data in the sequense of redemption, liquidating and total value, last resolution is 0

comp['txditc']=comp['txditc'].fillna(0)

# create book equity
comp['be']=comp['seq']+comp['txditc']-comp['ps']
comp['be']=np.where(comp['be']>0, comp['be'], np.nan)
#Book value of equity equals to Stockholders Equity + Deferred Tax - Preferred Stocks 
#set nan value for book equity that is less than 0

# number of years in Compustat
comp=comp.sort_values(by=['gvkey','datadate'])
comp['count']=comp.groupby(['gvkey']).cumcount()
#Sort DataFrame by column gvkey and datadate
#Mark cumulative number of each gvkey as of that row, starting from 0

comp=comp[['gvkey','datadate','year','be','count']]

###################
# CRSP Block      #
###################
# sql similar to crspmerge macro
crsp_m = conn.raw_sql("""
                      select a.permno, a.permco, a.date, b.shrcd, b.exchcd,
                      a.ret, a.retx, a.shrout, a.prc
                      from crsp.msf as a
                      left join crsp.msenames as b
                      on a.permno=b.permno
                      and b.namedt<=a.date
                      and a.date<=b.nameendt
                      where a.date between '01/01/1959' and '12/31/2017'
                      and b.exchcd between 1 and 3
                      """) 
#crsp.msf refers to Monthly Stock File: Monthly Stock - Securities
#crsp.msenames refers to CRSP Monthly Stock Event - Name History
#PERMNO 	Num	8	PERMNO,PERMNO is a unique five-digit permanent identifier assigned by CRSP to each security in the file
#PERMCO 	Num	8	PERMCO,PERMCO is a unique permanent identifier assigned by CRSP to all companies with issues on a CRSP file
#DATE 	Num	4	Date of Observation,DATE is the date corresponding to CAPV and YEAR
#RET 	Num	8	Returns,A return is the change in the total value of an investment in a common stock over some period of time per dollar of initial investment.
#RETX 	Num	8	Returns without Dividends, Ordinary dividends and certain other regularly taxable dividends are excluded from the returns calculation. The formula is the same as for RET except d(t) is usually 0
#SHROUT 	Num	8	Shares Outstanding,SHROUT is the number of publicly held shares, recorded in thousands
#PRC 	Num	8	Price or Bid/Ask Average,Prc is the closing price or the negative bid/ask average for a trading day.

#SHRCD 	Num	8	Share Code
#EXCHCD 	Num	8	Exchange Code
#NAMEDT 	Num	8	Names Date
#NAMEENDT 	Num	8	Names Ending Date

#The left join treats one table—the left table—as the primary dataset for the join. 
#This means that every row from the left table will be in the result set, 
#even if there’s no rating from the right table. Below, I’ve highlighted the rows that the left join will return.

# change variable format to int
crsp_m[['permco','permno','shrcd','exchcd']]=crsp_m[['permco','permno','shrcd','exchcd']].astype(int)

# Line up date to be end of month
crsp_m['date']=pd.to_datetime(crsp_m['date'])
crsp_m['jdate']=crsp_m['date']+MonthEnd(0)
#The 1 in MonthEnd just specifies to move one step forward to the next date that's a month end.

# add delisting return
dlret = conn.raw_sql("""
                     select permno, dlret, dlstdt 
                     from crsp.msedelist
                     """)
#MSEDELIST		CRSP Monthly Stock Event - Delisting
#DLRET 	Num	8	Delisting Return,DLRET is the return of the security after it is delisted. 
#It is calculated by comparing a value after delisting against the price on the security's last trading date. 
#The value after delisting can include a delisting price or the amount from a final distribution.
#DLSTDT 	Num	8	Delisting Date,DLSTDT contains the date (in YYMMDD format) of a security's last price on the current exchange.

#process dlret
dlret.permno=dlret.permno.astype(int)
dlret['dlstdt']=pd.to_datetime(dlret['dlstdt'])
dlret['jdate']=dlret['dlstdt']+MonthEnd(0)

#merge dlret and crsp_m
crsp = pd.merge(crsp_m, dlret, how='left',on=['permno','jdate'])
#crsp and dlret share the same column names: permno and jdate

#process crsp
crsp['dlret']=crsp['dlret'].fillna(0)
crsp['ret']=crsp['ret'].fillna(0)
crsp['retadj']=(1+crsp['ret'])*(1+crsp['dlret'])-1

# calculate market equity
crsp['me']=crsp['prc'].abs()*crsp['shrout'] 
#market equity equals to price of stock times shares of outstanding

#process crsp
crsp=crsp.drop(['dlret','dlstdt','prc','shrout'], axis=1)
crsp=crsp.sort_values(by=['jdate','permco','me'])

### Aggregate Market Cap ###
# sum of me across different permno belonging to same permco a given date
crsp_summe = crsp.groupby(['jdate','permco'])['me'].sum().reset_index()
# largest mktcap within a permco/date
crsp_maxme = crsp.groupby(['jdate','permco'])['me'].max().reset_index()
# join by jdate/maxme to find the permno
crsp1=pd.merge(crsp, crsp_maxme, how='inner', on=['jdate','permco','me'])
# drop me column and replace with the sum me
crsp1=crsp1.drop(['me'], axis=1)
# join with sum of me to get the correct market cap info
crsp2=pd.merge(crsp1, crsp_summe, how='inner', on=['jdate','permco'])
# sort by permno and date and also drop duplicates
crsp2=crsp2.sort_values(by=['permno','jdate']).drop_duplicates()
# important to have a duplicate check

# keep December market cap
crsp2['year']=crsp2['jdate'].dt.year
crsp2['month']=crsp2['jdate'].dt.month
decme=crsp2[crsp2['month']==12]
decme=decme[['permno','date','jdate','me','year']].rename(columns={'me':'dec_me'})

### July to June dates
crsp2['ffdate']=crsp2['jdate']+MonthEnd(-6)
crsp2['ffyear']=crsp2['ffdate'].dt.year
crsp2['ffmonth']=crsp2['ffdate'].dt.month
crsp2['1+retx']=1+crsp2['retx']
crsp2=crsp2.sort_values(by=['permno','date'])

# cumret by stock
crsp2['cumretx']=crsp2.groupby(['permno','ffyear'])['1+retx'].cumprod()
#cumprod returns the product of the year in this case, which is the cumulative return as time goes by

# lag cumret
crsp2['lcumretx']=crsp2.groupby(['permno'])['cumretx'].shift(1)

# lag market cap
crsp2['lme']=crsp2.groupby(['permno'])['me'].shift(1)

# if first permno then use me/(1+retx) to replace the missing value
crsp2['count']=crsp2.groupby(['permno']).cumcount()
crsp2['lme']=np.where(crsp2['count']==0, crsp2['me']/crsp2['1+retx'], crsp2['lme'])

# baseline me
mebase=crsp2[crsp2['ffmonth']==1][['permno','ffyear', 'lme']].rename(columns={'lme':'mebase'})

# merge result back together
crsp3=pd.merge(crsp2, mebase, how='left', on=['permno','ffyear'])
crsp3['wt']=np.where(crsp3['ffmonth']==1, crsp3['lme'], crsp3['mebase']*crsp3['lcumretx'])

decme['year']=decme['year']+1
decme=decme[['permno','year','dec_me']]

# Info as of June
crsp3_jun = crsp3[crsp3['month']==6]

crsp_jun = pd.merge(crsp3_jun, decme, how='inner', on=['permno','year'])
crsp_jun=crsp_jun[['permno','date', 'jdate', 'shrcd','exchcd','retadj','me','wt','cumretx','mebase','lme','dec_me']]
crsp_jun=crsp_jun.sort_values(by=['permno','jdate']).drop_duplicates()

#######################
# CCM Block           #
#######################
ccm=conn.raw_sql("""
                  select gvkey, lpermno as permno, linktype, linkprim, 
                  linkdt, linkenddt
                  from crsp.ccmxpf_linktable
                  where substr(linktype,1,1)='L'
                  and (linkprim ='C' or linkprim='P')
                  """)
#CCMXPF_LINKTABLE		CRSP/COMPUSTAT Merged - Link History w/ Used Flag
#lpermno 	Num	8	Historical CRSP PERMNO Link to COMPUSTAT Record
# linktype 	Char	2	Link Type Code,
# Link Type Code is a 2-character code providing additional detail on the usage of the link data available.
# linkprim 	Char	1	Primary Link Marker
# linkdt 	Num	8	First Effective Date of Link
# linkenddt 	Num	8	Last Effective Date of Link

ccm['linkdt']=pd.to_datetime(ccm['linkdt'])
ccm['linkenddt']=pd.to_datetime(ccm['linkenddt'])
# if linkenddt is missing then set to today date
ccm['linkenddt']=ccm['linkenddt'].fillna(pd.to_datetime('today'))
#attention: pd.to.datetime does not convert today(M8[ns]) into format '%Y\%m\%d', need to go with ccm[].dt.date
# eg: ccm['linkenddt']=ccm['linkenddt'].dt.date

ccm1=pd.merge(comp[['gvkey','datadate','be', 'count']],ccm,how='left',on=['gvkey'])
ccm1['yearend']=ccm1['datadate']+YearEnd(0)
ccm1['jdate']=ccm1['yearend']+MonthEnd(6)

# set link date bounds
ccm2=ccm1[(ccm1['jdate']>=ccm1['linkdt'])&(ccm1['jdate']<=ccm1['linkenddt'])]
ccm2=ccm2[['gvkey','permno','datadate','yearend', 'jdate','be', 'count']]

# link comp and crsp
ccm_jun=pd.merge(crsp_jun, ccm2, how='inner', on=['permno', 'jdate'])
ccm_jun['beme']=ccm_jun['be']*1000/ccm_jun['dec_me']

# select NYSE stocks for bucket breakdown
# exchcd = 1 and positive beme and positive me and shrcd in (10,11) and at least 2 years in comp
nyse=ccm_jun[(ccm_jun['exchcd']==1) & (ccm_jun['beme']>0) & (ccm_jun['me']>0) & (ccm_jun['count']>1) & ((ccm_jun['shrcd']==10) | (ccm_jun['shrcd']==11))]

#####
# size breakdown
nyse_sz=nyse.groupby(['jdate'])['me'].median().to_frame().reset_index().rename(columns={'me':'sizemedn'})
# beme breakdown
nyse_bm=nyse.groupby(['jdate'])['beme'].describe(percentiles=[0.3, 0.7]).reset_index()
nyse_bm=nyse_bm[['jdate','30%','70%']].rename(columns={'30%':'bm30', '70%':'bm70'})

nyse_breaks = pd.merge(nyse_sz, nyse_bm, how='inner', on=['jdate'])
# join back size and beme breakdown
ccm1_jun = pd.merge(ccm_jun, nyse_breaks, how='left', on=['jdate'])


# function to assign sz and bm bucket
def sz_bucket(row):
    if row['me']==np.nan:
        value=''
    elif row['me']<=row['sizemedn']:
        value='S'
    else:
        value='B'
    return value

def bm_bucket(row):
    if 0<=row['beme']<=row['bm30']:
        value = 'L'
    elif row['beme']<=row['bm70']:
        value='M'
    elif row['beme']>row['bm70']:
        value='H'
    else:
        value=''
    return value

# assign size portfolio
ccm1_jun['szport']=np.where((ccm1_jun['beme']>0)&(ccm1_jun['me']>0)&(ccm1_jun['count']>=1), ccm1_jun.apply(sz_bucket, axis=1), '')
# assign book-to-market portfolio
ccm1_jun['bmport']=np.where((ccm1_jun['beme']>0)&(ccm1_jun['me']>0)&(ccm1_jun['count']>=1), ccm1_jun.apply(bm_bucket, axis=1), '')
# create positivebmeme and nonmissport variable
ccm1_jun['posbm']=np.where((ccm1_jun['beme']>0)&(ccm1_jun['me']>0)&(ccm1_jun['count']>=1), 1, 0)
ccm1_jun['nonmissport']=np.where((ccm1_jun['bmport']!=''), 1, 0)


# store portfolio assignment as of June
june=ccm1_jun[['permno','date', 'jdate', 'bmport','szport','posbm','nonmissport']]
june['ffyear']=june['jdate'].dt.year
#if in any case there is a warning regarding view versus copy, try the code below
#june.insert(len(june.columns), 'ffyear', june['jdate'].dt.year)
#june.loc[:, 'ffyear'] = june['jdate'].dt.year

# merge back with monthly records
crsp3 = crsp3[['date','permno','shrcd','exchcd','retadj','me','wt','cumretx','ffyear','jdate']]
ccm3=pd.merge(crsp3, 
        june[['permno','ffyear','szport','bmport','posbm','nonmissport']], how='left', on=['permno','ffyear'])

# keeping only records that meet the criteria
ccm4=ccm3[(ccm3['wt']>0)& (ccm3['posbm']==1) & (ccm3['nonmissport']==1) & 
          ((ccm3['shrcd']==10) | (ccm3['shrcd']==11))]

############################
# Form Fama French Factors #
############################

# function to calculate value weighted return
def wavg(group, avg_name, weight_name):
    d = group[avg_name]
    w = group[weight_name]
    try:
        return (d * w).sum() / w.sum()
    except ZeroDivisionError:
        return np.nan

# value-weigthed return
vwret=ccm4.groupby(['jdate','szport','bmport']).apply(wavg, 'retadj','wt').to_frame().reset_index().rename(columns={0: 'vwret'})
vwret['sbport']=vwret['szport']+vwret['bmport']

# firm count
vwret_n=ccm4.groupby(['jdate','szport','bmport'])['retadj'].count().reset_index().rename(columns={'retadj':'n_firms'})
vwret_n['sbport']=vwret_n['szport']+vwret_n['bmport']

# tranpose
ff_factors=vwret.pivot(index='jdate', columns='sbport', values='vwret').reset_index()
ff_nfirms=vwret_n.pivot(index='jdate', columns='sbport', values='n_firms').reset_index()

# create SMB and HML factors
ff_factors['WH']=(ff_factors['BH']+ff_factors['SH'])/2
ff_factors['WL']=(ff_factors['BL']+ff_factors['SL'])/2
ff_factors['WHML'] = ff_factors['WH']-ff_factors['WL']

ff_factors['WB']=(ff_factors['BL']+ff_factors['BM']+ff_factors['BH'])/3
ff_factors['WS']=(ff_factors['SL']+ff_factors['SM']+ff_factors['SH'])/3
ff_factors['WSMB'] = ff_factors['WS']-ff_factors['WB']
ff_factors=ff_factors.rename(columns={'jdate':'date'})

# n firm count
ff_nfirms['H']=ff_nfirms['SH']+ff_nfirms['BH']
ff_nfirms['L']=ff_nfirms['SL']+ff_nfirms['BL']
ff_nfirms['HML']=ff_nfirms['H']+ff_nfirms['L']

ff_nfirms['B']=ff_nfirms['BL']+ff_nfirms['BM']+ff_nfirms['BH']
ff_nfirms['S']=ff_nfirms['SL']+ff_nfirms['SM']+ff_nfirms['SH']
ff_nfirms['SMB']=ff_nfirms['B']+ff_nfirms['S']
ff_nfirms['TOTAL']=ff_nfirms['SMB']
ff_nfirms=ff_nfirms.rename(columns={'jdate':'date'})

###################
# Compare With FF #
###################
_ff = conn.get_table(library='ff', table='factors_monthly')
_ff=_ff[['date','smb','hml']]
_ff['date']=_ff['date']+MonthEnd(0)

_ffcomp = pd.merge(_ff, ff_factors[['date','WSMB','WHML']], how='inner', on=['date'])
_ffcomp70=_ffcomp[_ffcomp['date']>='01/01/1970']
print(stats.pearsonr(_ffcomp70['smb'], _ffcomp70['WSMB']))
print(stats.pearsonr(_ffcomp70['hml'], _ffcomp70['WHML']))

#Print out the above result in a formal way
mydata=[stats.pearsonr(_ffcomp70['smb'], _ffcomp70['WSMB']),stats.pearsonr(_ffcomp70['hml'], _ffcomp70['WHML'])]
mydata
a=DataFrame(mydata, index=['SMB','HML'], columns=['correlation coefficient','p value'])
a

###################
# Visualization of comparison #
###################
#You may wanna change the data range in the future for case by case use

plt.figure(figsize=(12,8)) 
plt.suptitle("Comparison of Results", fontsize=14)

ax1=plt.subplot(2, 1, 1)
plt.ylabel("Return")
plt.title("SMB")
plt.plot(_ffcomp70['date'],_ffcomp70['smb'],label = 'smb',color='red')
plt.plot(_ffcomp70['date'],_ffcomp70['WSMB'], label = 'WSMB',color='blue')
plt.legend(loc="best")
ax1.set_xlim([datetime.date(1961, 7, 31), datetime.date(2018, 12, 31)])
plt.setp(ax1.get_xticklabels(), visible=False)

ax2=plt.subplot(2, 1, 2)
plt.xlabel('Time(y)')
plt.ylabel("Return")
plt.title("HML")
plt.plot(_ffcomp70['date'],_ffcomp70['hml'],label = 'hml', color='red')
plt.plot(_ffcomp70['date'],_ffcomp70['WHML'],label = 'WHML', color='blue')
ax2.set_xlim([datetime.date(1961, 7, 31), datetime.date(2018, 12, 31)])
plt.legend(loc="best")
plt.show()

#further inspection on cumulative returns
plt.figure(figsize=(12,8)) 
plt.suptitle("Comparison of Results", fontsize=14)

ax1=plt.subplot(2, 1, 1)
_ffcomp60smb=_ffcomp[['date','smb','WSMB']]
_ffcomp60smb.set_index(["date"], inplace=True)
plt.ylabel("Cumulative Return")
plt.title("SMB")
plt.plot((_ffcomp60smb + 1).cumprod() - 1)
#plt.legend(loc="best")
ax1.set_xlim([datetime.date(1961, 7, 31), datetime.date(2018, 12, 31)])

ax2=plt.subplot(2, 1, 2)
_ffcomp60hml=_ffcomp[['date','hml','WHML']]
_ffcomp60hml.set_index(["date"], inplace=True)
plt.xlabel('Time(y)')
plt.ylabel("Cumulative Return")
plt.title("HML")
#plt.legend(loc="best")
plt.plot((_ffcomp60hml + 1).cumprod() - 1) 
ax2.set_xlim([datetime.date(1961, 7, 31), datetime.date(2018, 12, 31)])

###################
# Key reflections on the construction #
###################
#Q1: What is our sample pool?
#Q2: How often do we renew the portfolio?
#Q3: What databases are used?
#Q4: How to define the criteria for size and value?
# Basically this program updates its portfolio on a yearly base. From July at year-t to June at year-t+1, it can calculate the monthly value-weighted return of each portfolio and eventually give us factors we need. Benchmark for classification is NYSE's Me in June and Beme in December last year. 