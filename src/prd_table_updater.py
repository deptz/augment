"""
PRD Table Updater
Utility functions for updating PRD table HTML with JIRA ticket links
"""
import logging
import uuid
from typing import Optional, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def update_story_row_with_jira_link(
    html_content: str, 
    story_row_index: int, 
    jira_key: str, 
    jira_url: str
) -> Optional[str]:
    """
    Update PRD table HTML to add/update JIRA ticket link in a specific row
    
    Args:
        html_content: Original HTML content from Confluence
        story_row_index: Zero-based index of the story row (0 = first data row, after header)
        jira_key: JIRA ticket key (e.g., "STORY-123")
        jira_url: Full JIRA ticket URL
        
    Returns:
        Updated HTML content, or None if update failed
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find the story table
        story_table = _find_story_table(soup)
        if not story_table:
            logger.error("Could not find story table in PRD HTML")
            return None
        
        # Get all rows (header + data rows)
        rows = story_table.find_all("tr")
        if not rows:
            logger.error("Story table has no rows")
            return None
        
        # Validate row index (account for header row)
        # story_row_index is 0-based for data rows, so row 0 = rows[1] (after header)
        data_row_index = story_row_index + 1
        if data_row_index >= len(rows):
            logger.error(f"Row index {story_row_index} is out of range (table has {len(rows) - 1} data rows)")
            return None
        
        # Get header row to find or add JIRA ticket column
        header_row = rows[0]
        header_cells = header_row.find_all(['th', 'td'])
        header_texts = [cell.get_text(" ", strip=True) for cell in header_cells]
        
        # Find JIRA ticket column index
        jira_col_index = None
        jira_column_names = ['jira ticket', 'story key', 'jira link', 'ticket', 'story ticket']
        
        for idx, header_text in enumerate(header_texts):
            if any(name in header_text.lower() for name in jira_column_names):
                jira_col_index = idx
                logger.debug(f"Found existing JIRA ticket column at index {jira_col_index}")
                break
        
        # If column doesn't exist, add it
        if jira_col_index is None:
            logger.info("JIRA ticket column not found, adding new column")
            jira_col_index = _add_jira_ticket_column(story_table, rows, soup)
            if jira_col_index is None:
                logger.error("Failed to add JIRA ticket column")
                return None
        
        # Update the specific row's JIRA ticket cell
        target_row = rows[data_row_index]
        row_cells = target_row.find_all("td")
        
        # Ensure we have enough cells (add empty cells if needed)
        while len(row_cells) <= jira_col_index:
            new_cell = soup.new_tag("td")
            target_row.append(new_cell)
            row_cells = target_row.find_all("td")
        
        # Update or create the JIRA ticket cell
        jira_cell = row_cells[jira_col_index]
        
        # Clear existing content and create HTML anchor tag for Confluence
        jira_cell.clear()
        link_tag = soup.new_tag("a", href=jira_url)
        link_tag.string = jira_key
        jira_cell.append(link_tag)
        
        logger.info(f"Updated row {story_row_index} with JIRA link: {jira_key}")
        
        # Return updated HTML
        return str(soup)
        
    except Exception as e:
        logger.error(f"Error updating PRD table with JIRA link: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def _find_story_table(soup: BeautifulSoup):
    """Find the story ticket list table in the PRD (same logic as PRDStoryParser)"""
    # Strategy: Find table with both "user story" AND "acceptance criteria" in headers
    for tbl in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True) for th in tbl.find_all("th")]
        if not headers:
            # Try td tags for headers
            first_row = tbl.find('tr')
            if first_row:
                headers = [cell.get_text(" ", strip=True) for cell in first_row.find_all(['th', 'td'])]
        
        if not headers:
            continue
        
        headers_lower = [h.lower() for h in headers]
        has_user_story = any("user story" in h or "user-story" in h for h in headers_lower)
        has_acceptance_criteria = any("acceptance criteria" in h or "acceptance-criteria" in h or "acceptance" in h for h in headers_lower)
        
        if has_user_story and has_acceptance_criteria:
            return tbl
    
    # Fallback: Find any table with "user story" header
    for tbl in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True) for th in tbl.find_all("th")]
        if not headers:
            first_row = tbl.find('tr')
            if first_row:
                headers = [cell.get_text(" ", strip=True) for cell in first_row.find_all(['th', 'td'])]
        
        if headers:
            headers_lower = [h.lower() for h in headers]
            if any("user story" in h or "user-story" in h for h in headers_lower):
                return tbl
    
    return None


def _add_jira_ticket_column(table, rows, soup=None) -> Optional[int]:
    """
    Add a new "JIRA Ticket" column to the table
    
    Args:
        table: BeautifulSoup table element
        rows: List of all table rows (header + data)
        soup: BeautifulSoup object (optional, will be extracted from table if not provided)
        
    Returns:
        Index of the newly added column, or None if failed
    """
    try:
        if not table:
            logger.error("Table is None in _add_jira_ticket_column")
            return None
        if not rows:
            return None
        
        # Get soup object from table if not provided
        if soup is None:
            # Traverse up to find the BeautifulSoup root object
            parent = table
            while parent is not None and not isinstance(parent, BeautifulSoup):
                parent = getattr(parent, 'parent', None)
            soup = parent
        
        if soup is None:
            logger.error("Could not find BeautifulSoup object for creating new tags")
            return None
        
        # Add header cell
        header_row = rows[0]
        new_header = soup.new_tag("th")
        new_header.string = "JIRA Ticket"
        header_row.append(new_header)
        
        # Get column index (it's the last column now)
        header_cells = header_row.find_all(['th', 'td'])
        col_index = len(header_cells) - 1
        
        # Add empty cells to all data rows
        data_rows_count = 0
        for row in rows[1:]:
            new_cell = soup.new_tag("td")
            row.append(new_cell)
            data_rows_count += 1
        
        logger.info(f"Added JIRA Ticket column at index {col_index}")
        return col_index
        
    except Exception as e:
        logger.error(f"Error adding JIRA ticket column: {e}")
        return None


def add_uuid_placeholder_to_row(
    html_content: str,
    story_row_index: int,
    row_uuid: str
) -> Optional[str]:
    """
    Add UUID placeholder to a specific PRD table row
    
    Args:
        html_content: Original HTML content from Confluence
        story_row_index: Zero-based index of the story row (0 = first data row, after header)
        row_uuid: UUID to use as placeholder
        
    Returns:
        Updated HTML content, or None if update failed
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find the story table
        story_table = _find_story_table(soup)
        if not story_table:
            logger.error("Could not find story table in PRD HTML")
            return None
        
        # Get all rows (header + data rows)
        rows = story_table.find_all("tr")
        if not rows:
            logger.error("Story table has no rows")
            return None
        
        # Validate row index
        data_row_index = story_row_index + 1
        if data_row_index >= len(rows):
            logger.error(f"Row index {story_row_index} is out of range (table has {len(rows) - 1} data rows)")
            return None
        
        # Get header row to find or add JIRA ticket column
        header_row = rows[0]
        header_cells = header_row.find_all(['th', 'td'])
        header_texts = [cell.get_text(" ", strip=True) for cell in header_cells]
        
        # Find JIRA ticket column index
        jira_col_index = None
        jira_column_names = ['jira ticket', 'story key', 'jira link', 'ticket', 'story ticket']
        
        for idx, header_text in enumerate(header_texts):
            if any(name in header_text.lower() for name in jira_column_names):
                jira_col_index = idx
                logger.debug(f"Found existing JIRA ticket column at index {jira_col_index}")
                break
        
        # If column doesn't exist, add it
        if jira_col_index is None:
            logger.info("JIRA ticket column not found, adding new column")
            jira_col_index = _add_jira_ticket_column(story_table, rows, soup)
            if jira_col_index is None:
                logger.error("Failed to add JIRA ticket column")
                return None
            # Re-fetch rows after adding column
            rows = story_table.find_all("tr")
            data_row_index = story_row_index + 1
        
        # Update the specific row's JIRA ticket cell
        target_row = rows[data_row_index]
        row_cells = target_row.find_all("td")
        
        # Ensure we have enough cells
        while len(row_cells) <= jira_col_index:
            new_cell = soup.new_tag("td")
            target_row.append(new_cell)
            row_cells = target_row.find_all("td")
        
        # Update or create the JIRA ticket cell with UUID placeholder
        jira_cell = row_cells[jira_col_index]
        
        # Format as markdown link for Confluence: [TEMP-{uuid}](placeholder)
        uuid_placeholder = f"[TEMP-{row_uuid}](placeholder)"
        
        # Clear existing content and add UUID placeholder
        jira_cell.clear()
        jira_cell.string = uuid_placeholder
        
        logger.info(f"Added UUID placeholder to row {story_row_index}: {row_uuid}")
        
        # Return updated HTML
        return str(soup)
        
    except Exception as e:
        logger.error(f"Error adding UUID placeholder to PRD table: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def find_row_by_uuid(
    html_content: str,
    row_uuid: str
) -> Optional[int]:
    """
    Find PRD table row index by UUID placeholder
    
    Args:
        html_content: HTML content from Confluence
        row_uuid: UUID to search for
        
    Returns:
        Zero-based row index if found, None otherwise
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find the story table
        story_table = _find_story_table(soup)
        if not story_table:
            logger.error("Could not find story table in PRD HTML")
            return None
        
        # Get all rows (header + data rows)
        rows = story_table.find_all("tr")
        if len(rows) < 2:
            logger.error("Story table has no data rows")
            return None
        
        # Get header row to find JIRA ticket column
        header_row = rows[0]
        header_cells = header_row.find_all(['th', 'td'])
        header_texts = [cell.get_text(" ", strip=True) for cell in header_cells]
        
        # Find JIRA ticket column index
        jira_col_index = None
        jira_column_names = ['jira ticket', 'story key', 'jira link', 'ticket', 'story ticket']
        
        for idx, header_text in enumerate(header_texts):
            if any(name in header_text.lower() for name in jira_column_names):
                jira_col_index = idx
                break
        
        if jira_col_index is None:
            logger.warning("JIRA ticket column not found")
            return None
        
        # Search for UUID placeholder in data rows
        uuid_pattern = f"[TEMP-{row_uuid}](placeholder)"
        
        for row_idx, row in enumerate(rows[1:], 0):  # Start from 0 for data rows
            cells = row.find_all("td")
            if jira_col_index < len(cells):
                jira_cell = cells[jira_col_index]
                cell_text = jira_cell.get_text(" ", strip=True)
                
                if uuid_pattern in cell_text:
                    logger.info(f"Found UUID {row_uuid} at row index {row_idx}")
                    return row_idx
        
        logger.warning(f"UUID {row_uuid} not found in PRD table")
        return None
        
    except Exception as e:
        logger.error(f"Error finding row by UUID: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def replace_uuid_with_jira_link(
    html_content: str,
    story_row_index: int,
    jira_key: str,
    jira_url: str
) -> Optional[str]:
    """
    Replace UUID placeholder with actual JIRA link in a specific row
    
    Args:
        html_content: Original HTML content from Confluence
        story_row_index: Zero-based index of the story row (0 = first data row, after header)
        jira_key: JIRA ticket key (e.g., "STORY-123")
        jira_url: Full JIRA ticket URL
        
    Returns:
        Updated HTML content, or None if update failed
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find the story table
        story_table = _find_story_table(soup)
        if not story_table:
            logger.error("Could not find story table in PRD HTML")
            return None
        
        # Get all rows (header + data rows)
        rows = story_table.find_all("tr")
        if not rows:
            logger.error("Story table has no rows")
            return None
        
        # Validate row index
        data_row_index = story_row_index + 1
        if data_row_index >= len(rows):
            logger.error(f"Row index {story_row_index} is out of range (table has {len(rows) - 1} data rows)")
            return None
        
        # Get header row to find JIRA ticket column
        header_row = rows[0]
        header_cells = header_row.find_all(['th', 'td'])
        header_texts = [cell.get_text(" ", strip=True) for cell in header_cells]
        
        # Find JIRA ticket column index
        jira_col_index = None
        jira_column_names = ['jira ticket', 'story key', 'jira link', 'ticket', 'story ticket']
        
        for idx, header_text in enumerate(header_texts):
            if any(name in header_text.lower() for name in jira_column_names):
                jira_col_index = idx
                break
        
        # If column doesn't exist, add it
        if jira_col_index is None:
            logger.info("JIRA ticket column not found, adding new column")
            jira_col_index = _add_jira_ticket_column(story_table, rows, soup)
            if jira_col_index is None:
                logger.error("Failed to add JIRA ticket column")
                return None
            # Re-fetch rows after adding column
            rows = story_table.find_all("tr")
            data_row_index = story_row_index + 1
        
        # Update the specific row's JIRA ticket cell
        target_row = rows[data_row_index]
        row_cells = target_row.find_all("td")
        
        # Ensure we have enough cells (add empty cells if needed)
        while len(row_cells) <= jira_col_index:
            new_cell = soup.new_tag("td")
            target_row.append(new_cell)
            row_cells = target_row.find_all("td")
        
        # Update the JIRA ticket cell
        jira_cell = row_cells[jira_col_index]
        
        # Clear existing content and create HTML anchor tag for Confluence
        jira_cell.clear()
        link_tag = soup.new_tag("a", href=jira_url)
        link_tag.string = jira_key
        jira_cell.append(link_tag)
        
        logger.info(f"Replaced UUID with JIRA link in row {story_row_index}: {jira_key}")
        
        # Return updated HTML
        return str(soup)
        
    except Exception as e:
        logger.error(f"Error replacing UUID with JIRA link: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


