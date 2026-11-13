import FinanceDataReader as fdr

try:
    df_krx = fdr.StockListing('KRX')
    print("KRX success, count:", len(df_krx))
    print("Columns:", df_krx.columns.tolist())
    print(df_krx.head(2)[['Code', 'Name', 'Market', 'Marcap']])
except Exception as e:
    print("KRX error:", e)
