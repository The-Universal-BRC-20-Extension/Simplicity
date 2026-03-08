"""
Utility functions for ticker normalization.

yTokens (rebasing derivatives) MUST preserve lowercase 'y' prefix.
Only Curve staking can create tokens with 'y' prefix.
"""


def normalize_ticker(ticker: str, preserve_y: bool = True) -> str:
    """
    Normalize ticker while preserving 'y' prefix for yTokens.

    Args:
        ticker: Ticker to normalize (e.g., "yWTF", "YWTF", "LOL")
        preserve_y: If True, preserve 'y' minuscule for yTokens (default: True)

    Returns:
        Normalized ticker:
        - yTokens (starts with 'y' lowercase): 'y' + rest in uppercase (e.g., "yWTF")
        - Normal tokens (including 'Y' uppercase): All uppercase (e.g., "YWTF", "LOL")
    """
    if not ticker:
        return ticker

    # Strip whitespace
    ticker = ticker.strip()

    # Only 'y' (lowercase) is treated as yToken prefix
    # 'Y' (uppercase) is preserved as normal token (different ticker)
    if preserve_y and len(ticker) > 0 and ticker[0] == "y":
        # yToken: preserve 'y' minuscule, uppercase the rest
        return "y" + ticker[1:].upper()
    else:
        # Normal token: uppercase all (including 'Y' prefix tokens)
        return ticker.upper()


def normalize_ticker_for_comparison(ticker: str) -> str:
    """
    Normalize ticker for comparison purposes.

    This is used when comparing tickers from different sources (DB, API, etc.)
    to ensure consistent comparison.

    Args:
        ticker: Ticker to normalize

    Returns:
        Normalized ticker for comparison
    """
    return normalize_ticker(ticker, preserve_y=True)


def parse_pool_id_tickers(pool_id: str) -> tuple[str, str]:
    """
    Parse pool_id to extract token_a and token_b, preserving 'y' prefix.

    Args:
        pool_id: Canonical pool ID (e.g., "LOL-yWTF" or "LOL-YWTF")

    Returns:
        Tuple of (token_a, token_b) normalized:
        - "LOL-yWTF" -> ("LOL", "yWTF")
        - "LOL-YWTF" -> ("LOL", "YWTF")  # Different ticker!
    """
    if "-" not in pool_id:
        raise ValueError(f"Invalid pool_id format: {pool_id}")

    tokens = pool_id.split("-")
    if len(tokens) != 2:
        raise ValueError(f"Invalid pool_id format: {pool_id}")

    # Normalize each token (preserve 'y' minuscule ONLY, 'Y' uppercase stays uppercase)
    token_a = normalize_ticker(tokens[0].strip(), preserve_y=True)
    token_b = normalize_ticker(tokens[1].strip(), preserve_y=True)

    return (token_a, token_b)


def sort_tickers_for_pool(ticker_a: str, ticker_b: str) -> tuple[str, str]:
    """
    Sort two tickers for pool creation, preserving 'y' prefix.

    Args:
        ticker_a: First ticker
        ticker_b: Second ticker

    Returns:
        Tuple of (token_a, token_b) sorted alphabetically with 'y' preserved
    """

    def normalize_for_sort(ticker: str) -> str:
        """Return normalized ticker for alphabetical sorting.

        Preserves 'y' minuscule for yTokens, but sorts alphabetically.
        'y' (121) comes after 'L' (76) in ASCII, so "LOL" < "yWTF" normally.
        """
        if ticker and len(ticker) > 0 and ticker[0] == "y":
            # yToken: preserve 'y' minuscule, uppercase the rest for comparison
            return "y" + ticker[1:].upper()
        else:
            # Normal token: uppercase (including 'Y' prefix)
            return ticker.upper()

    # Sort preserving 'y' minuscule ONLY
    tickers_sorted = sorted([ticker_a, ticker_b], key=normalize_for_sort)
    token_a, token_b = tickers_sorted[0], tickers_sorted[1]

    # Normalize for storage (preserve 'y' minuscule ONLY, 'Y' uppercase stays uppercase)
    token_a_normalized = normalize_ticker(token_a, preserve_y=True)
    token_b_normalized = normalize_ticker(token_b, preserve_y=True)

    return (token_a_normalized, token_b_normalized)
