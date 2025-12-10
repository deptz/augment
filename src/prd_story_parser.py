"""
PRD Story Table Parser
Parses story ticket list tables from PRD documents
"""
import logging
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup
import re

from .planning_models import StoryPlan, AcceptanceCriteria, TestCase

logger = logging.getLogger(__name__)


class PRDStoryParser:
    """Parser for extracting story tickets from PRD table format"""
    
    def __init__(self):
        """
        Initialize PRD Story Parser
        """
        self.story_section_patterns = [
            'Story-Ticket-List',
            'Story Ticket List',
            'Story-Tickets',
            'Story Tickets',
            'Story-List',
            'Story List'
        ]
    
    def parse_stories_from_prd_content(self, prd_content: Dict[str, Any], epic_key: str) -> List[StoryPlan]:
        """
        Parse story tickets from PRD content
        
        Args:
            prd_content: PRD page data from Confluence
            epic_key: Epic key to associate stories with
            
        Returns:
            List of StoryPlan objects
        """
        try:
            # Get HTML content
            html_content = prd_content.get('body', {}).get('storage', {}).get('value', '')
            if not html_content:
                logger.warning("No HTML content found in PRD")
                logger.debug(f"PRD content keys: {list(prd_content.keys())}")
                logger.debug(f"Body structure: {prd_content.get('body', {})}")
                return []
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Debug: Log all tables found
            all_tables = soup.find_all("table")
            logger.debug(f"Found {len(all_tables)} table(s) in PRD HTML")
            for i, tbl in enumerate(all_tables):
                headers = [th.get_text(" ", strip=True) for th in tbl.find_all("th")]
                logger.debug(f"Table {i+1} headers: {headers}")
            
            # Find the story ticket list section
            table = self._find_story_table(soup)
            if not table:
                logger.warning("Story ticket list table not found in PRD")
                logger.debug(f"Searched {len(all_tables)} tables but none matched story table criteria")
                return []
            
            logger.debug(f"Found story table with {len(table.find_all('tr'))} rows")
            
            # Store page context for constructing attachment URLs
            self._page_id = prd_content.get('id', '')
            self._page_url = prd_content.get('url', '')
            
            # Parse table rows into stories
            stories = self._parse_table_rows(table, epic_key)
            logger.info(f"Parsed {len(stories)} stories from PRD table")
            return stories
            
        except Exception as e:
            logger.error(f"Error parsing stories from PRD: {e}")
            return []
    
    def _find_story_table(self, soup: BeautifulSoup) -> Optional[Any]:
        """Find the story ticket list table in the PRD"""
        # Strategy 0 (PRIMARY): Find table with both "user story" AND "acceptance criteria" in headers
        # This matches the working simulation logic exactly
        potential_table = None  # Store table with "user story" even if no "acceptance criteria"
        
        for tbl in soup.find_all("table"):
            # Match simulation exactly: use find_all("th") directly on table
            headers = [th.get_text(" ", strip=True) for th in tbl.find_all("th")]
            if not headers:
                continue
            
            # Normalize headers for comparison
            headers_lower = [h.lower() for h in headers]
            header_text = ' '.join(headers_lower)
            
            # Check for both required headers (matching simulation logic exactly)
            has_user_story = any("user story" in h or "user-story" in h for h in headers_lower)
            has_acceptance_criteria = any("acceptance criteria" in h or "acceptance-criteria" in h or "acceptance" in h for h in headers_lower)
            
            if has_user_story and has_acceptance_criteria:
                logger.debug("Found story table by primary strategy (has both 'user story' and 'acceptance criteria' headers)")
                logger.debug(f"Table headers: {headers}")
                return tbl
            
            # Also check if table has "user story" header (even without acceptance criteria, might still be valid)
            if has_user_story and potential_table is None:
                logger.debug(f"Found table with 'user story' header (but no 'acceptance criteria'): {headers}")
                # Store as potential match but continue searching for better match
                potential_table = tbl
        
        # Strategy 1: Find by section ID
        for pattern in self.story_section_patterns:
            section = soup.find(attrs={'id': pattern})
            if section:
                # Find table within this section
                table = section.find_next('table')
                if table:
                    logger.debug(f"Found story table by section ID: {pattern}")
                    return table
        
        # Strategy 2: Find by heading text (prioritize this for "User Stories" tables)
        for pattern in self.story_section_patterns:
            # Try to find heading with this text
            for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                heading_text = heading.get_text().strip()
                if pattern.lower() in heading_text.lower():
                    # Find table after this heading
                    table = heading.find_next('table')
                    if table:
                        # Verify this table has story-related headers
                        headers = self._extract_table_headers(table)
                        if self._is_story_table(headers) or 'user story' in ' '.join(headers).lower():
                            logger.debug(f"Found story table by heading: {heading_text}")
                            return table
        
        # Strategy 3: Find any table with story-related headers (but prefer tables with "user story" in headers)
        story_tables = []
        for table in soup.find_all('table'):
            headers = self._extract_table_headers(table)
            if self._is_story_table(headers):
                # Prefer tables with "user story" in headers
                header_text = ' '.join(headers).lower()
                if 'user story' in header_text:
                    logger.debug("Found story table by header analysis (has 'user story')")
                    return table
                story_tables.append(table)
        
        # Return first story table found if no "user story" table exists
        if story_tables:
            logger.debug("Found story table by header analysis")
            return story_tables[0]
        
        # If we found a table with "user story" but no "acceptance criteria", use it as fallback
        if potential_table:
            logger.debug("Using table with 'user story' header (acceptance criteria column may be missing or named differently)")
            return potential_table
        
        return None
    
    def _is_story_table(self, headers: List[str]) -> bool:
        """Check if table headers indicate this is a story table"""
        header_text = ' '.join(headers).lower()
        story_keywords = ['story', 'title', 'description', 'acceptance']
        return any(keyword in header_text for keyword in story_keywords)
    
    def _extract_table_headers(self, table: Any) -> List[str]:
        """Extract column headers from table"""
        headers = []
        thead = table.find('thead')
        if thead:
            for th in thead.find_all(['th', 'td']):
                headers.append(th.get_text().strip())
        else:
            # Try first row as headers
            first_row = table.find('tr')
            if first_row:
                for cell in first_row.find_all(['th', 'td']):
                    headers.append(cell.get_text().strip())
        return headers
    
    def _parse_table_rows(self, table: Any, epic_key: str) -> List[StoryPlan]:
        """Parse table rows into StoryPlan objects
        
        Uses simpler logic matching simulate_prd_extraction.py exactly:
        - rows[0] is the header row
        - Process rows starting from rows[1:] (skip header row)
        """
        stories = []
        
        # Extract headers - exactly matching simulation: rows[0] with th tags
        rows = table.find_all("tr")
        if not rows:
            logger.warning("No rows found in story table")
            return []
        
        # Get header row (first row, matching simulation logic exactly)
        header_cells = rows[0].find_all("th")
        if not header_cells:
            logger.warning("No header row found in story table (first row has no th tags)")
            return []
        
        # Extract header texts (matching simulation exactly)
        header_texts = [th.get_text(" ", strip=True) for th in header_cells]
        if not header_texts:
            logger.warning("No headers found in story table")
            return []
        
        logger.debug(f"Table headers: {header_texts}")
        
        # Helper function to get column index by fragment (matching simulation logic exactly)
        def col_index(fragment: str):
            frag = fragment.lower()
            for idx, h in enumerate(header_texts):
                if frag in h.lower():
                    return idx
            return None
        
        # Extract column indices (matching simulation exactly)
        idx_number = col_index("#")
        idx_story = col_index("user story")
        idx_importance = col_index("importance")
        idx_mockup = col_index("mockup")
        idx_ac = col_index("acceptance criteria")
        
        logger.debug(f"Column indices - story: {idx_story}, acceptance_criteria: {idx_ac}, number: {idx_number}")
        
        if idx_story is None:
            logger.warning("Required 'user story' column not found in table headers")
            logger.debug(f"Available headers: {header_texts}")
            return []
        
        # Step 1: Collect all row data and acceptance criteria
        row_data_list = []
        skipped_rows = 0
        for r in rows[1:]:
            tds = r.find_all("td")
            if not tds:
                skipped_rows += 1
                continue
            
            # Heuristic: only keep "full" rows that look like data rows (matching simulation logic)
            if len(tds) < len(header_texts):
                skipped_rows += 1
                logger.debug(f"Skipping row with {len(tds)} cells (expected {len(header_texts)})")
                continue
            
            # Helper function to get cell by index (matching simulation logic exactly)
            def cell(idx):
                if idx is None or idx >= len(tds):
                    return None
                return tds[idx]
            
            # Extract values using _clean_text for most cells (matching simulation exactly)
            number = self._clean_text(cell(idx_number)) or None
            story_cell = cell(idx_story)
            importance = self._clean_text(cell(idx_importance)) or None
            # Use _extract_cell_text for mockup column to handle images
            mockup_cell = cell(idx_mockup)
            mockup_raw = self._extract_cell_text(mockup_cell) if mockup_cell else None
            
            # Story / description: use _clean_text (joins with spaces, matching simulation)
            story_text = self._clean_text(story_cell) if story_cell else ""
            
            # Acceptance criteria: extract text while preserving HTML structure
            ac_cell = cell(idx_ac)
            ac_text = self._extract_text_with_structure(ac_cell) if ac_cell else None
            
            # Build row_data in the format expected by _create_story_from_row
            row_data = {
                'title': story_text or None,
                'description': story_text or None,  # Will be processed in _create_story_from_row
                'acceptance_criteria': ac_text,
                'mockup': mockup_raw or None,
            }
            
            row_data_list.append(row_data)
        
        logger.debug(f"Collected {len(row_data_list)} data rows (skipped {skipped_rows} rows)")
        
        if not row_data_list:
            logger.warning("No valid data rows found in story table")
            logger.debug(f"Total rows in table: {len(rows)}, header row: 1, data rows processed: {len(row_data_list)}")
            return []
        
        # Create stories from row data
        for idx, row_data in enumerate(row_data_list):
            # Debug logging for first few rows
            if len(stories) < 2:
                title_preview = row_data.get("title", "")[:50] if row_data.get("title") else None
                logger.debug(f"Row data: title='{title_preview}'")
            
            # Create StoryPlan from row data
            story = self._create_story_from_row(row_data, epic_key)
            if story:
                stories.append(story)
            else:
                logger.debug(f"Row {idx+1} did not produce a valid story (likely missing title)")
        
        logger.debug(f"Created {len(stories)} stories from {len(row_data_list)} data rows")
        return stories
    
    def _normalize_headers(self, headers: List[str]) -> Dict[str, str]:
        """Normalize header names to standard keys"""
        mapping = {}
        for header in headers:
            header_lower = header.lower().strip()
            
            # Map to standard keys
            # Check for "user story" first (common in PRD tables)
            if 'user story' in header_lower or 'user-story' in header_lower:
                mapping[header_lower] = 'title'
            elif 'title' in header_lower or 'summary' in header_lower or 'name' in header_lower:
                mapping[header_lower] = 'title'
            elif 'description' in header_lower or 'desc' in header_lower:
                mapping[header_lower] = 'description'
            elif 'acceptance' in header_lower or 'criteria' in header_lower or 'ac' in header_lower:
                mapping[header_lower] = 'acceptance_criteria'
            elif 'mockup' in header_lower or 'design' in header_lower or 'figma' in header_lower:
                mapping[header_lower] = 'mockup'
            else:
                mapping[header_lower] = header_lower
        
        return mapping
    
    def _clean_text(self, cell: Any) -> str:
        """Extract and clean text from a BeautifulSoup node (matching simulation logic)
        Joins with spaces for normal text extraction
        """
        if cell is None:
            return ""
        # Remove script and style elements
        for script in cell(["script", "style"]):
            script.decompose()
        # Use stripped_strings and join with spaces (matching _clean_text from simulation)
        return " ".join(cell.stripped_strings)
    
    def _extract_text_with_structure(self, cell: Any) -> str:
        """
        Extract text from HTML cell while preserving structure and styling (paragraphs, lists, 
        line breaks, bold, italic, links, etc.) as Markdown.
        
        Args:
            cell: BeautifulSoup element (td cell)
            
        Returns:
            Text string with structure and styling preserved as Markdown
        """
        if cell is None:
            return ""
        
        lines = []
        
        def process_element(elem, in_bold=False, in_italic=False, in_code=False):
            """Recursively process HTML elements to preserve structure and styling"""
            if elem is None:
                return
            
            # Handle text nodes
            if isinstance(elem, str):
                text = elem.strip()
                if text:
                    # Apply current formatting
                    if in_code:
                        lines.append(f"`{text}`")
                    elif in_italic and in_bold:
                        lines.append(f"***{text}***")
                    elif in_bold:
                        lines.append(f"**{text}**")
                    elif in_italic:
                        lines.append(f"*{text}*")
                    else:
                        lines.append(text)
                return
            
            tag_name = elem.name.lower() if elem.name else None
            
            # Handle images (both <img> tags and Confluence ac:image macros)
            if tag_name == 'img':
                src = elem.get('src', '')
                if src:
                    # Check if it's a Confluence attachment URL
                    if '/download/attachments/' in src or '/wiki/download/attachments/' in src:
                        alt = elem.get('alt', '')
                        # Try to extract filename from URL
                        if not alt and '/attachments/' in src:
                            url_parts = src.split('/')
                            if len(url_parts) > 0:
                                potential_filename = url_parts[-1]
                                if '.' in potential_filename:
                                    alt = potential_filename
                        if alt:
                            lines.append(f"[Image: {alt}]({src})")
                        else:
                            lines.append(f"[Image]({src})")
                    else:
                        # External image
                        alt = elem.get('alt', '')
                        if alt:
                            lines.append(f"[Image: {alt}]({src})")
                        else:
                            lines.append(f"[Image]({src})")
            elif tag_name == 'ac:image':
                # Handle Confluence ac:image macros
                filename = None
                # Try to find attachment reference
                ac_link = elem.find('ac:link')
                if ac_link:
                    ri_attachment = ac_link.find('ri:attachment')
                    if ri_attachment:
                        filename = ri_attachment.get('ri:filename', '')
                
                # Also check for ac:image with direct ri:attachment
                if not filename:
                    ri_attachment_direct = elem.find('ri:attachment')
                    if ri_attachment_direct:
                        filename = ri_attachment_direct.get('ri:filename', '')
                
                # Check for ac:parameter with image data as fallback
                if not filename:
                    ac_parameter = elem.find('ac:parameter', {'ac:name': 'alt'})
                    if ac_parameter:
                        filename = ac_parameter.get_text(strip=True)
                
                if filename:
                    # Try to construct Confluence attachment URL if we have page context
                    if hasattr(self, '_page_id') and self._page_id:
                        # Construct attachment URL: /wiki/download/attachments/{pageId}/{filename}
                        attachment_url = f"/wiki/download/attachments/{self._page_id}/{filename}"
                        lines.append(f"[Image: {filename}]({attachment_url})")
                    else:
                        # Just filename if no page context
                        lines.append(f"[Image: {filename}]")
            # Handle styling elements
            elif tag_name in ['strong', 'b']:
                for child in elem.children:
                    process_element(child, in_bold=True, in_italic=in_italic, in_code=in_code)
            elif tag_name in ['em', 'i']:
                for child in elem.children:
                    process_element(child, in_bold=in_bold, in_italic=True, in_code=in_code)
            elif tag_name in ['code', 'tt']:
                for child in elem.children:
                    process_element(child, in_bold=in_bold, in_italic=in_italic, in_code=True)
            elif tag_name == 'a':
                # Handle links
                href = elem.get('href', '')
                link_parts = []
                for child in elem.children:
                    if isinstance(child, str):
                        link_parts.append(child.strip())
                    else:
                        link_parts.append(child.get_text(" ", strip=True))
                link_text = " ".join(filter(None, link_parts)).strip()
                if not link_text:
                    link_text = href
                
                # Convert to markdown link format
                if href:
                    lines.append(f"[{link_text}]({href})")
                else:
                    if link_text:
                        lines.append(link_text)
            elif tag_name == 'p':
                # Paragraph: add newline before if not first, process content, add newline after
                if lines and lines[-1]:
                    lines.append('')
                for child in elem.children:
                    process_element(child, in_bold=in_bold, in_italic=in_italic, in_code=in_code)
                if lines and lines[-1]:
                    lines.append('')
            elif tag_name in ['ul', 'ol']:
                # List: add newline before, process items, add newline after
                if lines and lines[-1]:
                    lines.append('')
                for li in elem.find_all('li', recursive=False):
                    process_element(li, in_bold=in_bold, in_italic=in_italic, in_code=in_code)
                if lines and lines[-1]:
                    lines.append('')
            elif tag_name == 'li':
                # List item: process content
                item_parts = []
                for child in elem.children:
                    if isinstance(child, str):
                        item_parts.append(child.strip())
                    elif child.name not in ['ul', 'ol']:  # Don't recurse into nested lists here
                        # Extract styled text from child
                        styled_text = self._extract_styled_text_from_element(child)
                        if styled_text:
                            item_parts.append(styled_text)
                text = " ".join(filter(None, item_parts))
                if text:
                    lines.append(f"- {text}")
            elif tag_name == 'br':
                # Line break: add empty line
                lines.append('')
            elif tag_name == 'div':
                # Div: process children, may add separation
                for child in elem.children:
                    process_element(child, in_bold=in_bold, in_italic=in_italic, in_code=in_code)
            else:
                # Other elements: just get text with styling
                styled_text = self._extract_styled_text_from_element(elem)
                if styled_text:
                    lines.append(styled_text)
        
        # Process all children of the cell
        for child in cell.children:
            process_element(child)
        
        # Join lines, but clean up excessive blank lines
        result_lines = []
        prev_blank = False
        for line in lines:
            is_blank = not line.strip()
            if is_blank and prev_blank:
                continue  # Skip consecutive blank lines
            result_lines.append(line)
            prev_blank = is_blank
        
        return '\n'.join(result_lines).strip()
    
    def _extract_styled_text_from_element(self, elem: Any) -> str:
        """Extract text from an element preserving inline styling as Markdown"""
        if elem is None:
            return ""
        
        if isinstance(elem, str):
            return elem.strip()
        
        tag_name = elem.name.lower() if elem.name else None
        
        # Handle styling elements
        if tag_name in ['strong', 'b']:
            text = ''.join([self._extract_styled_text_from_element(c) for c in elem.children])
            return f"**{text}**" if text else ""
        elif tag_name in ['em', 'i']:
            text = ''.join([self._extract_styled_text_from_element(c) for c in elem.children])
            return f"*{text}*" if text else ""
        elif tag_name in ['code', 'tt']:
            text = ''.join([self._extract_styled_text_from_element(c) for c in elem.children])
            return f"`{text}`" if text else ""
        elif tag_name == 'a':
            href = elem.get('href', '')
            link_text = ''.join([self._extract_styled_text_from_element(c) for c in elem.children]).strip()
            if not link_text:
                link_text = href
            if href:
                return f"[{link_text}]({href})"
            return link_text
        else:
            # For other elements, recursively extract text
            return ''.join([self._extract_styled_text_from_element(c) for c in elem.children])
    
    def _extract_cell_text_simple(self, cell: Any) -> str:
        """Extract text content from table cell using simple stripped_strings approach
        Preserves newlines for structure (used for acceptance criteria cells only)
        """
        if cell is None:
            return ""
        # Remove script and style elements
        for script in cell(["script", "style"]):
            script.decompose()
        # Use stripped_strings and join with newlines to preserve structure
        return "\n".join(cell.stripped_strings)
    
    def _extract_cell_text(self, cell: Any) -> str:
        """Extract text content from table cell, handling HTML formatting, images, and links"""
        # Remove script and style elements
        for script in cell(["script", "style"]):
            script.decompose()
        
        # Extract images and links before getting text
        image_links = []
        figma_links = []
        other_links = []
        
        # Extract images (both <img> tags and Confluence image attachments)
        for img in cell.find_all(['img', 'ac:image']):
            # Handle standard img tags
            if img.name == 'img':
                src = img.get('src', '')
                if src:
                    # Check if it's a Confluence attachment URL
                    if '/download/attachments/' in src or '/wiki/download/attachments/' in src:
                        # Extract attachment name if available
                        alt = img.get('alt', '')
                        # Try to extract filename from URL
                        if not alt and '/attachments/' in src:
                            # Extract filename from URL like: /wiki/download/attachments/PAGEID/filename.png
                            url_parts = src.split('/')
                            if len(url_parts) > 0:
                                potential_filename = url_parts[-1]
                                if '.' in potential_filename:
                                    alt = potential_filename
                        if alt:
                            image_links.append(f"[Image: {alt}]({src})")
                        else:
                            image_links.append(f"[Image]({src})")
                    else:
                        # External image
                        alt = img.get('alt', '')
                        if alt:
                            image_links.append(f"[Image: {alt}]({src})")
                        else:
                            image_links.append(f"[Image]({src})")
            
            # Handle Confluence ac:image macros
            elif img.name == 'ac:image':
                filename = None
                # Try to find attachment reference
                ac_link = img.find('ac:link')
                if ac_link:
                    ri_attachment = ac_link.find('ri:attachment')
                    if ri_attachment:
                        filename = ri_attachment.get('ri:filename', '')
                
                # Also check for ac:image with direct ri:attachment
                if not filename:
                    ri_attachment_direct = img.find('ri:attachment')
                    if ri_attachment_direct:
                        filename = ri_attachment_direct.get('ri:filename', '')
                
                # Check for ac:parameter with image data as fallback
                if not filename:
                    ac_parameter = img.find('ac:parameter', {'ac:name': 'alt'})
                    if ac_parameter:
                        filename = ac_parameter.get_text(strip=True)
                
                if filename:
                    # Try to construct Confluence attachment URL if we have page context
                    if hasattr(self, '_page_id') and self._page_id:
                        # Construct attachment URL: /wiki/download/attachments/{pageId}/{filename}
                        attachment_url = f"/wiki/download/attachments/{self._page_id}/{filename}"
                        image_links.append(f"[Image: {filename}]({attachment_url})")
                    else:
                        # Just filename if no page context
                        image_links.append(f"[Image: {filename}]")
        
        # Extract links (especially Figma links)
        for link in cell.find_all('a', href=True):
            href = link.get('href', '')
            link_text = link.get_text(strip=True) or href
            
            # Check for Figma links
            if 'figma.com' in href.lower():
                figma_links.append(f"[Figma: {link_text}]({href})")
            else:
                # Other links
                if link_text != href:
                    other_links.append(f"[{link_text}]({href})")
                else:
                    other_links.append(href)
        
        # Get text content
        text = cell.get_text(separator=' ', strip=True)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Remove URLs from plain text if they're already extracted as links
        # This prevents duplicate display of the same URL
        all_extracted_urls = []
        for link_info in figma_links + other_links:
            # Extract URL from markdown link format [text](url)
            url_match = re.search(r'\(([^\)]+)\)', link_info)
            if url_match:
                all_extracted_urls.append(url_match.group(1))
            # Also check if it's a plain URL
            elif link_info.startswith('http'):
                all_extracted_urls.append(link_info)
        
        # Remove extracted URLs from plain text to avoid duplicates
        for url in all_extracted_urls:
            # Remove the URL from text (handle both with and without trailing punctuation)
            text = re.sub(re.escape(url) + r'[.,;:!?]?', '', text, flags=re.IGNORECASE)
            text = text.strip()
        
        # Combine text with extracted media/links
        parts = []
        if text:
            parts.append(text)
        if figma_links:
            parts.extend(figma_links)
        if image_links:
            parts.extend(image_links)
        if other_links:
            parts.extend(other_links)
        
        return '\n'.join(parts) if parts else ''
    
    def _create_story_from_row(self, row_data: Dict[str, str], epic_key: str) -> Optional[StoryPlan]:
        """Create a StoryPlan object from table row data"""
        try:
            # Extract required fields
            title = row_data.get('title', '').strip()
            if not title:
                logger.warning("Story row missing title, skipping")
                return None
            
            description = row_data.get('description', '').strip()
            if not description:
                description = title  # Use title as fallback
            
            # Process title and description: Extract title (before "As a...") and move user story to description
            # Pattern to match "As a..." at the start of the user story part
            as_a_pattern = r'\s*(As\s+(?:an?\s+)?[^,]+,\s*I\s+want\s+to\s+[^.]*(?:\s+so\s+that\s+[^.]*)?)\.?'
            
            # Find where "As a..." starts in the title
            as_a_match = re.search(as_a_pattern, title, re.IGNORECASE)
            
            if as_a_match:
                # Get the position where "As a..." starts
                as_a_start = as_a_match.start()
                
                # Extract title (everything before "As a...")
                title_part = title[:as_a_start].strip()
                
                # Extract user story (from "As a..." onwards)
                user_story_text = as_a_match.group(1).strip()
                
                # Use title_part as summary (or fallback to original if no title found)
                if title_part:
                    summary = title_part
                else:
                    # If no title before "As a...", remove the user story part
                    summary = re.sub(as_a_pattern, '', title, flags=re.IGNORECASE).strip()
                
                # Clean up summary
                summary = re.sub(r'\s+', ' ', summary).strip()
                
                # Ensure summary is under 255 characters
                if len(summary) > 255:
                    # Truncate at word boundary
                    truncated = summary[:252]
                    last_space = truncated.rfind(' ')
                    if last_space > 200:  # Only truncate at word if we have enough content
                        summary = truncated[:last_space] + "..."
                    else:
                        summary = truncated + "..."
                    logger.warning(f"Summary truncated to {len(summary)} characters to meet JIRA limit")
                
                # Add user story to description if not already there
                if user_story_text.lower() not in description.lower():
                    if description:
                        description = f"{user_story_text}\n\n{description}"
                    else:
                        description = user_story_text
            else:
                # No user story format found, use title as-is but ensure it's under 255 chars
                summary = title
                if len(summary) > 255:
                    # Truncate at word boundary
                    truncated = summary[:252]
                    last_space = truncated.rfind(' ')
                    if last_space > 200:
                        summary = truncated[:last_space] + "..."
                    else:
                        summary = truncated + "..."
                    logger.warning(f"Summary truncated to {len(summary)} characters to meet JIRA limit")
            
            # Append mockup content if available
            mockup = row_data.get('mockup', '').strip()
            if mockup:
                description += f"\n\n**Mockup:**\n{mockup}"
            
            # Append acceptance criteria to description if available
            acceptance_criteria_text = row_data.get('acceptance_criteria', '').strip()
            if acceptance_criteria_text:
                description += f"\n\n**Acceptance Criteria:**\n{acceptance_criteria_text}"
            
            # Create StoryPlan (use processed summary, not original title)
            story = StoryPlan(
                summary=summary,  # Use processed summary (title extracted, user story moved to description)
                description=description,
                acceptance_criteria=[],  # Empty list since acceptance criteria is in description
                test_cases=[],  # Will be generated later if needed
                tasks=[],
                epic_key=epic_key,
                priority="medium"
            )
            
            return story
            
        except Exception as e:
            logger.error(f"Error creating story from row data: {e}")
            return None
