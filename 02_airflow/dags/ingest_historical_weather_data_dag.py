import os
import json
import logging
import decimal
import requests
from datetime import date, datetime
import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.task_group import TaskGroup

from google.cloud import storage
from airflow.providers.google.cloud.operators.bigquery import BigQueryCreateExternalTableOperator, BigQueryInsertJobOperator
# import pyarrow.csv as pv
# import pyarrow.parquet as pq

from gcloud_helpers import upload_to_gcs


PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
BUCKET = os.environ.get("GCP_GCS_BUCKET")
BIGQUERY_DATASET = 'energy_data'
EIA_API_KEY = os.environ.get("EIA_API_KEY")
AIRFLOW_HOME = os.environ.get("AIRFLOW_HOME", "/opt/airflow/")

LOCAL_DATASET_FILE_SUFFIX= "{{ execution_date.strftime(\'%Y-%m-%d-%H\') }}"
REMOTE_DATASET_FILE_SUFFIX = "{{ execution_date.strftime(\'%Y-%m-%d\') }}" 

YEAR = "{{ execution_date.strftime(\'%Y\') }}"

def extract_historical_weather_data(csv):
    station_data = pd.read_csv(csv)

    station_data[['temperature_degC', 'temperature_QC']] = station_data['TMP'].str.split(',', expand=True)
    station_data[['dew_point_degC', 'dew_point_QC']] = station_data['DEW'].str.split(',', expand=True)

    station_data = (station_data
                    .astype({'temperature_degC': float, 'dew_point_degC': float})
                    .assign(temperature_degC=lambda df_: (df_['temperature_degC'] / 10).replace(999.9, np.nan),
                            dew_point_degC=lambda df_: (df_['dew_point_degC'] / 10).replace(999.9, np.nan),
                    )
                )
    
    columns = ['STATION', 'NAME', 'DATE', 'temperature_degC', 'dew_point_degC', 'temperature_QC', 'dew_point_QC']
    station_data[columns].to_parquet(f"{AIRFLOW_HOME}/{station_id}.parquet")


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
}

station_ids = ['72565003017']

with DAG(
    dag_id="historical_weather_dag",
    schedule_interval="@daily",
    default_args=default_args,
    start_date=datetime(2015, 1, 1),
    catchup=True,
    max_active_runs=1,
    tags=['dtc-de', 'weather'],
) as dag:
    with TaskGroup(group_id='download_and_extract') as dl_and_extract_tg:
        for station_id in station_ids: 

            download_task = BashOperator(
                        task_id=f"download_weather_{station_id}_task",
                        bash_command=f'curl https://noaa-global-hourly-pds.s3.amazonaws.com/{YEAR}/{station_id}.csv -o {AIRFLOW_HOME}/{station_id}.csv'
                    )

            local_raw_to_gcs_task = PythonOperator(
                        task_id=f"local_raw_to_gcs_{station_id}_task",
                        python_callable=upload_to_gcs,
                        op_kwargs={
                            "bucket": BUCKET,
                            "object_name": f"raw/weather_station/{YEAR}/{station_id}.csv",
                            "local_file": f"{AIRFLOW_HOME}/{station_id}.csv",
                        }
                    )

            extract_data_task = PythonOperator(
                    task_id=f"extract_weather_station_data_task_{station_id}",
                    python_callable=extract_historical_weather_data,
                    op_kwargs={
                        "csv": f"{AIRFLOW_HOME}/{station_id}.csv",
                    }
                )

            local_extracted_to_gcs_task = PythonOperator(
                    task_id=f"local_extracted_to_gcs_{station_id}_task",
                    python_callable=upload_to_gcs,
                    op_kwargs={
                        "bucket": BUCKET,
                        "object_name": f"staged/weather_station/{YEAR}/{station_id}.parquet",
                        "local_file": f"{AIRFLOW_HOME}/{station_id}.parquet",
                    }
                )

            cleanup_task = BashOperator(
                task_id=f"cleanup_{station_id}_task",
                bash_command=f'rm {AIRFLOW_HOME}/{station_id}.csv {AIRFLOW_HOME}/{station_id}.parquet'
            )
            
            download_task >> local_raw_to_gcs_task >> extract_data_task >> local_extracted_to_gcs_task >> cleanup_task

    gcs_to_bq_ext_task = BigQueryCreateExternalTableOperator(
            task_id=f"gcs_to_bq_ext_weather_task",
            table_resource={
                "tableReference": {
                    "projectId": PROJECT_ID,
                    "datasetId": BIGQUERY_DATASET,
                    "tableId": f'{YEAR}_weather_station_external',
                },
                "externalDataConfiguration": {
                    "sourceFormat": "PARQUET",
                    "sourceUris": [f"gs://{BUCKET}/staged/weather_station/{YEAR}/*"],
                },
            },
        )

    CREATE_NATIVE_TABLE_QUERY = f"""CREATE OR REPLACE TABLE {BIGQUERY_DATASET}.{YEAR}_weather_station_native
                            AS SELECT * FROM {BIGQUERY_DATASET}.{YEAR}_weather_station_external;"""

    create_native_bq_table_task = BigQueryInsertJobOperator(
        task_id=f"bq_ext_to_native_task",
        configuration={
            "query": {
                "query": CREATE_NATIVE_TABLE_QUERY,
                "useLegacySql": False,
            }
        },
    )

    dl_and_extract_tg >> gcs_to_bq_ext_task >> create_native_bq_table_task
