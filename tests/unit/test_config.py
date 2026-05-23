"""Tests for settings precedence: flag > env (GHR_*) > config file > default."""

from ghr.config import Settings, load_settings


def test_defaults_when_nothing_provided() -> None:
    s = load_settings(cli={}, env={}, config={})
    assert isinstance(s, Settings)
    assert s.default_limit == 30
    assert s.max_limit == 100
    assert s.cache_enabled is True
    assert s.half_life_days == 30.0


def test_config_file_overrides_default() -> None:
    assert load_settings(cli={}, env={}, config={"default_limit": 50}).default_limit == 50


def test_env_overrides_config_with_int_coercion() -> None:
    s = load_settings(cli={}, env={"GHR_DEFAULT_LIMIT": "75"}, config={"default_limit": 50})
    assert s.default_limit == 75


def test_flag_overrides_env_and_config() -> None:
    s = load_settings(
        cli={"default_limit": 10}, env={"GHR_DEFAULT_LIMIT": "75"}, config={"default_limit": 50}
    )
    assert s.default_limit == 10


def test_bool_env_coercion() -> None:
    off = load_settings(cli={}, env={"GHR_CACHE_ENABLED": "false"}, config={})
    on = load_settings(cli={}, env={"GHR_CACHE_ENABLED": "1"}, config={})
    assert off.cache_enabled is False
    assert on.cache_enabled is True


def test_float_field_coercion() -> None:
    assert load_settings(cli={}, env={}, config={"half_life_days": 14}).half_life_days == 14.0


def test_cli_none_does_not_override() -> None:
    s = load_settings(cli={"default_limit": None}, env={}, config={"default_limit": 42})
    assert s.default_limit == 42


def test_empty_env_string_ignored() -> None:
    s = load_settings(cli={}, env={"GHR_DEFAULT_LIMIT": ""}, config={"default_limit": 42})
    assert s.default_limit == 42


def test_weights_property_assembles_dict() -> None:
    s = load_settings(cli={"w_reactions": 2.0}, env={}, config={})
    assert s.weights == {"reactions": 2.0, "comments": 0.7, "recency": 1.5}
