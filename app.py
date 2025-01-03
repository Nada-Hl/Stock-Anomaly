#!/usr/bin/env python
# coding: utf-8

# In[1]:


import pandas as pd
from datetime import datetime, time
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi import Request
from pydantic import BaseModel
import nbformat
from threading import Thread
import uvicorn
import nest_asyncio
from typing import List
import math
from fastapi.responses import JSONResponse
import pickle
import numpy as np
from sklearn.preprocessing import StandardScaler
import json
from io import BytesIO
from azure.storage.blob import BlobServiceClient
from alpha_vantage.timeseries import TimeSeries
import io
import sys
import matplotlib.pyplot as plt
import builtins
from datetime import timezone


# In[2]:
API_KEY = 'WRUHOXVS7HM2OG23'
SYMBOL = "MSFT"

connection_string = 'DefaultEndpointsProtocol=https;AccountName=stockanomaly1;AccountKey=O/zmEH0urLFXzD/RWyf0kXKTWwjIZbJ64zU+MfRepFFTj27oHR39A48elx9IdeOcYvWgWAtIa4k9+AStTgp5jQ==;EndpointSuffix=core.windows.net'
container_name = 'containerstock'
blob_name = "MSFT.csv"

def is_time_in_interval(start_time, end_time, test_override=False):
    if test_override: 
        return True
    current_time = datetime.now(timezone.utc).time()
    result = start_time <= current_time <= end_time
    return result


def fetch_new_data(api_key, symbol, last_date):
    ts = TimeSeries(key=api_key, output_format="pandas")
    data, _ = ts.get_daily(symbol=symbol, outputsize="full")
    data.reset_index(inplace=True)  # Convert index to a column
    data.rename(columns={"index": "Date"}, inplace=True)
    
    new_data = data[pd.to_datetime(data["date"]) > last_date]
    return new_data

def rename_columns(new_data):
    new_data = new_data.rename(columns={
        "date"   : "Date",
        "1. open": "Open",
        "2. high": "High",
        "3. low": "Low",
        "4. close": "Close",
        "5. volume": "Volume"
    })
    return new_data

def update_stock_data():
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)

        blob_stream = blob_client.download_blob().readall()
        data_blob = pd.read_csv(BytesIO(blob_stream), parse_dates=["Date"])
        last_date = data_blob["Date"].max()
        new_data = fetch_new_data(API_KEY, SYMBOL, last_date)
        
        if not new_data.empty:
            new_data = rename_columns(new_data)
            combined_data = pd.concat([data_blob, new_data], ignore_index=True)
            combined_data = combined_data.drop_duplicates(subset="Date", keep="last").sort_values("Date")
            blob_client.upload_blob(combined_data.to_csv(index=False), overwrite=True)
    except Exception as e:
        pass

START_TIME = time(10, 15)
END_TIME = time(10, 45)   

TEST_MODE = False

if is_time_in_interval(START_TIME, END_TIME, test_override=TEST_MODE):
    update_stock_data()


with open('MSFT_stocky.ipynb') as f:
    notebook_data = nbformat.read(f, as_version=4)

original_stdout = sys.stdout
sys.stdout = io.StringIO()

original_show = plt.show
original_print = builtins.print

def block_print(*args, **kwargs):
    pass

def block_show(*args, **kwargs):
    pass

builtins.print = block_print
plt.show = block_show

plt.ioff()

try:
    for cell in notebook_data['cells']:
        if cell['cell_type'] == 'code':
            code = cell['source']
            exec(code) 
            plt.close('all')
            
            # Check if an output CSV is generated by the code
            if "output.csv" in code:  
                print("Detected output.csv generation!")
                with open("output.csv", "rb") as data_file:
                    blob_client.upload_blob(data_file, timeout=600, overwrite=True)
            
    # Fall back to sys.stdout content upload if needed
    data = sys.stdout.getvalue().strip()
    if data:
        print("Captured stdout data. Uploading...")
        blob_client.upload_blob(data, timeout=600, overwrite=True)
    else:
        print("No stdout data captured.")
finally:
    sys.stdout = original_stdout
    builtins.print = original_print
    plt.show = original_show
    plt.ion()


# In[9]:


nest_asyncio.apply()


# In[10]:


app = FastAPI()


# In[11]:


class Features(BaseModel):
    Date: str
    Open: float
    High: float
    Low: float
    Close: float
    Adj_Close: float
    Volume: float
    PRV: float


# In[12]:


class MonthlyAnomaly(BaseModel):
    Month: str
    Anomalies: int
    Percentage_Change: float


# In[13]:


class Anomaly(BaseModel):
    Date: str
    Open: float
    Close: float
    High: float
    Low: float
    Anomaly: int


# In[14]:


templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# In[15]:


def load_data_from_blob():
    blob_name_new = "New_MSFT.csv"

    blob_service_client_new = BlobServiceClient.from_connection_string(connection_string)
    container_client_new = blob_service_client.get_container_client(container_name)
    blob_client_new = container_client_new.get_blob_client(blob_name_new)
    blob_stream_new = blob_client_new.download_blob().readall()
    return pd.read_csv(BytesIO(blob_stream_new), parse_dates=["Date"])


# In[16]:



@app.get("/anomalies", response_model=List[MonthlyAnomaly])
async def get_monthly_anomalies():
    df = load_data_from_blob()
    df["Date"] = pd.to_datetime(df["Date"])
    current_year = pd.Timestamp.now().year
    yearly_data = df[df["Date"].dt.year == current_year]

    yearly_data = yearly_data.copy()
    yearly_data["Month"] = yearly_data["Date"].dt.month
    monthly_anomalies = yearly_data.groupby("Month").agg(
        Anomalies=("Anomaly", "sum") 
    ).reset_index()
    
    months = pd.DataFrame({"Month": range(1, 13)})
    monthly_anomalies = months.merge(monthly_anomalies, on="Month", how="left").fillna(0)
    
    monthly_anomalies["Anomalies"] = monthly_anomalies["Anomalies"].astype(int)
    monthly_anomalies["Percentage_Change"] = (
        monthly_anomalies["Anomalies"]
            .pct_change()
            .replace([float('inf'), float('-inf')], 0)
            .fillna(0) * 100
    )
    
    monthly_anomalies["Month"] = monthly_anomalies["Month"].apply(
        lambda x: pd.Timestamp(year=current_year, month=x, day=1).strftime("%B")
    )

    return monthly_anomalies.to_dict(orient="records")


# In[17]:


def fetch_latest_anomalies(count: int = 28):
    df = load_data_from_blob()
    df['Date'] = pd.to_datetime(df['Date'])
    sorted_df = df.sort_values(by="Date", ascending=False)
    latest_data = sorted_df.head(count)
    anomalies = latest_data[["Date", "Open", "Close", "High", "Low","Anomaly"]].to_dict(orient="records")
    for anomaly in anomalies:
        anomaly["Date"] = anomaly["Date"].strftime("%Y-%m-%d")
    return anomalies


# In[18]:


@app.get("/latest_anomalies", response_class=JSONResponse)
async def latest_anomalies(count: int = 28):
    anomalies = fetch_latest_anomalies(count)
    return {"anomalies": anomalies}


# In[19]:


from datetime import datetime

@app.get("/monthly_statistics")
async def monthly_statistics():
    df = load_data_from_blob()
    now = datetime.now()
    current_year = now.year
    current_month = now.month
    df["Date"] = pd.to_datetime(df["Date"])
    current_month_data = df[
        (df["Date"].dt.year == current_year) & (df["Date"].dt.month == current_month)
    ]
    total_events = len(current_month_data)
    total_anomalies = len(current_month_data[current_month_data["Anomaly"] == 1])

    return {"total_events": total_events, "total_anomalies": total_anomalies}


# In[20]:


def fetch_last_day_statistics():
    df = load_data_from_blob()
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values(by="Date", ascending=False)
    
    last_day_data = df.iloc[0]
    is_anomaly = bool(last_day_data['Anomaly'] == 1)
    return {
        "date": last_day_data['Date'].strftime('%Y-%m-%d'),
        "open": last_day_data['Open'],
        "close": last_day_data['Close'],
        "high": last_day_data['High'],
        "low": last_day_data['Low'],
        "is_anomaly": is_anomaly
    }


# In[21]:


@app.get("/daily_statistic", response_class=JSONResponse)
async def daily_statistic():
    last_day_data = fetch_last_day_statistics()
    return last_day_data


# In[22]:


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    anomalies_list = fetch_latest_anomalies()
    return templates.TemplateResponse("dashboard.html", {"request": request, "anomalies": anomalies_list})


# In[23]:


def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)


# In[ ]:


run_fastapi()


# In[ ]:




