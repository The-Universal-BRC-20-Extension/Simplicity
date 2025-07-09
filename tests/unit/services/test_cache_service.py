import pytest
from unittest.mock import patch, MagicMock
from src.services.cache_service import CacheService
from src.utils.logging import setup_logging

setup_logging()


@pytest.fixture
def mock_redis(monkeypatch):
    mock_client = MagicMock()
    with patch("redis.Redis", return_value=mock_client):
        yield mock_client


def test_get_cache_hit(mock_redis):
    service = CacheService()
    mock_redis.get.return_value = '{"foo": "bar"}'
    result = service.get("key1")
    assert result == {"foo": "bar"}
    mock_redis.get.assert_called_once_with("key1")


def test_get_cache_miss(mock_redis):
    service = CacheService()
    mock_redis.get.return_value = None
    result = service.get("key2")
    assert result is None
    mock_redis.get.assert_called_once_with("key2")


def test_get_cache_error(mock_redis, caplog):
    service = CacheService()
    mock_redis.get.side_effect = Exception("fail")
    with caplog.at_level("ERROR"):
        result = service.get("key3")
    assert result is None
    assert "Cache get failed" in caplog.text


def test_set_cache_success(mock_redis):
    service = CacheService()
    mock_redis.setex.return_value = True
    result = service.set("key4", {"a": 1}, ttl=100)
    assert result is True
    mock_redis.setex.assert_called_once()
    args, kwargs = mock_redis.setex.call_args
    assert args[0] == "key4"
    assert args[1] == 100
    assert "a" in args[2]


def test_set_cache_error(mock_redis, caplog):
    service = CacheService()
    mock_redis.setex.side_effect = Exception("fail")
    with caplog.at_level("ERROR"):
        result = service.set("key5", {"b": 2}, ttl=50)
    assert result is False
    assert "Cache set failed" in caplog.text


def test_delete_cache_success(mock_redis):
    service = CacheService()
    mock_redis.delete.return_value = 1
    result = service.delete("key6")
    assert result is True
    mock_redis.delete.assert_called_once_with("key6")


def test_delete_cache_miss(mock_redis):
    service = CacheService()
    mock_redis.delete.return_value = 0
    result = service.delete("key7")
    assert result is False
    mock_redis.delete.assert_called_once_with("key7")


def test_delete_cache_error(mock_redis, caplog):
    service = CacheService()
    mock_redis.delete.side_effect = Exception("fail")
    with caplog.at_level("ERROR"):
        result = service.delete("key8")
    assert result is False
    assert "Cache delete failed" in caplog.text


def test_generate_key():
    service = CacheService()
    key = service.generate_key("prefix", 1, "foo", 3)
    assert key == "prefix:1_foo_3"
