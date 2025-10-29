import time

from fastapi.testclient import TestClient


def test_endpoint_performance(client: TestClient):
    """Test that endpoints respond within acceptable time"""
    endpoints = ["/v1/indexer/brc20/list", "/v1/indexer/brc20/status"]

    for endpoint in endpoints:
        start_time = time.time()
        response = client.get(endpoint)
        end_time = time.time()

        assert response.status_code in [200, 404]
        assert (end_time - start_time) < 0.5


def test_ticker_endpoint_performance(client: TestClient):
    """Test ticker specific endpoints performance"""
    endpoints = [
        "/v1/indexer/brc20/ORDI/info",
        "/v1/indexer/brc20/ORDI/holders",
        "/v1/indexer/brc20/ORDI/history",
    ]

    for endpoint in endpoints:
        start_time = time.time()
        response = client.get(endpoint)
        end_time = time.time()

        assert response.status_code in [200, 404]
        assert (end_time - start_time) < 1.0


def test_address_endpoint_performance(client: TestClient):
    """Test address specific endpoints performance"""
    test_address = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
    endpoints = [
        f"/v1/indexer/address/{test_address}/history",
        f"/v1/indexer/address/{test_address}/brc20/ORDI/info",
    ]

    for endpoint in endpoints:
        start_time = time.time()
        response = client.get(endpoint)
        end_time = time.time()

        assert response.status_code in [200, 400, 404]
        assert (end_time - start_time) < 1.0


def test_pagination_performance(client: TestClient):
    """Test pagination endpoints performance"""
    endpoints = [
        "/v1/indexer/brc20/list?skip=0&limit=10",
        "/v1/indexer/brc20/list?skip=0&limit=100",
    ]

    for endpoint in endpoints:
        start_time = time.time()
        response = client.get(endpoint)
        end_time = time.time()

        assert response.status_code == 200
        assert (end_time - start_time) < 1.0


def test_concurrent_requests_performance(client: TestClient):
    """Test performance under concurrent requests"""
    import queue
    import threading

    results: queue.Queue[tuple[int, float]] = queue.Queue()

    def make_request():
        start_time = time.time()
        response = client.get("/v1/indexer/brc20/status")
        end_time = time.time()
        results.put((response.status_code, end_time - start_time))

    threads = []
    for i in range(10):
        thread = threading.Thread(target=make_request)
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    response_times = []
    while not results.empty():
        status_code, response_time = results.get()
        assert status_code == 200
        response_times.append(response_time)

    assert all(rt < 2.0 for rt in response_times)

    avg_response_time = sum(response_times) / len(response_times)
    assert avg_response_time < 1.0
