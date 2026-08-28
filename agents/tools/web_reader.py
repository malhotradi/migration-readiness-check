import requests
import re
import logging
from html.parser import HTMLParser
from typing import Optional

logger = logging.getLogger(__name__)

class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_blocks = []
        self.in_script_or_style = False

    def handle_starttag(self, tag, attrs):
        if tag in ["script", "style", "head", "meta", "link"]:
            self.in_script_or_style = True

    def handle_endtag(self, tag):
        if tag in ["script", "style", "head", "meta", "link"]:
            self.in_script_or_style = False

    def handle_data(self, data):
        if not self.in_script_or_style:
            cleaned = data.strip()
            if cleaned:
                self.text_blocks.append(cleaned)

    def get_text(self) -> str:
        return "\n".join(self.text_blocks)

def clean_html(html_content: str) -> str:
    """Extracts readable text from HTML by removing script/style tags and extracting content."""
    parser = HTMLTextExtractor()
    parser.feed(html_content)
    return parser.get_text()

def fetch_latest_gcp_migration_rules(source_engine: str) -> str:
    """
    Fetches the official live Google Cloud Database Migration Service (DMS) documentation page 
    for the selected database source engine and extracts the text content.
    This is used to dynamically identify if any new source database requirements or configuration variables 
    have been added to the GCP prerequisites.
    """
    url_map = {
        "MySQL": "https://cloud.google.com/database-migration/docs/mysql/configure-source-database",
        "PostgreSQL": "https://cloud.google.com/database-migration/docs/postgresql/configure-source-database",
        "SQL Server": "https://cloud.google.com/database-migration/docs/sql-server/configure-source-database",
        "Oracle": "https://cloud.google.com/database-migration/docs/oracle/configure-source-database"
    }

    url = url_map.get(source_engine)
    if not url:
        return f"Error: No documentation URL mapped for source engine type: '{source_engine}'"

    logger.info(f"Fetching latest GCP DMS source prerequisites from: {url}")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Extract and clean content
        raw_text = clean_html(response.text)
        
        # Clean up excessive newlines
        cleaned_text = re.sub(r'\n+', '\n', raw_text)
        return cleaned_text
    except Exception as e:
        logger.error(f"Failed to fetch live GCP migration rules from {url}: {str(e)}")
        return f"Error: Unable to fetch live GCP migration rules from documentation website. Reason: {str(e)}"
