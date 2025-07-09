#!/usr/bin/env python3
"""
Monitoring Validation Script
Tests monitoring and health checks before release as required.
"""

import asyncio
import json
import time
from typing import Dict
import httpx
import sys
import argparse


class MonitoringValidator:
    """Validates monitoring endpoints and performance before release."""

    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.client = httpx.AsyncClient()
        self.results: Dict[str, Dict] = {}

    async def validate_health_endpoints(self) -> bool:
        """Validate all health check endpoints for Simplicity Indexer."""
        print("🔍 Validating health endpoints...")

        health_endpoints = [
            "/v1/indexer/brc20/health",
            "/v1/indexer/brc20/status",
        ]

        all_healthy = True

        for endpoint in health_endpoints:
            url = f"{self.base_url}{endpoint}"
            try:
                response = await self.client.get(url)
                if response.status_code != 200:
                    print(f"❌ {endpoint}: HTTP {response.status_code}")
                    all_healthy = False
                    self.results[endpoint] = {
                        "status": "error",
                        "http_code": response.status_code,
                    }
                    continue

                data = response.json()

                if endpoint == "/v1/indexer/brc20/health":
                    # Accept both "ok" and "healthy" for maximum compatibility
                    status = data.get("status")
                    if status in ("ok", "healthy"):
                        print(f"✅ {endpoint}: healthy")
                        self.results[endpoint] = {
                            "status": "healthy",
                            "response_time": response.elapsed.total_seconds(),
                        }
                    else:
                        print(f"❌ {endpoint}: unexpected status ({status})")
                        all_healthy = False
                        self.results[endpoint] = {
                            "status": status,
                            "error": "unexpected_status",
                        }

                elif endpoint == "/v1/indexer/brc20/status":
                    # Expect: 3 integer fields
                    required_fields = [
                        "current_block_height_network",
                        "last_indexed_block_main_chain",
                        "last_indexed_brc20_op_block",
                    ]
                    missing = [
                        field
                        for field in required_fields
                        if field not in data or not isinstance(data[field], int)
                    ]
                    if not missing:
                        print(f"✅ {endpoint}: valid status")
                        self.results[endpoint] = {
                            "status": "healthy",
                            "response_time": response.elapsed.total_seconds(),
                        }
                    else:
                        missing_fields = ', '.join(missing)
                        print(f"\u274c {endpoint}: missing or invalid fields: "
                              f"{missing_fields}")
                        all_healthy = False
                        self.results[endpoint] = {
                            "status": "error",
                            "error": f"missing_or_invalid_fields: {missing_fields}",
                        }

            except Exception as exc:
                print(f"❌ {endpoint}: Connection or parsing error - {exc}")
                all_healthy = False
                self.results[endpoint] = {"status": "error", "error": str(exc)}

        return all_healthy

    async def validate_performance_requirements(self) -> bool:
        """Validate sub-20ms performance requirements."""
        print("⚡ Validating performance requirements...")

        test_endpoints = [
            "/v1/indexer/brc20/OPQT/info",
            "/v1/indexer/brc20/health",
        ]

        performance_passed = True

        for endpoint in test_endpoints:
            response_times = []

            # Test 10 requests
            for i in range(10):
                try:
                    start_time = time.time()
                    response = await self.client.get(f"{self.base_url}{endpoint}")
                    end_time = time.time()

                    response_time_ms = (end_time - start_time) * 1000
                    response_times.append(response_time_ms)

                    if response.status_code != 200:
                        print(f"❌ {endpoint}: HTTP {response.status_code}")
                        performance_passed = False

                except Exception as e:
                    print(f"❌ {endpoint}: Request failed - {e}")
                    performance_passed = False

            if response_times:
                avg_response_time = sum(response_times) / len(response_times)
                max_response_time = max(response_times)

                self.results[f"{endpoint}_performance"] = {
                    "average_ms": avg_response_time,
                    "max_ms": max_response_time,
                    "all_responses": response_times,
                }

                if avg_response_time < 20:
                    print(f"\u2705 {endpoint}: {avg_response_time:.2f}ms average "
                          f"(< 20ms requirement)")
                else:
                    print(f"\u274c {endpoint}: {avg_response_time:.2f}ms average "
                          f"(> 20ms requirement)")
                    performance_passed = False

                if max_response_time > 50:
                    print(
                        f"\u26a0\ufe0f  {endpoint}: {max_response_time:.2f}ms "
                        f"max response time"
                    )

        return performance_passed

    async def validate_api_endpoints(self) -> bool:
        """Validate core API endpoints functionality."""
        print("🔗 Validating API endpoints...")

        api_endpoints = [
            "/v1/indexer/brc20/OPQT/info",
            "/v1/indexer/brc20/health",
        ]

        all_working = True

        for endpoint in api_endpoints:
            try:
                response = await self.client.get(f"{self.base_url}{endpoint}")

                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"✅ {endpoint}: Valid JSON response")
                        self.results[f"{endpoint}_api"] = {
                            "status": "working",
                            "response_size": len(str(data)),
                        }
                    except json.JSONDecodeError:
                        print(f"❌ {endpoint}: Invalid JSON response")
                        all_working = False
                        self.results[f"{endpoint}_api"] = {
                            "status": "error",
                            "error": "invalid_json",
                        }
                else:
                    print(f"❌ {endpoint}: HTTP {response.status_code}")
                    all_working = False
                    self.results[f"{endpoint}_api"] = {
                        "status": "error",
                        "http_code": response.status_code,
                    }

            except Exception as e:
                print(f"❌ {endpoint}: Connection error - {e}")
                all_working = False
                self.results[f"{endpoint}_api"] = {"status": "error", "error": str(e)}

        return all_working

    async def validate_concurrent_load(self) -> bool:
        """Validate concurrent user handling."""
        print("👥 Validating concurrent load handling...")

        concurrent_requests = 20
        endpoint = "/v1/indexer/brc20/health"

        async def single_request():
            try:
                start_time = time.time()
                response = await self.client.get(f"{self.base_url}{endpoint}")
                end_time = time.time()

                return {
                    "status_code": response.status_code,
                    "response_time": (end_time - start_time) * 1000,
                    "success": response.status_code == 200,
                }
            except Exception as e:
                return {
                    "status_code": 0,
                    "response_time": 0,
                    "success": False,
                    "error": str(e),
                }

        # Run concurrent requests
        start_time = time.time()
        tasks = [single_request() for _ in range(concurrent_requests)]
        results = await asyncio.gather(*tasks)
        end_time = time.time()

        total_time = end_time - start_time
        successful_requests = sum(1 for r in results if r["success"])
        response_times = [r["response_time"] for r in results if r["success"]]

        success_rate = successful_requests / concurrent_requests * 100
        avg_response_time = (
            sum(response_times) / len(response_times) if response_times else 0
        )

        self.results["concurrent_load"] = {
            "total_requests": concurrent_requests,
            "successful_requests": successful_requests,
            "success_rate": success_rate,
            "total_time": total_time,
            "average_response_time": avg_response_time,
        }

        if success_rate >= 95:
            print(f"\u2705 Concurrent load: {success_rate:.1f}% success rate "
                  f"({successful_requests}/{concurrent_requests})")
            print(f"✅ Average response time: {avg_response_time:.2f}ms")
            return True
        else:
            print(f"\u274c Concurrent load: {success_rate:.1f}% success rate "
                  f"({successful_requests}/{concurrent_requests})")
            return False

    async def run_all_validations(self) -> bool:
        """Run all validation tests."""
        print("🚀 Starting monitoring validation for release...")
        print("=" * 50)

        validations = [
            ("Health Endpoints", self.validate_health_endpoints),
            ("Performance Requirements", self.validate_performance_requirements),
            ("API Endpoints", self.validate_api_endpoints),
            ("Concurrent Load", self.validate_concurrent_load),
        ]

        all_passed = True

        for name, validation_func in validations:
            print(f"\n📋 {name}")
            print("-" * 30)

            try:
                result = await validation_func()
                if not result:
                    all_passed = False
            except Exception as e:
                print(f"❌ {name}: Validation failed - {e}")
                all_passed = False

        print("\n" + "=" * 50)

        if all_passed:
            print("✅ All monitoring validations passed! Ready for release.")
        else:
            print("❌ Some validations failed. Please fix issues before release.")

        return all_passed

    async def generate_report(self) -> str:
        """Generate a detailed monitoring report."""
        report = {
            "timestamp": time.time(),
            "summary": {
                "total_tests": len(self.results),
                "passed_tests": sum(
                    1
                    for r in self.results.values()
                    if r.get("status") in ["healthy", "working"]
                ),
            },
            "detailed_results": self.results,
        }

        return json.dumps(report, indent=2)

    async def cleanup(self):
        """Cleanup resources."""
        await self.client.aclose()


async def main():
    """Main function to run monitoring validation."""
    parser = argparse.ArgumentParser(description="Validate monitoring before release")
    parser.add_argument(
        "--url", default="http://localhost:8080", help="Base URL for the indexer"
    )
    parser.add_argument("--report", help="Save detailed report to file")
    parser.add_argument(
        "--exit-on-fail",
        action="store_true",
        help="Exit with error code if validation fails",
    )

    args = parser.parse_args()

    validator = MonitoringValidator(args.url)

    try:
        # Run all validations
        all_passed = await validator.run_all_validations()

        # Generate report if requested
        if args.report:
            report = await validator.generate_report()
            with open(args.report, "w") as f:
                f.write(report)
            print(f"📄 Detailed report saved to {args.report}")

        # Exit with appropriate code
        if args.exit_on_fail and not all_passed:
            sys.exit(1)
        elif all_passed:
            print("\n🎉 Monitoring validation completed successfully!")
            sys.exit(0)
        else:
            print("\n⚠️  Monitoring validation completed with warnings.")
            sys.exit(0)

    except KeyboardInterrupt:
        print("\n⏹️  Monitoring validation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Monitoring validation failed: {e}")
        sys.exit(1)
    finally:
        await validator.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
