from viadot.flows import SAPRFCToADLS
from viadot.config import local_config
from viadot.sources import AzureDataLake

ADLS_PATH = "raw/supermetrics/mp/test_file_sap.parquet"


def test_sap_rfc_to_adls():
    sap_test_creds = local_config.get("SAP").get("QA")
    flow = SAPRFCToADLS(
        name="test flow",
        queries=[
            "SELECT MATNR, MATKL FROM MARA WHERE LAEDA LIKE '2022%'",
            "SELECT MTART, LAEDA FROM MARA WHERE LAEDA LIKE '2022%'",
        ],
        func="BBP_RFC_READ_TABLE",
        sap_credentials=sap_test_creds,
        local_file_path="test_file.parquet",
        adls_path=ADLS_PATH,
        overwrite=True,
    )
    result = flow.run()
    assert result.is_successful()
    file = AzureDataLake(ADLS_PATH)
    assert file.exists()