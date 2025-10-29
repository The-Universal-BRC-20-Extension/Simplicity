#!/bin/bash

# Phase 8 Unisat API Comprehensive Test Script
# Run with: chmod +x test_api.sh && ./test_api.sh

BASE_URL="http://localhost:8080"
EXAMPLE_ADDRESS="bc1ptklkkhyu9v62as79uz0z03a628z04s9h0crxud29s95edrerch4qvut6ya"
SHORT_ADDRESS="bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}    Phase 8 Unisat API Comprehensive Test    ${NC}"
echo -e "${BLUE}===============================================${NC}"
echo -e "${CYAN}Base URL:${NC} $BASE_URL"
echo -e "${CYAN}Example Address:${NC} $EXAMPLE_ADDRESS"
echo -e "${CYAN}Short Address:${NC} $SHORT_ADDRESS"
echo -e "${CYAN}Test Start Time:${NC} $(date)"
echo

# Function to make detailed request and show result
test_endpoint() {
    local name="$1"
    local url="$2"
    local expected_status="$3"
    local extract="$4"
    local show_full="$5"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    echo -e "${PURPLE}🔍 Test $TOTAL_TESTS: $name${NC}"
    echo -e "${CYAN}URL:${NC} $url"
    echo -e "${CYAN}Expected Status:${NC} $expected_status"
    
    # Make request with timing and status code
    start_time=$(date +%s%3N)
    response=$(curl -s -w "HTTPSTATUS:%{http_code};TIME:%{time_total}" "$url" 2>/dev/null)
    end_time=$(date +%s%3N)
    
    # Extract HTTP status and timing
    http_code=$(echo "$response" | grep -o "HTTPSTATUS:[0-9]*" | cut -d: -f2)
    time_total=$(echo "$response" | grep -o "TIME:[0-9.]*" | cut -d: -f2)
    duration=$((end_time - start_time))
    
    # Extract actual response body
    response_body=$(echo "$response" | sed -E 's/HTTPSTATUS:[0-9]*;TIME:[0-9.]*$//')
    
    echo -e "${CYAN}Actual Status:${NC} $http_code"
    echo -e "${CYAN}Response Time:${NC} ${time_total}s (${duration}ms local)"
    
    # Check if request succeeded
    if [ -z "$http_code" ]; then
        echo -e "${RED}❌ FAILED: Request failed (connection error)${NC}"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo
        return 1
    fi
    
    # Check status code
    if [ "$http_code" != "$expected_status" ]; then
        echo -e "${RED}❌ FAILED: Expected status $expected_status, got $http_code${NC}"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    else
        echo -e "${GREEN}✅ PASSED: Correct status code${NC}"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    fi
    
    # Validate JSON and extract data
    if echo "$response_body" | jq . >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Valid JSON response${NC}"
        
        # Show full response if requested
        if [ "$show_full" = "true" ]; then
            echo -e "${YELLOW}📄 Full Response:${NC}"
            echo "$response_body" | jq .
        fi
        
        # Extract specific field if requested
        if [ -n "$extract" ]; then
            result=$(echo "$response_body" | jq -r "$extract" 2>/dev/null)
            if [ "$result" != "null" ] && [ -n "$result" ]; then
                echo -e "${CYAN}📊 Extracted Data ($extract):${NC} $result"
            else
                echo -e "${YELLOW}⚠️  Could not extract: $extract${NC}"
            fi
        fi
        
        # Show response structure
        echo -e "${CYAN}📋 Response Structure:${NC}"
        echo "$response_body" | jq 'keys' 2>/dev/null || echo "Not an object"
        
        # Show data array length if present
        if echo "$response_body" | jq -e '.data' >/dev/null 2>&1; then
            data_length=$(echo "$response_body" | jq '.data | length' 2>/dev/null)
            echo -e "${CYAN}📊 Data Array Length:${NC} $data_length"
        fi
        
    else
        echo -e "${RED}❌ Invalid JSON response${NC}"
        echo -e "${YELLOW}Raw Response:${NC} $response_body"
    fi
    
    echo -e "${BLUE}────────────────────────────────────────────────────────────${NC}"
    echo
}

# Function to test pagination
test_pagination() {
    local endpoint="$1"
    local name="$2"
    
    echo -e "${PURPLE}🔍 Pagination Test: $name${NC}"
    
    # Test different page sizes
    for size in 1 10 50 100 1000 2000; do
        echo -e "${CYAN}Testing size=$size:${NC}"
        start_time=$(date +%s%3N)
        response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$endpoint?size=$size" 2>/dev/null)
        end_time=$(date +%s%3N)
        duration=$((end_time - start_time))
        
        http_code=$(echo "$response" | grep -o "HTTPSTATUS:[0-9]*" | cut -d: -f2)
        response_body=$(echo "$response" | sed -E 's/HTTPSTATUS:[0-9]*$//')
        
        if [ "$http_code" = "200" ]; then
            actual_size=$(echo "$response_body" | jq -r '.size // "null"' 2>/dev/null)
            data_length=$(echo "$response_body" | jq '.data | length' 2>/dev/null)
            echo -e "  ${GREEN}✅${NC} Status: $http_code, Requested: $size, Actual: $actual_size, Items: $data_length, Time: ${duration}ms"
        else
            echo -e "  ${RED}❌${NC} Status: $http_code, Time: ${duration}ms"
        fi
    done
    echo
}

# Function to test performance
test_performance() {
    local url="$1"
    local name="$2"
    local iterations="${3:-5}"
    
    echo -e "${PURPLE}⚡ Performance Test: $name${NC}"
    echo -e "${CYAN}Running $iterations requests to:${NC} $url"
    
    local total_time=0
    local success_count=0
    
    for i in $(seq 1 $iterations); do
        start_time=$(date +%s%3N)
        response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$url" 2>/dev/null)
        end_time=$(date +%s%3N)
        duration=$((end_time - start_time))
        total_time=$((total_time + duration))
        
        http_code=$(echo "$response" | grep -o "HTTPSTATUS:[0-9]*" | cut -d: -f2)
        
        if [ "$http_code" = "200" ]; then
            success_count=$((success_count + 1))
            echo -e "  Request $i: ${GREEN}✅${NC} ${duration}ms"
        else
            echo -e "  Request $i: ${RED}❌${NC} Status $http_code, ${duration}ms"
        fi
    done
    
    avg_time=$((total_time / iterations))
    success_rate=$((success_count * 100 / iterations))
    
    echo -e "${CYAN}📊 Results:${NC}"
    echo -e "  Success Rate: ${success_rate}%"
    echo -e "  Average Time: ${avg_time}ms"
    echo -e "  Total Time: ${total_time}ms"
    echo
}

# Start tests
echo -e "${YELLOW}🚀 Starting API Tests...${NC}"
echo

# Test 1: Health Check (detailed)
test_endpoint "Health Check" \
    "$BASE_URL/v1/indexer/brc20/health" \
    "200" \
    ".status" \
    "true"

# Test 2: Get Tickers (comprehensive)
test_endpoint "Get All Tickers (first 5)" \
    "$BASE_URL/v1/indexer/brc20/tick?size=5" \
    "200" \
    ".total" \
    "true"

# Test 3: Get specific ticker - ORDI
test_endpoint "Get ORDI Ticker Info" \
    "$BASE_URL/v1/indexer/brc20/tick/ORDI" \
    "200" \
    ".tick" \
    "true"

# Test 4: Get specific ticker - OPQT
test_endpoint "Get OPQT Ticker Info" \
    "$BASE_URL/v1/indexer/brc20/tick/OPQT" \
    "200" \
    ".tick" \
    "false"

# Test 5: Get non-existent ticker
test_endpoint "Get Non-Existent Ticker" \
    "$BASE_URL/v1/indexer/brc20/tick/MISSING" \
    "404" \
    ".detail" \
    "false"

# Test 6: Get very long ticker (should be valid)
test_endpoint "Get Long Ticker (Valid Format)" \
    "$BASE_URL/v1/indexer/brc20/tick/VERYLONGTICKERNAMETHATSHOULDBEVALID" \
    "404" \
    ".detail" \
    "false"

# Test 7: Get ORDI holders
test_endpoint "Get ORDI Holders (first 10)" \
    "$BASE_URL/v1/indexer/brc20/tick/ORDI/holders?size=10" \
    "200" \
    ".total" \
    "false"

# Test 8: Get ORDI transactions
test_endpoint "Get ORDI Transactions (first 5)" \
    "$BASE_URL/v1/indexer/brc20/tick/ORDI/transactions?size=5" \
    "200" \
    ".total" \
    "false"

# Test 9: Get address balances (long address)
test_endpoint "Get Address Balances (Long Address)" \
    "$BASE_URL/v1/indexer/brc20/address/$EXAMPLE_ADDRESS" \
    "200" \
    ".total" \
    "false"

# Test 10: Get address balances (short address)
test_endpoint "Get Address Balances (Short Address)" \
    "$BASE_URL/v1/indexer/brc20/address/$SHORT_ADDRESS" \
    "200" \
    ".total" \
    "false"

# Test 11: Get address transactions
test_endpoint "Get Address Transactions" \
    "$BASE_URL/v1/indexer/brc20/address/$EXAMPLE_ADDRESS/transactions?size=5" \
    "200" \
    ".total" \
    "false"

# Test 12: Invalid address format
test_endpoint "Test Invalid Address Format" \
    "$BASE_URL/v1/indexer/brc20/address/invalid_address" \
    "400" \
    ".detail" \
    "false"

# Test 13: Empty address
test_endpoint "Test Empty Address" \
    "$BASE_URL/v1/indexer/brc20/address/" \
    "404" \
    "" \
    "false"

# Pagination Tests
echo -e "${YELLOW}📄 Running Pagination Tests...${NC}"
test_pagination "$BASE_URL/v1/indexer/brc20/tick" "Tickers Pagination"
test_pagination "$BASE_URL/v1/indexer/brc20/tick/ORDI/holders" "Holders Pagination"

# Performance Tests
echo -e "${YELLOW}⚡ Running Performance Tests...${NC}"
test_performance "$BASE_URL/v1/indexer/brc20/health" "Health Endpoint" 5
test_performance "$BASE_URL/v1/indexer/brc20/tick?size=10" "Tickers Endpoint" 3
test_performance "$BASE_URL/v1/indexer/brc20/tick/ORDI" "Single Ticker" 3

# Concurrent Request Test
echo -e "${PURPLE}🔄 Concurrent Request Test${NC}"
echo -e "${CYAN}Running 5 simultaneous requests to health endpoint...${NC}"
start_time=$(date +%s%3N)
for i in {1..5}; do
    curl -s "$BASE_URL/v1/indexer/brc20/health" >/dev/null 2>&1 &
done
wait
end_time=$(date +%s%3N)
concurrent_duration=$((end_time - start_time))
echo -e "${GREEN}✅ Completed in ${concurrent_duration}ms${NC}"
echo

# Cache Behavior Test
echo -e "${PURPLE}💾 Cache Behavior Test${NC}"
echo -e "${CYAN}Testing cache with repeated requests to ORDI endpoint...${NC}"
for i in {1..3}; do
    echo -n "Request $i: "
    start_time=$(date +%s%3N)
    result=$(curl -s "$BASE_URL/v1/indexer/brc20/tick/ORDI" 2>/dev/null | jq -r '.tick // "FAILED"')
    end_time=$(date +%s%3N)
    duration=$((end_time - start_time))
    if [ "$result" != "FAILED" ]; then
        echo -e "${GREEN}✅ $result${NC} (${duration}ms)"
    else
        echo -e "${RED}❌ FAILED${NC} (${duration}ms)"
    fi
done
echo

# Server Info Test
echo -e "${PURPLE}🖥️  Server Information Test${NC}"
server_info=$(curl -s -I "$BASE_URL/v1/indexer/brc20/health" 2>/dev/null)
if [ $? -eq 0 ]; then
    echo -e "${CYAN}Response Headers:${NC}"
    echo "$server_info" | grep -E "(Server|Content-Type|Date|Content-Length)" | sed 's/^/  /'
else
    echo -e "${RED}❌ Could not retrieve server headers${NC}"
fi
echo

# Final Summary
echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}              TEST SUMMARY                    ${NC}"
echo -e "${BLUE}===============================================${NC}"
echo -e "${CYAN}Test End Time:${NC} $(date)"
echo -e "${CYAN}Total Tests:${NC} $TOTAL_TESTS"
echo -e "${GREEN}Passed:${NC} $PASSED_TESTS"
echo -e "${RED}Failed:${NC} $FAILED_TESTS"

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}🎉 ALL TESTS PASSED!${NC}"
    success_rate=100
else
    success_rate=$((PASSED_TESTS * 100 / TOTAL_TESTS))
    echo -e "${YELLOW}⚠️  Some tests failed${NC}"
fi

echo -e "${CYAN}Success Rate:${NC} ${success_rate}%"
echo

# Additional Information
echo -e "${BLUE}📚 Additional Information:${NC}"
echo -e "${CYAN}• API Documentation:${NC} $BASE_URL/docs"
echo -e "${CYAN}• ReDoc Documentation:${NC} $BASE_URL/redoc"
echo -e "${CYAN}• For detailed API specs:${NC} See PHASE8_API_TESTS.md"
echo -e "${CYAN}• For production deployment:${NC} Update BASE_URL to production server"
echo

exit $FAILED_TESTS 