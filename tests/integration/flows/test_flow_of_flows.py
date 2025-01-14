import pytest
from unittest import mock
from viadot.flows import Pipeline
from prefect.engine.state import Success
from prefect.engine.state import State


def test_pipeline_init():
    instance = Pipeline(
        "test_pipeline_flow",
        project_name="example_project",
        extract_flows_names=["flow1_extract", "flow2_load"],
        transform_flow_name="flow1_extract",
    )
    assert instance


def test_pipeline_flow_run_mock():
    with mock.patch.object(Pipeline, "run", return_value=Success) as mock_method:

        instance = Pipeline(
            "test_pipeline_flow",
            project_name="example_project",
            extract_flows_names=["flow1_extract", "flow2_load"],
            transform_flow_name="flow1_extract",
        )
        result = instance.run()
        assert result
