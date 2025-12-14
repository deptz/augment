#!/usr/bin/env python3
"""
Diagnostic script to check why user stories can't be fetched for a PRD ID.

Usage:
    python scripts/diagnose_prd_stories.py 50191401021
"""

import sys
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.confluence_client import ConfluenceClient
from src.prd_story_parser import PRDStoryParser

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title: str):
    """Print a section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_step(step: str, status: str = "INFO"):
    """Print a diagnostic step"""
    status_symbol = {
        "OK": "✓",
        "ERROR": "✗",
        "WARNING": "⚠",
        "INFO": "→"
    }.get(status, "→")
    print(f"{status_symbol} {step}")


def check_confluence_connection(client: ConfluenceClient) -> bool:
    """Check if Confluence connection works"""
    print_section("Step 1: Testing Confluence Connection")
    
    try:
        result = client.test_connection()
        if result:
            print_step("Confluence connection successful", "OK")
            return True
        else:
            print_step("Confluence connection failed", "ERROR")
            return False
    except Exception as e:
        print_step(f"Confluence connection error: {e}", "ERROR")
        return False


def fetch_prd_page(client: ConfluenceClient, page_id: str) -> Optional[Dict[str, Any]]:
    """Fetch PRD page content by ID"""
    print_section("Step 2: Fetching PRD Page Content")
    
    print_step(f"Attempting to fetch page ID: {page_id}")
    
    try:
        # Try direct page ID fetch
        page_data = client._get_page_by_id(page_id)
        
        if page_data:
            print_step("Page fetched successfully", "OK")
            print_step(f"Page Title: {page_data.get('title', 'N/A')}")
            print_step(f"Page URL: {page_data.get('url', 'N/A')}")
            print_step(f"Page ID: {page_data.get('id', 'N/A')}")
            return page_data
        else:
            print_step("Page fetch returned None", "ERROR")
            return None
            
    except Exception as e:
        print_step(f"Error fetching page: {e}", "ERROR")
        import traceback
        print_step(f"Traceback: {traceback.format_exc()}", "ERROR")
        return None


def check_body_structure(page_data: Dict[str, Any]) -> bool:
    """Check if page data has correct body structure"""
    print_section("Step 3: Checking Body Structure")
    
    has_body = 'body' in page_data
    print_step(f"Has 'body' key: {has_body}", "OK" if has_body else "ERROR")
    
    if not has_body:
        print_step(f"Available keys: {list(page_data.keys())}", "INFO")
        return False
    
    body = page_data.get('body', {})
    has_storage = 'storage' in body
    print_step(f"Has 'body.storage' key: {has_storage}", "OK" if has_storage else "ERROR")
    
    if not has_storage:
        print_step(f"Body keys: {list(body.keys())}", "INFO")
        return False
    
    storage = body.get('storage', {})
    has_value = 'value' in storage
    print_step(f"Has 'body.storage.value' key: {has_value}", "OK" if has_value else "ERROR")
    
    if not has_value:
        print_step(f"Storage keys: {list(storage.keys())}", "INFO")
        return False
    
    html_content = storage.get('value', '')
    has_content = bool(html_content)
    content_length = len(html_content) if html_content else 0
    
    print_step(f"HTML content exists: {has_content}", "OK" if has_content else "ERROR")
    print_step(f"HTML content length: {content_length} characters", "INFO")
    
    if not has_content:
        return False
    
    # Show first 200 characters as preview
    preview = html_content[:200].replace('\n', ' ')
    print_step(f"HTML preview (first 200 chars): {preview}...", "INFO")
    
    return True


def check_html_parsing(html_content: str) -> Optional[BeautifulSoup]:
    """Check if HTML can be parsed"""
    print_section("Step 4: Parsing HTML Content")
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        print_step("HTML parsed successfully", "OK")
        return soup
    except Exception as e:
        print_step(f"HTML parsing error: {e}", "ERROR")
        return None


def check_tables(soup: BeautifulSoup) -> list:
    """Check for tables in HTML"""
    print_section("Step 5: Checking for Tables")
    
    all_tables = soup.find_all("table")
    print_step(f"Found {len(all_tables)} table(s) in PRD HTML", "INFO")
    
    if len(all_tables) == 0:
        print_step("No tables found in PRD", "ERROR")
        return []
    
    # Analyze each table
    for i, tbl in enumerate(all_tables, 1):
        print_step(f"\nAnalyzing Table {i}:", "INFO")
        
        # Get headers
        headers = [th.get_text(" ", strip=True) for th in tbl.find_all("th")]
        if not headers:
            # Try first row as headers
            first_row = tbl.find('tr')
            if first_row:
                headers = [cell.get_text(" ", strip=True) for cell in first_row.find_all(['th', 'td'])]
        
        print_step(f"  Headers: {headers}", "INFO")
        
        # Check for story-related keywords
        headers_lower = [h.lower() for h in headers]
        header_text = ' '.join(headers_lower)
        
        has_user_story = any("user story" in h or "user-story" in h for h in headers_lower)
        has_acceptance_criteria = any("acceptance criteria" in h or "acceptance-criteria" in h or "acceptance" in h for h in headers_lower)
        has_title = any("title" in h.lower() or "summary" in h.lower() for h in headers_lower)
        
        print_step(f"  Has 'user story' column: {has_user_story}", "OK" if has_user_story else "WARNING")
        print_step(f"  Has 'acceptance criteria' column: {has_acceptance_criteria}", "OK" if has_acceptance_criteria else "WARNING")
        print_step(f"  Has 'title' column: {has_title}", "INFO")
        
        # Count rows
        rows = tbl.find_all("tr")
        print_step(f"  Total rows: {len(rows)}", "INFO")
        
        if len(rows) > 1:
            data_rows = len(rows) - 1  # Exclude header
            print_step(f"  Data rows: {data_rows}", "INFO")
    
    return all_tables


def check_story_sections(soup: BeautifulSoup):
    """Check for story-related sections"""
    print_section("Step 6: Checking for Story Sections")
    
    story_section_patterns = [
        'Story-Ticket-List',
        'Story Ticket List',
        'Story-Tickets',
        'Story Tickets',
        'Story-List',
        'Story List',
        'User-Stories',
        'User Stories'
    ]
    
    found_sections = []
    for pattern in story_section_patterns:
        # Check by ID
        section = soup.find(attrs={'id': pattern})
        if section:
            found_sections.append(f"ID: {pattern}")
            print_step(f"Found section by ID: {pattern}", "OK")
        
        # Check by heading text
        for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            heading_text = heading.get_text().strip()
            if pattern.lower() in heading_text.lower():
                found_sections.append(f"Heading: {heading_text}")
                print_step(f"Found section by heading: {heading_text}", "OK")
                break
    
    if not found_sections:
        print_step("No story sections found", "WARNING")
    
    return found_sections


def test_story_parser(page_data: Dict[str, Any], epic_key: str = "TEST-EPIC") -> list:
    """Test the PRD story parser"""
    print_section("Step 7: Testing Story Parser")
    
    try:
        parser = PRDStoryParser()
        stories = parser.parse_stories_from_prd_content(page_data, epic_key)
        
        print_step(f"Parser returned {len(stories)} stories", "OK" if stories else "ERROR")
        
        if stories:
            print_step("\nParsed Stories:", "INFO")
            for i, story in enumerate(stories[:5], 1):  # Show first 5
                print_step(f"  Story {i}: {story.summary[:60]}...", "INFO")
                print_step(f"    Description length: {len(story.description)} chars", "INFO")
                print_step(f"    Acceptance criteria: {len(story.acceptance_criteria)} items", "INFO")
        
        return stories
        
    except Exception as e:
        print_step(f"Parser error: {e}", "ERROR")
        import traceback
        print_step(f"Traceback: {traceback.format_exc()}", "ERROR")
        return []


def main():
    """Main diagnostic function"""
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_prd_stories.py <PRD_PAGE_ID>")
        print("Example: python scripts/diagnose_prd_stories.py 50191401021")
        sys.exit(1)
    
    page_id = sys.argv[1]
    
    print_section("PRD Story Fetching Diagnostic Tool")
    print(f"Diagnosing PRD ID: {page_id}")
    
    # Load configuration
    print_section("Initialization")
    try:
        config = Config()
        print_step("Configuration loaded", "OK")
    except Exception as e:
        print_step(f"Configuration error: {e}", "ERROR")
        sys.exit(1)
    
    # Initialize Confluence client
    try:
        confluence_config = config.confluence
        if not all(confluence_config.get(key) for key in ['server_url', 'username', 'api_token']):
            print_step("Confluence configuration incomplete", "ERROR")
            print_step("Required: server_url, username, api_token", "INFO")
            sys.exit(1)
        
        confluence_client = ConfluenceClient(
            server_url=confluence_config['server_url'],
            username=confluence_config['username'],
            api_token=confluence_config['api_token']
        )
        print_step("Confluence client initialized", "OK")
    except Exception as e:
        print_step(f"Confluence client initialization error: {e}", "ERROR")
        sys.exit(1)
    
    # Run diagnostics
    if not check_confluence_connection(confluence_client):
        print_section("Summary")
        print_step("Diagnostic failed at connection step", "ERROR")
        sys.exit(1)
    
    page_data = fetch_prd_page(confluence_client, page_id)
    if not page_data:
        print_section("Summary")
        print_step("Diagnostic failed at page fetch step", "ERROR")
        sys.exit(1)
    
    if not check_body_structure(page_data):
        print_section("Summary")
        print_step("Diagnostic failed at body structure check", "ERROR")
        sys.exit(1)
    
    html_content = page_data.get('body', {}).get('storage', {}).get('value', '')
    soup = check_html_parsing(html_content)
    if not soup:
        print_section("Summary")
        print_step("Diagnostic failed at HTML parsing step", "ERROR")
        sys.exit(1)
    
    tables = check_tables(soup)
    check_story_sections(soup)
    
    stories = test_story_parser(page_data)
    
    # Final summary
    print_section("Summary")
    if stories:
        print_step(f"✓ SUCCESS: Found {len(stories)} stories", "OK")
    else:
        print_step("✗ FAILED: No stories could be parsed", "ERROR")
        print_step("\nPossible issues:", "INFO")
        print_step("  1. PRD page may not have a story table", "INFO")
        print_step("  2. Table may not have 'user story' column header", "INFO")
        print_step("  3. Table may not have 'acceptance criteria' column header", "INFO")
        print_step("  4. Table may be empty or have no data rows", "INFO")
        print_step("  5. Table structure may not match expected format", "INFO")
    
    print("\n")


if __name__ == "__main__":
    main()

