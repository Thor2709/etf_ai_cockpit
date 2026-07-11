# ISSUE-0035 export gate

The final export command wrote `data/derived/data_health.csv` with 11 rows. Its header contains `dataset,status,path,row_count,checksum,as_of,freshness,provider,last_success,last_failure,warnings`, and the validation output confirms price, FX, holdings, fundamentals, news, macro, forecasts and backtest rows are present. The recorded command/result is `evidence/wave4/data-health-export-responsive-final.txt`.
