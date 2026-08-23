import re

def detect_entities(text: str) -> list[str]:
    return sorted(set(re.findall(r"\b(?:SEC|Ethereum Foundation|BlackRock|Coinbase|Binance|Donald Trump|Elon Musk)\b", text, re.I)))
