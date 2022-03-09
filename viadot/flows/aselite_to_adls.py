from typing import Any, Dict, List, Literal
from prefect import Flow
from viadot.tasks import AzureDataLakeUpload
from viadot.task_utils import df_to_csv, df_converts_bytes_to_int
from viadot.tasks.aselite import ASELiteToDF


df_task = ASELiteToDF()
file_to_adls_task = AzureDataLakeUpload()


class ASELitetoADLS(Flow):
    def __init__(
        self,
        name: str,
        query: str = None,
        sqldb_credentials_secret: str = None,
        vault_name: str = None,
        file_path: str = "None",
        sep: str = "\t",
        to_path: str = None,
        if_exists: Literal["replace", "append", "delete"] = "replace",
        overwrite: bool = True,
        convert_bytes: bool = False,
        *args: List[any],
        **kwargs: Dict[str, Any]
    ):
        """
        Flow for downloading data from ASElite to csv file, then uploading it to Azure Storage Explorer.

        Args:
            name (str): The name of the flow.
            query (str): Query to perform on a database. Defaults to None.
            sqldb_credentials_secret (str, optional): The name of the Azure Key Vault secret containing a dictionary with
            ASElite SQL Database credentials. Defaults to None.
            vault_name (str, optional): The name of the vault from which to obtain the secrets. Defaults to None.
            file_path (str, optional): Local destination path. Defaults to None.
            sep (str, optional): The delimiter for the output CSV file. Defaults to "\t".
            to_path (str): The path to an ADLS file. Defaults to None.
            if_exists (Literal, optional): What to do if the table exists. Defaults to "replace".
            overwrite (str, optional): Whether to overwrite the destination file. Defaults to True.
        """
        self.query = query
        self.sqldb_credentials_secret = sqldb_credentials_secret
        self.vault_name = vault_name
        self.overwrite = overwrite

        self.file_path = file_path
        self.sep = sep
        self.to_path = to_path
        self.if_exists = if_exists
        self.convert_bytes = convert_bytes

        super().__init__(*args, name=name, **kwargs)

        self.gen_flow()

    def gen_flow(self) -> Flow:
        df = df_task.bind(
            query=self.query,
            credentials_secret=self.sqldb_credentials_secret,
            vault_name=self.vault_name,
            flow=self,
        )

        if self.convert_bytes == True:
            df = df_converts_bytes_to_int.bind(df, flow=self)

        create_csv = df_to_csv.bind(
            df,
            path=self.file_path,
            sep=self.sep,
            if_exists=self.if_exists,
            flow=self,
        )

        adls_upload = file_to_adls_task.bind(
            from_path=self.file_path,
            to_path=self.to_path,
            overwrite=self.overwrite,
            flow=self,
        )

        create_csv.set_upstream(df, flow=self)
        adls_upload.set_upstream(create_csv, flow=self)