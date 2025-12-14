#!/usr/bin/env python3
"""
Detailed diagnostic script to analyze specific rows in a PRD table.

Usage:
    python scripts/diagnose_prd_row_details.py <PRD_ID> [story_title_search]
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
    level=logging.INFO,  # Reduce verbosity
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def analyze_table_rows(page_data: Dict[str, Any], search_term: Optional[str] = None):
    """Analyze each row in the story table"""
    html_content = page_data.get('body', {}).get('storage', {}).get('value', '')
    if not html_content:
        print("No HTML content found")
        return
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find the story table
    parser = PRDStoryParser()
    table = parser._find_story_table(soup)
    
    if not table:
        print("No story table found")
        return
    
    rows = table.find_all("tr")
    if not rows:
        print("No rows found")
        return
    
    # Get headers
    header_cells = rows[0].find_all("th")
    if not header_cells:
        header_cells = rows[0].find_all("td")
    
    if not header_cells:
        print("No headers found")
        return
    
    header_texts = [cell.get_text(" ", strip=True) for cell in header_cells]
    print(f"\nHeaders: {header_texts}\n")
    print("=" * 80)
    
    # Analyze each data row
    for i, row in enumerate(rows[1:], 1):
        cells = row.find_all("td")
        if not cells:
            print(f"\nRow {i}: No cells found")
            continue
        
        print(f"\n{'='*80}")
        print(f"ROW {i} ANALYSIS")
        print(f"{'='*80}")
        
        # Extract cell data
        row_data = {}
        for idx, header in enumerate(header_texts):
            if idx < len(cells):
                cell = cells[idx]
                cell_text = parser._clean_text(cell)
                row_data[header] = cell_text
                print(f"\n{header}:")
                print(f"  Length: {len(cell_text)} chars")
                print(f"  Preview: {cell_text[:100]}..." if len(cell_text) > 100 else f"  Content: {cell_text}")
                
                # Check if this is the search term
                if search_term and search_term.lower() in cell_text.lower():
                    print(f"  *** MATCHES SEARCH TERM: '{search_term}' ***")
        
        # Try to create story from this row
        print(f"\n--- Attempting to create story from row {i} ---")
        try:
            # Prepare row_data in the format expected by _create_story_from_row
            story_row_data = {
                'title': row_data.get('User Story', ''),
                'description': row_data.get('User Story', ''),
                'acceptance_criteria': row_data.get('Acceptance Criteria', ''),
                'mockup': row_data.get('Mockup / Technical Notes', '')
            }
            
            story = parser._create_story_from_row(story_row_data, "TEST-EPIC")
            if story:
                print(f"✓ Story created successfully:")
                print(f"  Summary: {story.summary[:80]}...")
                print(f"  Description length: {len(story.description)} chars")
            else:
                print(f"✗ Story creation returned None")
        except Exception as e:
            print(f"✗ Error creating story: {e}")
            import traceback
            print(f"  Traceback: {traceback.format_exc()}")


def main():
    """Main diagnostic function"""
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_prd_row_details.py <PRD_PAGE_ID> [search_term]")
        print("Example: python scripts/diagnose_prd_row_details.py 50781913160 'Self Topup'")
        sys.exit(1)
    
    page_id = sys.argv[1]
    search_term = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(f"Analyzing PRD ID: {page_id}")
    if search_term:
        print(f"Searching for: '{search_term}'")
    
    # Load configuration
    try:
        config = Config()
        confluence_config = config.confluence
        
        if not all(confluence_config.get(key) for key in ['server_url', 'username', 'api_token']):
            print("Confluence configuration incomplete")
            sys.exit(1)
        
        confluence_client = ConfluenceClient(
            server_url=confluence_config['server_url'],
            username=confluence_config['username'],
            api_token=confluence_config['api_token']
        )
    except Exception as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
    
    # Fetch page
    try:
        page_data = confluence_client._get_page_by_id(page_id)
        if not page_data:
            print(f"Failed to fetch page {page_id}")
            sys.exit(1)
        
        print(f"Page Title: {page_data.get('title', 'N/A')}")
    except Exception as e:
        print(f"Error fetching page: {e}")
        sys.exit(1)
    
    # Analyze rows
    analyze_table_rows(page_data, search_term)


if __name__ == "__main__":
    main()
