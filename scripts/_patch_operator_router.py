from pathlib import Path
import re

p = Path("apps/api/recoverai_api/operator/router.py")
text = p.read_text(encoding="utf-8")
text = re.sub(
    r'@router\.(get|post|patch)\("([^"]+)"\)',
    r'@router.\1("\2", response_model=None)',
    text,
)
p.write_text(text, encoding="utf-8")
