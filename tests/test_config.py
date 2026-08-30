from api.scraper import load_config


def test_configuration_separates_discovery_filters_signals_and_scoring():
    config = load_config()

    assert "profiles" not in config
    assert "scoring" not in config
    assert set(config) >= {
        "search",
        "hard_filters",
        "signals",
        "pre_score",
        "embeddings",
    }
    assert "legacy_scoring" not in config
    assert config["search"]["query_groups"]
    assert config["search"]["linkedin_fetch_description"] is False
    assert all(
        "weight" not in group and group["queries"]
        for group in config["search"]["query_groups"]
    )
    assert config["signals"]["role_terms"]
    assert config["signals"]["technologies"]
    technology_names = {
        definition["name"] for definition in config["signals"]["technologies"]
    }
    assert technology_names >= {
        "python",
        "power_platform",
        "power_automate",
        "n8n",
        "rest_api",
        "etl",
        "power_bi",
        "azure",
        "databricks",
        "sql",
    }
    assert sum(
        config["pre_score"][name]["max_score"]
        for name in ("seniority", "technologies", "role", "location")
    ) == 100
    assert config["embeddings"]["enabled"] is True
    assert config["embeddings"]["dimensions"] == 1024
    assert config["embeddings"]["title_weight"] == 0.4
    assert config["embeddings"]["description_weight"] == 0.6
