from api.scraper import load_config


def test_configuration_separates_discovery_filters_signals_and_scoring():
    config = load_config()

    assert "profiles" not in config
    assert "scoring" not in config
    assert set(config) >= {
        "search",
        "hard_filters",
        "signals",
        "legacy_scoring",
    }
    assert config["search"]["query_groups"]
    assert all(
        "weight" not in group and group["queries"]
        for group in config["search"]["query_groups"]
    )
    assert config["signals"]["role_terms"]
    assert config["signals"]["technologies"]
    technology_terms = {
        term
        for group in config["signals"]["technologies"]
        for term in group["terms"]
    }
    assert technology_terms >= {
        "python",
        "power platform",
        "power automate",
        "n8n",
        "rest api",
        "etl",
        "power bi",
        "azure",
        "databricks",
        "sql",
    }
