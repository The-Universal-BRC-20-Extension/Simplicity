#!/bin/bash

# --- Configuration ---
# Remplace cette URL par celle de ton serveur de production ou local.
DOMAIN_NAME="https://indexer.wtf.rich" 
# Remplace par ta clé API si nécessaire. Laisse vide si pas de clé.
API_KEY="Kycvq5CiKukoBWJjN3WEduoHnE6pKWrQPM7XuiLEkbgLuQgEzZPu"

# --- Variables de test (à adapter) ---
TICKER="W"
ADDRESS="bc1p9s8jywvdavsqlxq9f0yvhcarshda4su87tgt5hu29rze07plykcqrrawtf"
TXID="fe469ac05d7da1dd50d9517fbee6be9601fb230477ef7b88b7e29cb5bf9efabb"
BLOCK_HEIGHT="919100"
RAW_TX_HEX_VALIDATE="02000000000101b1883fe9a68eec92c2b46f0bd9c68f38b30906589c2224ffbc79f592e0130d200000000000ffffffff030000000000000000356a337b2270223a226272632d3230222c226f70223a226d696e74222c227469636b223a2257222c22616d74223a223130303030227d22020000000000002251202c0f22398deb200f98054bc8cbe3a385dbdac387f2d0ba5f8a28c597f83f25b010270000000000002251201b0aebd94a7ab6a6fb1c05270b800d5e6177c05ae4f7107d16b2de77f1c8ad1003402692fe6110a46e09c41719896fb72b823906bce74448fe02ba8708f1a32aaa83a0129bd13fc206c2e09539f587169e791ad7092d6940110f88b44dd51837cf1330201f38897fe29463cf1b76e74a70f13c71ef4414431b8a508d6c741574f8b1e55dac006307575f50524f4f460200016821c050929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee96802ac07100000000"
SCRIPT_ADDRESS="bc1prv9whk2202m2d7cuq5nshqqdtesh0sz6unm3qlgkkt080uwg45gq05pxyz"
POSITION_ID=1

# --- Helpers ---
CURL_OPTS="-s" # -s pour silent

# Tableau des headers pour l'exécution réelle
EXEC_HEADERS=()
# Tableau des headers pour l'affichage dans les logs (avec masquage)
DISPLAY_HEADERS=()

if [ -n "$API_KEY" ]; then
    EXEC_HEADERS+=(-H \"X-API-Key: ${API_KEY}\")
    DISPLAY_HEADERS+=(-H "X-API-Key: [MASQUÉ]")
fi

function run_test {
    # $1: Nom du test
    # $2: Méthode HTTP (GET, POST, etc.)
    # $3: Chemin de l'endpoint
    # $4: Options supplémentaires (corps de la requête -d, etc.)

    echo "--- Test: $1 ---"

    # Construit la commande pour l'affichage, en utilisant les headers masqués
    DISPLAY_COMMAND="curl ${CURL_OPTS} -X $2 \"${DOMAIN_NAME}$3\" ${DISPLAY_HEADERS[@]} $4"
    echo "Executing: ${DISPLAY_COMMAND}"

    # Construit la commande pour l'exécution réelle, avec la vraie clé API
    EXEC_COMMAND="curl ${CURL_OPTS} -X $2 \"${DOMAIN_NAME}$3\" ${EXEC_HEADERS[@]} $4"

    # Exécute la commande et formate la sortie JSON
    eval ${EXEC_COMMAND} | jq .
    echo -e "\n"
}

# --- Suite de Tests ---

# == Health Checks ==
run_test "Root Endpoint" "GET" "/" ""
run_test "Concurrency Health" "GET" "/health/concurrency" ""
run_test "BRC-20 Health" "GET" "/v1/indexer/brc20/health" ""
run_test "Validation Service Health" "GET" "/v1/validator/health" ""

# == BRC-20 Endpoints ==
run_test "Indexer Status" "GET" "/v1/indexer/brc20/status" ""
run_test "List BRC-20 Tokens (limit 5)" "GET" "/v1/indexer/brc20/list?limit=5" ""
run_test "List All BRC-20 Tokens (max 10)" "GET" "/v1/indexer/brc20/list/all?max_results=10" ""
run_test "Ticker Info" "GET" "/v1/indexer/brc20/${TICKER}/info" ""
run_test "Ticker Holders (limit 5)" "GET" "/v1/indexer/brc20/${TICKER}/holders?limit=5" ""
run_test "All Ticker Holders (max 10)" "GET" "/v1/indexer/brc20/${TICKER}/holders/all?max_results=10" ""
run_test "Ticker History (limit 5)" "GET" "/v1/indexer/brc20/${TICKER}/history?limit=5" ""
run_test "All Ticker History (max 10)" "GET" "/v1/indexer/brc20/${TICKER}/history/all?max_results=10" ""
run_test "Ticker TX History" "GET" "/v1/indexer/brc20/${TICKER}/tx/${TXID}/history" ""
run_test "Address Ticker Balance" "GET" "/v1/indexer/address/${ADDRESS}/brc20/${TICKER}/info" ""
run_test "Address General History (limit 5)" "GET" "/v1/indexer/address/${ADDRESS}/history?limit=5" ""
run_test "All Address General History (max 10)" "GET" "/v1/indexer/address/${ADDRESS}/history/all?max_results=10" ""
run_test "Address Ticker History (limit 5)" "GET" "/v1/indexer/address/${ADDRESS}/brc20/${TICKER}/history?limit=5" ""
run_test "All Address Ticker History (max 10)" "GET" "/v1/indexer/address/${ADDRESS}/brc20/${TICKER}/history/all?max_results=10" ""
run_test "History by Height (limit 5)" "GET" "/v1/indexer/brc20/history-by-height/${BLOCK_HEIGHT}?limit=5" ""
run_test "All History by Height (max 10)" "GET" "/v1/indexer/brc20/history-by-height/${BLOCK_HEIGHT}/all?max_results=10" ""

# == Mempool Endpoints ==
run_test "Check Pending Transfers" \
    "POST" \
    "/v1/mempool/check-pending" \
    "-H \"Content-Type: application/json\" -d '{\"address\": \"${ADDRESS}\", \"ticker\": \"${TICKER}\"}'"

# == Validation Endpoints ==
run_test "Validate Wrap Mint" \
    "POST" \
    "/v1/validator/validate-wrap-mint" \
    "-H \"Content-Type: application/json\" -d '{\"raw_tx_hex\": \"${RAW_TX_HEX_VALIDATE}\"}'"
run_test "Validate Address from Witness" \
    "POST" \
    "/v1/validator/validate-address-from-witness" \
    "-H \"Content-Type: application/json\" -d '{\"raw_tx_hex\": \"${RAW_TX_HEX_VALIDATE}\"}'"

# == Swap Endpoints ==
run_test "List Swap Positions" "GET" "/v1/indexer/swap/positions?limit=5" ""
run_test "Get Swap Position by ID" "GET" "/v1/indexer/swap/positions/${POSITION_ID}" ""
run_test "List Owner Swap Positions" "GET" "/v1/indexer/swap/owner/${ADDRESS}/positions?limit=5" ""
run_test "List Expiring Swap Positions" "GET" "/v1/indexer/swap/expiring?height_lte=${BLOCK_HEIGHT}&limit=5" ""
run_test "List Pools" "GET" "/v1/indexer/swap/pools?limit=5" ""
run_test "Get Swap TVL for a Ticker" "GET" "/v1/indexer/swap/tvl/${TICKER}" ""

# == Wrap Endpoints ==
run_test "List Wrap Contracts" "GET" "/v1/indexer/w/contracts?limit=5" ""
run_test "Get Wrap Contract by Script Address" "GET" "/v1/indexer/w/contracts/${SCRIPT_ADDRESS}" ""
run_test "Get Wrap TVL" "GET" "/v1/indexer/w/tvl" ""
run_test "Get Wrap Metrics" "GET" "/v1/indexer/w/metrics" ""


echo "--- Tous les tests sont terminés ---"
