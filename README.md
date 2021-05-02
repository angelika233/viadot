# Viadot
<p>
<a href="https://github.com/psf/black" target="_blank">
    <img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Build">
</a>
</p>

---

**Documentation**: <a href="https://dyvenia.github.io/viadot/" target="_blank">https://dyvenia.github.io/viadot/</a>

**Source Code**: <a href="https://github.com/dyvenia/viadot" target="_blank">https://github.com/dyvenia/viadot</a>

---

A simple data ingestion library to guide data flows from some places to other places

## Getting Data from a Source

viadot supports few sources. For instance, the UK Carbon Intensity API does not require credentials.

```python
from viadot.sources.uk_carbon_intensity import UKCarbonIntensity
ukci = UKCarbonIntensity()
ukci.query("/intensity")
ukci.to_df()
```

The above code pulls the UK Carbon Insentity data from the external API to the local Pandas dataframe (df).

## Loading Data to a Source

TODO

## Running tests
```
run.sh
docker exec -it viadot_testing bash
cd tests/ && pytest .
```

## Running flows locally
```
run.sh
poetry shell
FLOW_NAME=supermetrics_to_azure_sql; python -m viadot.flows.$FLOW_NAME
```

## Uploading pkg to PyPi

Generate the `requirements.txt` file from poetry.

```bash
poetry export -f requirements.txt --output requirements.txt --with-credentials --dev
```

And then publish with poetry.

```bash
poetry update
poetry publish --build
```
