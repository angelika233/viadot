import os
from typing import Any, Dict, List, Union

import pandas as pd
from visions.functional import infer_type
from visions.typesets.complete_set import CompleteSet

from prefect import Flow, Task, apply_map, task, Parameter
from prefect.storage import Git, GitHub, Local
from prefect.tasks.control_flow import case
from prefect.tasks.secrets import PrefectSecret
from prefect.utilities import logging
from prefect.backend import get_key_value


from ..task_utils import METADATA_COLUMNS, add_ingestion_metadata_task
from ..tasks import (
    AzureDataLakeUpload,
    AzureSQLCreateTable,
    BCPTask,
    DownloadGitHubFile,
    RunGreatExpectationsValidation,
    AzureDataLakeToDF,
    AzureDataLakeCopy,
)

logger = logging.get_logger(__name__)

lake_to_df_task = AzureDataLakeToDF()
download_github_file_task = DownloadGitHubFile()
validation_task = RunGreatExpectationsValidation()
promote_to_conformed_task = AzureDataLakeUpload()
promote_to_operations_task = AzureDataLakeCopy()
create_table_task = AzureSQLCreateTable()
bulk_insert_task = BCPTask()


@task
def union_dfs_task(dfs: List[pd.DataFrame]):
    return pd.concat(dfs, ignore_index=True)


@task
def df_get_data_types_task(df):
    typeset = CompleteSet()
    dtypes = infer_type(df, typeset)
    return dtypes


@task
def df_to_csv_task(df, path: str, sep: str = "\t"):
    df.to_csv(path, sep=sep, index=False)


@task
def is_stored_locally(f: Flow):
    return f.storage is None or isinstance(f.storage, Local)


class ADLSToAzureSQL(Flow):
    def __init__(
        self,
        name: str,
        expectation_suite_name: str = "failure",
        local_file_path: str = None,
        adls_path: str = None,
        sep: str = "\t",
        overwrite_adls: bool = True,
        if_empty: str = "warn",
        adls_sp_credentials_secret: str = None,
        table: str = None,
        schema: str = None,
        if_exists: str = "replace",  # this applies to the full CSV file, not per chunk
        sqldb_credentials_secret: str = None,
        max_download_retries: int = 5,
        tags: List[str] = ["promotion"],
        vault_name: str = None,
        *args: List[any],
        **kwargs: Dict[str, Any],
    ):
        """
        Flow for downloading data from different marketing APIs to a local CSV
        using Supermetrics API, then uploading it to Azure Data Lake,
        and finally inserting into Azure SQL Database.

        Args:
            name (str): The name of the flow.
            expectation_suite_name (str, optional): The name of the expectation suite. Defaults to "failure".
            Currently, only GitHub URLs are supported. Defaults to None.
            local_file_path (str, optional): Local destination path. Defaults to None.
            adls_path (str): The path to an ADLS folder or file. If you pass a path to a directory,
            the latest file from that directory will be loaded. We assume that the files are named using timestamps.
            sep (str, optional): The separator to use in the CSV. Defaults to "\t".
            overwrite_adls (bool, optional): Whether to overwrite the file in ADLS. Defaults to True.
            if_empty (str, optional): What to do if the Supermetrics query returns no data. Defaults to "warn".
            adls_sp_credentials_secret (str, optional): The name of the Azure Key Vault secret containing a dictionary with
            ACCOUNT_NAME and Service Principal credentials (TENANT_ID, CLIENT_ID, CLIENT_SECRET) for the Azure Data Lake.
            Defaults to None.
            table (str, optional): Destination table. Defaults to None.
            schema (str, optional): Destination schema. Defaults to None.
            if_exists (str, optional): What to do if the table exists. Defaults to "replace".
            sqldb_credentials_secret (str, optional): The name of the Azure Key Vault secret containing a dictionary with
            Azure SQL Database credentials. Defaults to None.
            max_download_retries (int, optional): How many times to retry the download. Defaults to 5.
            tags (List[str], optional): Flow tags to use, eg. to control flow concurrency. Defaults to ["promotion"].
            vault_name (str, optional): The name of the vault from which to obtain the secrets. Defaults to None.
        """
        adls_path = adls_path.strip("/")

        # Read parquet file from raw
        if adls_path.split(".")[-1] in ["csv", "parquet"]:
            self.path = adls_path
        else:
            self.path = get_key_value(key=adls_path)

        #

        # RunGreatExpectationsValidation

        # AzureDataLakeUpload
        self.local_file_path = local_file_path or self.slugify(name) + ".csv"
        self.sep = sep
        self.overwrite_adls = overwrite_adls
        self.if_empty = if_empty
        self.adls_sp_credentials_secret = adls_sp_credentials_secret
        self.adls_path = adls_path
        self.adls_path_conformed = self.get_promoted_path(adls_path)
        self.adls_path_operations = self.get_promoted_path(adls_path, env="operations")

        # BCPTask
        self.table = table
        self.schema = schema
        # self.dtypes = dtypes or {}
        self.if_exists = if_exists
        self.sqldb_credentials_secret = sqldb_credentials_secret

        # Global
        self.max_download_retries = max_download_retries
        self.tags = tags
        self.vault_name = vault_name

        super().__init__(*args, name=name, **kwargs)

        # DownloadGitHubFile (download expectations)
        self.expectation_suite_name = expectation_suite_name
        self.expectation_suite_file_name = expectation_suite_name + ".json"
        self.expectation_suite_path = self._get_expectation_suite_path()
        self.expectation_suite_local_path = os.path.join(
            os.getcwd(), "expectations", self.expectation_suite_file_name
        )
        self.storage_repo = self._get_expectation_suite_repo()

        # self.dtypes.update(METADATA_COLUMNS)
        self.gen_flow()

    @staticmethod
    def slugify(name):
        return name.replace(" ", "_").lower()

    def get_promoted_path(self, env: str = "conformed") -> str:
        adls_path_clean = self.adls_path.strip("/")

        extension = adls_path_clean.split(".")[-1]
        if extension in ["csv", "parquet"]:
            file_name = adls_path_clean.split("/")[-2] + ".csv"
            common_path = "/".join(adls_path_clean.split("/")[1:-2])
        else:
            file_name = adls_path_clean.split("/")[-1] + ".csv"
            common_path = "/".join(adls_path_clean.split("/")[1:-1])

        promoted_path = os.path.join(env, common_path, file_name)

        return promoted_path

    def _get_expectation_suite_repo(self):
        if self.storage is None or isinstance(self.storage, Local):
            return None
        return self.storage.repo

    def _get_expectation_suite_path(self):

        if self.storage is None:
            return os.path.join(os.getcwd(), self.expectation_suite_file_name)

        elif isinstance(self.storage, GitHub):
            path = self.storage.path
        elif isinstance(self.storage, Git):
            # assuming this is DevOps
            path = self.storage.flow_path
        elif isinstance(self.storage, Local):
            path = self.storage.directory
        else:
            try:
                path = self.storage.path
            except AttributeError:
                raise NotImplemented("Unsupported storage type.")

        flow_dir_path = path[: path.rfind("/")]
        return os.path.join(
            flow_dir_path, "expectations", self.expectation_suite_file_name
        )

    def gen_flow(self) -> Flow:
        adls_raw_file_path = Parameter("adls_raw_file_path", default=self.path)

        df = lake_to_df_task.bind(path=adls_raw_file_path, flow=self)

        dtypes = df_get_data_types_task.bind(df, flow=self)

        validation = validation_task.bind(
            df=df,
            expectations_path=os.getcwd(),
            expectation_suite_name=self.expectation_suite_name,
            flow=self,
        )

        local = is_stored_locally.bind(self, flow=self)
        with case(local, True):
            pass_the_other_case = True
        if not pass_the_other_case:
            with case(local, False):
                download_expectations = download_github_file_task.bind(
                    repo=self.storage_repo,
                    from_path=self.expectation_suite_path,
                    to_path=self.expectation_suite_local_path,
                    flow=self,
                )
                validation.set_upstream(download_expectations, flow=self)

        df_to_csv = df_to_csv_task.bind(
            df=df,
            path=self.local_file_path,
            sep=self.sep,
            flow=self,
        )

        promote_to_conformed_task.bind(
            from_path=self.local_file_path,
            to_path=self.adls_path_conformed,
            overwrite=self.overwrite_adls,
            sp_credentials_secret=self.adls_sp_credentials_secret,
            vault_name=self.vault_name,
            flow=self,
        )
        promote_to_operations_task.bind(
            from_path=self.adls_path_conformed,
            to_path=self.adls_path_operations,
            overwrite=self.overwrite_adls,
            sp_credentials_secret=self.adls_sp_credentials_secret,
            vault_name=self.vault_name,
            flow=self,
        )
        create_table_task.bind(
            schema=self.schema,
            table=self.table,
            dtypes=dtypes,
            if_exists=self.if_exists,
            credentials_secret=self.sqldb_credentials_secret,
            vault_name=self.vault_name,
            flow=self,
        )
        bulk_insert_task.bind(
            path=self.local_file_path,
            schema=self.schema,
            table=self.table,
            credentials_secret=self.sqldb_credentials_secret,
            vault_name=self.vault_name,
            flow=self,
        )

        df_to_csv.set_upstream(validation, flow=self)

        promote_to_conformed_task.set_upstream(df_to_csv, flow=self)
        df_get_data_types_task.set_upstream(lake_to_df_task, flow=self)
        create_table_task.set_upstream(validation, flow=self)
        bulk_insert_task.set_upstream(create_table_task, flow=self)
