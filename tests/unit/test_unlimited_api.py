#!/usr/bin/env python3
"""
Test script for unlimited API endpoints
Tests all the new "get_all" endpoints to ensure they can return unlimited results
"""

import requests
import time
from typing import Dict, Optional


class UnlimitedAPITester:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.session = requests.Session()

    def test_endpoint(self, endpoint: str, params: Optional[Dict] = None, name: str = "") -> Dict:
        """Test an endpoint and return results"""
        url = f"{self.base_url}{endpoint}"

        print(f"🔍 Testing: {name or endpoint}")
        print(f"   URL: {url}")
        if params:
            print(f"   Params: {params}")

        start_time = time.time()
        try:
            response = self.session.get(url, params=params, timeout=30)
            duration = time.time() - start_time

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Status: {response.status_code}")
                print(f"   ⏱️  Duration: {duration:.2f}s")

                if isinstance(data, dict) and "total_count" in data:
                    # GetAllResponse format
                    print(f"   📊 Total: {data.get('total_count', 0)}")
                    print(f"   📊 Returned: {data.get('returned_count', 0)}")
                    print(f"   📊 Has More: {data.get('has_more', False)}")
                elif isinstance(data, list):
                    print(f"   📊 Items: {len(data)}")

                return {
                    "success": True,
                    "status_code": response.status_code,
                    "duration": duration,
                    "data": data,
                }
            else:
                print(f"   ❌ Status: {response.status_code}")
                print(f"   ❌ Error: {response.text}")
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "error": response.text,
                }

        except Exception as e:
            duration = time.time() - start_time
            print(f"   ❌ Exception: {str(e)}")
            return {"success": False, "error": str(e), "duration": duration}

    def test_all_endpoints(self):
        """Test all unlimited endpoints"""
        print("🚀 Testing Unlimited API Endpoints")
        print("=" * 60)

        results = {}

        # Test 1: Get all tickers
        results["all_tickers"] = self.test_endpoint("/v1/indexer/brc20/list/all", name="Get All Tickers")

        # Test 2: Get all tickers with limit
        results["all_tickers_limited"] = self.test_endpoint(
            "/v1/indexer/brc20/list/all",
            params={"max_results": 10},
            name="Get All Tickers (Limited to 10)",
        )

        # Test 3: Get all holders for a specific ticker
        results["all_holders"] = self.test_endpoint("/v1/indexer/brc20/ORDI/holders/all", name="Get All ORDI Holders")

        # Test 4: Get all history for a ticker
        results["all_ticker_history"] = self.test_endpoint(
            "/v1/indexer/brc20/ORDI/history/all", name="Get All ORDI History"
        )

        # Test 5: Get all history for a ticker with limit
        results["all_ticker_history_limited"] = self.test_endpoint(
            "/v1/indexer/brc20/ORDI/history/all",
            params={"max_results": 50},
            name="Get All ORDI History (Limited to 50)",
        )

        # Test 6: Get all history for an address
        results["all_address_history"] = self.test_endpoint(
            "/v1/indexer/address/bc1q544xqrx8mltjcaqky7mey6yayah2gjsyf6qenn/history/all",
            name="Get All Address History",
        )

        # Test 7: Get all history for an address with limit
        results["all_address_history_limited"] = self.test_endpoint(
            "/v1/indexer/address/bc1q544xqrx8mltjcaqky7mey6yayah2gjsyf6qenn/history/all",
            params={"max_results": 20},
            name="Get All Address History (Limited to 20)",
        )

        # Test 8: Get all history for a block height
        results["all_block_history"] = self.test_endpoint(
            "/v1/indexer/brc20/history-by-height/903000/all",
            name="Get All Block History",
        )

        # Test 9: Test regular endpoints with high limits
        results["regular_high_limit"] = self.test_endpoint(
            "/v1/indexer/brc20/list",
            params={"limit": 5000},
            name="Regular Endpoint with High Limit (5000)",
        )

        # Test 10: Test address history with high limit
        results["address_high_limit"] = self.test_endpoint(
            "/v1/indexer/address/bc1pz42whrh25gx0h755fv26x333dwjg4tyjtgjda27qcmrkwzu95d9q0hf0ff/history",
            params={"limit": 30000},
            name="Address History with High Limit (30000)",
        )

        return results

    def print_summary(self, results: Dict):
        """Print a summary of test results"""
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)

        successful_tests = 0
        total_tests = len(results)

        for test_name, result in results.items():
            if result.get("success"):
                successful_tests += 1
                print(f"✅ {test_name}: PASSED ({result.get('duration', 0):.2f}s)")
            else:
                print(f"❌ {test_name}: FAILED - {result.get('error', 'Unknown error')}")

        print(f"\n🎯 Results: {successful_tests}/{total_tests} tests passed")

        if successful_tests == total_tests:
            print("🎉 ALL TESTS PASSED! Unlimited API is working correctly.")
        else:
            print("⚠️  Some tests failed. Check the errors above.")

    def test_performance(self):
        """Test performance with different result sizes"""
        print("\n" + "=" * 60)
        print("⚡ PERFORMANCE TESTING")
        print("=" * 60)

        # Test different result sizes
        sizes = [100, 500, 1000, 5000, 10000]

        for size in sizes:
            result = self.test_endpoint(
                "/v1/indexer/brc20/list/all",
                params={"max_results": size},
                name=f"Performance Test - {size} results",
            )

            if result.get("success"):
                duration = result.get("duration", 0)
                print(f"   📈 {size} results: {duration:.2f}s ({size/duration:.0f} results/sec)")


def main():
    """Main test function"""
    print("🔧 Universal BRC-20 Indexer - Unlimited API Test")
    print("=" * 60)

    # Get base URL from user or use default
    base_url = input("Enter API base URL (default: http://localhost:8080): ").strip()
    if not base_url:
        base_url = "http://localhost:8080"

    tester = UnlimitedAPITester(base_url)

    # Test health endpoint first
    print("🏥 Testing health endpoint...")
    health_result = tester.test_endpoint("/v1/indexer/brc20/health", name="Health Check")

    if not health_result.get("success"):
        print("❌ Health check failed. Make sure the API is running.")
        return

    print("✅ Health check passed. Starting unlimited API tests...\n")

    # Run all tests
    results = tester.test_all_endpoints()

    # Print summary
    tester.print_summary(results)

    # Run performance tests
    tester.test_performance()

    print("\n🎯 Test completed!")


if __name__ == "__main__":
    main()
