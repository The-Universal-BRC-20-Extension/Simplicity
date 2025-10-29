#!/bin/bash

BASE_URL="http://localhost:8080"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  Testing /list Endpoint Modification  ${NC}"
echo -e "${BLUE}======================================${NC}"
echo -e "${CYAN}Base URL:${NC} $BASE_URL"
echo -e "${CYAN}Test Time:${NC} $(date)"
echo

test_endpoint() {
    local name="$1"
    local url="$2"
    local expected_status="$3"
    
    echo -e "${YELLOW}🔍 Test: $name${NC}"
    echo -e "${CYAN}URL:${NC} $url"
    
    start_time=$(date +%s%3N)
    response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$url" 2>/dev/null)
    end_time=$(date +%s%3N)
    duration=$((end_time - start_time))
    
    http_code=$(echo "$response" | grep -o "HTTPSTATUS:[0-9]*" | cut -d: -f2)
    response_body=$(echo "$response" | sed -E 's/HTTPSTATUS:[0-9]*$//')
    
    echo -e "${CYAN}Status Code:${NC} $http_code"
    echo -e "${CYAN}Response Time:${NC} ${duration}ms"
    
    if [ -z "$http_code" ]; then
        echo -e "${RED}❌ FAILED: Request failed (connection error)${NC}"
        echo -e "${RED}   Is the API server running? Try: cd ubrc20-indexer && python run.py${NC}"
        return 1
    fi
    
    if [ "$http_code" != "$expected_status" ]; then
        echo -e "${RED}❌ FAILED: Expected status $expected_status, got $http_code${NC}"
        if [ "$http_code" = "404" ]; then
            echo -e "${RED}   Endpoint not found - modification may not be applied yet${NC}"
        fi
    else
        echo -e "${GREEN}✅ PASSED: Correct status code${NC}"
    fi
    
    if echo "$response_body" | jq . >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Valid JSON response${NC}"
        
        total=$(echo "$response_body" | jq -r '.total // "N/A"' 2>/dev/null)
        data_length=$(echo "$response_body" | jq '.data | length' 2>/dev/null)
        
        echo -e "${CYAN}📊 Total Items:${NC} $total"
        echo -e "${CYAN}📊 Returned Items:${NC} $data_length"
        
        first_ticker=$(echo "$response_body" | jq -r '.data[0].tick // "N/A"' 2>/dev/null)
        if [ "$first_ticker" != "N/A" ] && [ "$first_ticker" != "null" ]; then
            echo -e "${CYAN}📊 First Ticker:${NC} $first_ticker"
        fi
        
    else
        echo -e "${RED}❌ Invalid JSON response${NC}"
        echo -e "${YELLOW}Raw Response (first 200 chars):${NC} ${response_body:0:200}..."
    fi
    
    echo -e "${BLUE}────────────────────────────────────────${NC}"
    echo
}

echo -e "${YELLOW}🚀 Starting /list Endpoint Tests...${NC}"
echo

echo -e "${CYAN}Step 1: Verify API is running${NC}"
test_endpoint "Health Check" \
    "$BASE_URL/v1/indexer/brc20/health" \
    "200"

echo -e "${CYAN}Step 2: Test /list endpoint (default parameters)${NC}"
test_endpoint "Get Ticker List (default)" \
    "$BASE_URL/v1/indexer/brc20/list" \
    "200"

echo -e "${CYAN}Step 3: Test /list with limit parameter${NC}"
test_endpoint "Get Ticker List (limit=10)" \
    "$BASE_URL/v1/indexer/brc20/list?limit=10" \
    "200"

echo -e "${CYAN}Step 4: Test /list with limit and offset${NC}"
test_endpoint "Get Ticker List (limit=5&offset=10)" \
    "$BASE_URL/v1/indexer/brc20/list?limit=5&offset=10" \
    "200"

echo -e "${CYAN}Step 5: Test /list with large limit${NC}"
test_endpoint "Get Ticker List (limit=2000)" \
    "$BASE_URL/v1/indexer/brc20/list?limit=2000" \
    "422"

echo -e "${CYAN}Step 6: Verify old /tick endpoint returns 404${NC}"
test_endpoint "Old /tick endpoint (should be 404)" \
    "$BASE_URL/v1/indexer/brc20/tick" \
    "404"

echo -e "${GREEN}🎉 All tests completed!${NC}"
echo -e "${YELLOW}💡 Notes:${NC}"
echo -e "   • If health check fails, start API: ${CYAN}cd ubrc20-indexer && python run.py${NC}"
echo -e "   • If /list returns 404, the modification wasn't applied yet"
echo -e "   • If old /tick still works, both endpoints exist (not expected)"
echo