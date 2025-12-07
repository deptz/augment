import requests
import re
from typing import Dict, List, Optional, Any, Tuple
import logging
from urllib.parse import urljoin
import tempfile
import os
from io import BytesIO

logger = logging.getLogger(__name__)


class JiraClient:
    """Jira API client for fetching and updating tickets"""
    
    def __init__(self, server_url: str, username: str, api_token: str, prd_custom_field: str, rfc_custom_field: Optional[str] = None, test_case_custom_field: Optional[str] = None, mandays_custom_field: Optional[str] = None):
        self.server_url = server_url.rstrip('/')
        self.auth = (username, api_token)
        self.prd_custom_field = prd_custom_field
        self.rfc_custom_field = rfc_custom_field
        self.test_case_custom_field = test_case_custom_field
        self.mandays_custom_field = mandays_custom_field
        
        logger.info(f"🔍 JiraClient initialized:")
        logger.info(f"🔍   server_url: {self.server_url}")
        logger.info(f"🔍   username: {username}")
        logger.info(f"🔍   prd_custom_field: {self.prd_custom_field}")
        logger.info(f"🔍   rfc_custom_field: {self.rfc_custom_field}")
        logger.info(f"🔍   test_case_custom_field: {self.test_case_custom_field}")
        logger.info(f"🔍   mandays_custom_field: {self.mandays_custom_field}")
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def _get_fields_list(self) -> str:
        """Get the list of fields to fetch from Jira API"""
        base_fields = ['key', 'summary', 'description', 'status', 'parent', 'assignee', 'created', 'updated']
        custom_fields = [self.prd_custom_field]
        
        if self.rfc_custom_field:
            custom_fields.append(self.rfc_custom_field)
            
        if self.test_case_custom_field:
            custom_fields.append(self.test_case_custom_field)
            
        if self.mandays_custom_field:
            custom_fields.append(self.mandays_custom_field)
            
        return ','.join(base_fields + custom_fields)
    
    def search_tickets(self, jql: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """Search for tickets using JQL with the new enhanced search API"""
        # Use the new enhanced search endpoint
        url = urljoin(self.server_url, '/rest/api/3/search/jql')
        
        # Check if JQL is too long for GET request (usually around 2048 chars)
        if len(jql) > 2000:
            return self._search_tickets_post(url, jql, max_results)
        else:
            return self._search_tickets_get(url, jql, max_results)
    
    def _search_tickets_get(self, url: str, jql: str, max_results: int) -> List[Dict[str, Any]]:
        """Search using GET request for shorter JQL queries"""
        params = {
            'jql': jql,
            'maxResults': max_results,
            'fields': self._get_fields_list()
        }
        
        all_issues = []
        next_page_token = None
        
        try:
            while True:
                if next_page_token:
                    params['nextPageToken'] = next_page_token
                
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                issues = data.get('issues', [])
                all_issues.extend(issues)
                
                # Check if this is the last page
                if data.get('isLast', True) or len(all_issues) >= max_results:
                    break
                
                # Get next page token if available
                next_page_token = data.get('nextPageToken')
                if not next_page_token:
                    break
                
                # Update max results for next request
                remaining = max_results - len(all_issues)
                if remaining > 0:
                    params['maxResults'] = min(remaining, 100)
                else:
                    break
            
            return all_issues[:max_results]  # Ensure we don't exceed max_results
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to search tickets: {e}")
            # Fallback to deprecated API if enhanced search fails
            logger.warning("Falling back to deprecated search API")
            return self._search_tickets_deprecated(jql, max_results)
    
    def _search_tickets_post(self, url: str, jql: str, max_results: int) -> List[Dict[str, Any]]:
        """Search using POST request for longer JQL queries"""
        payload = {
            'jql': jql,
            'maxResults': max_results,
            'fields': [
                'key', 'summary', 'description', 'status', 'parent', 'assignee',
                self.prd_custom_field, 'created', 'updated'
            ]
        }
        
        all_issues = []
        next_page_token = None
        
        try:
            while True:
                if next_page_token:
                    payload['nextPageToken'] = next_page_token
                
                response = self.session.post(url, json=payload, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                issues = data.get('issues', [])
                all_issues.extend(issues)
                
                # Check if this is the last page
                if data.get('isLast', True) or len(all_issues) >= max_results:
                    break
                
                # Get next page token if available
                next_page_token = data.get('nextPageToken')
                if not next_page_token:
                    break
                
                # Update max results for next request
                remaining = max_results - len(all_issues)
                if remaining > 0:
                    payload['maxResults'] = min(remaining, 100)
                else:
                    break
            
            return all_issues[:max_results]  # Ensure we don't exceed max_results
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to search tickets with POST: {e}")
            # Fallback to deprecated API if enhanced search fails
            logger.warning("Falling back to deprecated search API")
            return self._search_tickets_deprecated(jql, max_results)
    
    def _search_tickets_deprecated(self, jql: str, max_results: int) -> List[Dict[str, Any]]:
        """Fallback method using deprecated search API"""
        url = urljoin(self.server_url, '/rest/api/3/search')
        
        params = {
            'jql': jql,
            'maxResults': max_results,
            'fields': self._get_fields_list()
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            return data.get('issues', [])
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to search tickets with deprecated API: {e}")
            raise
    
    def get_ticket(self, ticket_key: str) -> Optional[Dict[str, Any]]:
        """Get detailed information for a specific ticket"""
        url = urljoin(self.server_url, f'/rest/api/3/issue/{ticket_key}')
        
        params = {
            'fields': self._get_fields_list() + ',issuelinks'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get ticket {ticket_key}: {e}")
            return None
    
    def get_issue_links(self, ticket_key: str) -> List[Dict[str, Any]]:
        """Get issue links for a specific ticket"""
        try:
            ticket_data = self.get_ticket(ticket_key)
            if not ticket_data:
                return []
            
            fields = ticket_data.get('fields', {})
            issue_links = fields.get('issuelinks', [])
            
            logger.debug(f"Found {len(issue_links)} issue links for {ticket_key}")
            return issue_links
            
        except Exception as e:
            logger.error(f"Failed to get issue links for {ticket_key}: {e}")
            return []
    
    def find_story_tickets(self, ticket_key: str) -> List[Dict[str, Any]]:
        """Find ALL story tickets linked via 'split from' or 'split to' relationships"""
        try:
            issue_links = self.get_issue_links(ticket_key)
            story_tickets = []
            
            for link in issue_links:
                link_type = link.get('type', {})
                link_name = link_type.get('name', '').lower()
                
                # Check for split relationships
                if 'split' in link_name:
                    # Check both inward and outward links
                    inward_issue = link.get('inwardIssue')
                    outward_issue = link.get('outwardIssue')
                    
                    # Get the linked issue (could be inward or outward)
                    linked_issue = inward_issue or outward_issue
                    if linked_issue:
                        issue_type = linked_issue.get('fields', {}).get('issuetype', {}).get('name', '').lower()
                        
                        # If the linked issue is a story, get its full data
                        if 'story' in issue_type:
                            story_key = linked_issue['key']
                            logger.debug(f"Found story ticket {story_key} linked to {ticket_key}")
                            story_data = self.get_ticket(story_key)
                            if story_data:
                                story_tickets.append(story_data)
            
            logger.debug(f"Found {len(story_tickets)} story ticket(s) via split relations for {ticket_key}")
            return story_tickets
            
        except Exception as e:
            logger.error(f"Failed to find story tickets for {ticket_key}: {e}")
            return []
    
    def find_story_ticket(self, ticket_key: str) -> Optional[Dict[str, Any]]:
        """Find the first story ticket linked via 'split from' or 'split to' relation (legacy method)"""
        story_tickets = self.find_story_tickets(ticket_key)
        return story_tickets[0] if story_tickets else None
    
    def update_ticket_description(self, ticket_key: str, description: str, dry_run: bool = True) -> bool:
        """Update the description of a ticket"""
        if dry_run:
            logger.info(f"DRY RUN: Would update {ticket_key} with description:")
            logger.info(description)
            return True
        
        url = urljoin(self.server_url, f'/rest/api/3/issue/{ticket_key}')
        
        # Convert markdown description to ADF format
        description_adf = self._convert_markdown_to_adf(description)
        
        payload = {
            'fields': {
                'description': description_adf
            }
        }
        
        try:
            response = self.session.put(url, json=payload, timeout=30)
            response.raise_for_status()
            
            logger.info(f"Successfully updated ticket {ticket_key}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to update ticket {ticket_key}: {e}")
            return False

    def append_to_ticket_description(self, ticket_key: str, additional_text: str) -> bool:
        """Append text to existing JIRA ticket description"""
        try:
            # Get current ticket
            ticket = self.get_ticket(ticket_key)
            if not ticket:
                logger.error(f"Ticket {ticket_key} not found")
                return False
            
            current_description = ticket.get('fields', {}).get('description', '')
            
            # Handle ADF format
            if isinstance(current_description, dict):
                # Extract text from ADF
                current_text = self._extract_text_from_adf(current_description)
                # Append new content
                updated_text = current_text + additional_text
            else:
                # Handle plain text
                current_text = str(current_description) if current_description else ""
                updated_text = current_text + additional_text
            
            # Create ADF format for the updated description
            adf_content = {
                'type': 'doc',
                'version': 1,
                'content': [
                    {
                        'type': 'paragraph',
                        'content': [
                            {
                                'type': 'text',
                                'text': updated_text
                            }
                        ]
                    }
                ]
            }
            
            # Update the ticket
            url = urljoin(self.server_url, f'/rest/api/3/issue/{ticket_key}')
            payload = {
                'fields': {
                    'description': adf_content
                }
            }
            
            response = self.session.put(url, json=payload, timeout=30)
            response.raise_for_status()
            
            logger.info(f"✅ Successfully appended to description for {ticket_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error appending to ticket {ticket_key} description: {str(e)}")
            return False

    def update_mandays_custom_field(self, ticket_key: str, mandays: float) -> bool:
        """Update the mandays custom field with estimation value"""
        try:
            if not self.mandays_custom_field:
                logger.warning("No mandays custom field configured, skipping update")
                return False
            
            logger.info(f"Attempting to update mandays custom field {self.mandays_custom_field} on ticket {ticket_key} with value {mandays}")
            
            # Update the ticket with mandays value (number field)
            url = urljoin(self.server_url, f'/rest/api/3/issue/{ticket_key}')
            
            # Create payload with numeric value
            payload = {
                'fields': {
                    self.mandays_custom_field: mandays
                }
            }
            
            response = self.session.put(url, json=payload, timeout=30)
            response.raise_for_status()
            
            logger.info(f"Successfully updated mandays custom field for {ticket_key}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating mandays custom field for {ticket_key}: {str(e)}")
            return False

    def update_test_case_custom_field(self, ticket_key: str, test_cases_content: str) -> bool:
        """Update the test case custom field with formatted test cases"""
        try:
            if not self.test_case_custom_field:
                logger.warning("No test case custom field configured, falling back to description append")
                return self.append_to_ticket_description(ticket_key, test_cases_content)
            
            logger.info(f"🔍 Attempting to update custom field {self.test_case_custom_field} on ticket {ticket_key}")
            logger.info(f"🔍 Content length: {len(test_cases_content)} characters")
            
            # Convert plain text to simple ADF format as required by JIRA
            logger.info("🔍 Converting plain text content to Atlassian Document Format (ADF)")
            test_cases_adf = self._convert_plain_text_to_adf(test_cases_content)
            logger.info(f"🔍 ADF conversion completed, structure keys: {list(test_cases_adf.keys())}")
            
            # Update the ticket with test cases in custom field
            url = urljoin(self.server_url, f'/rest/api/3/issue/{ticket_key}')
            logger.info(f"🔍 Update URL: {url}")
            
            # Create payload with ADF content
            payload = {
                'fields': {
                    self.test_case_custom_field: test_cases_adf
                }
            }
            logger.info(f"🔍 Payload structure: ADF document with {len(test_cases_adf.get('content', []))} content blocks")
            
            response = self.session.put(url, json=payload, timeout=30)
            
            logger.info(f"🔍 Response status: {response.status_code}")
            logger.info(f"🔍 Response headers: {dict(response.headers)}")
            logger.info(f"🔍 Response body: {response.text}")
            
            response.raise_for_status()
            
            logger.info(f"✅ Successfully updated test case custom field for {ticket_key}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating test case custom field for {ticket_key}: {str(e)}")
            logger.error(f"❌ Exception type: {type(e).__name__}")
            # Fallback to description append if custom field update fails
            logger.warning("Falling back to description append method")
            return self.append_to_ticket_description(ticket_key, test_cases_content)

    def _convert_plain_text_to_adf(self, plain_text_content: str) -> Dict[str, Any]:
        """Convert plain text test cases to simple Atlassian Document Format (ADF)"""
        try:
            logger.debug(f"🔍 Converting plain text to ADF, input has {len(plain_text_content)} characters")
            
            # Split content into lines and create simple paragraph blocks
            lines = plain_text_content.strip().split('\n')
            content_blocks = []
            
            for line in lines:
                line = line.strip()
                if line:  # Skip empty lines
                    content_blocks.append({
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": line
                            }
                        ]
                    })
            
            adf_doc = {
                "type": "doc",
                "version": 1,
                "content": content_blocks
            }
            
            logger.debug(f"🔍 Plain text ADF conversion complete: {len(content_blocks)} paragraph blocks generated")
            return adf_doc
            
        except Exception as e:
            logger.error(f"Error converting plain text to ADF: {str(e)}")
            # Fallback to single paragraph
            return {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": plain_text_content
                            }
                        ]
                    }
                ]
            }

    def _convert_markdown_to_adf(self, markdown_content: str) -> Dict[str, Any]:
        """Convert markdown formatted content to Atlassian Document Format (ADF)"""
        try:
            logger.debug(f"🔍 Converting markdown to ADF, input has {len(markdown_content)} characters")
            logger.debug(f"🔍 Input preview: {repr(markdown_content[:200])}")
            content_blocks = []
            lines = markdown_content.split('\n')
            logger.debug(f"🔍 Processing {len(lines)} lines for ADF conversion")
            
            i = 0
            in_code_block = False
            code_block_lines = []
            code_block_language = ""
            current_bullet_list = []
            
            def parse_bold_text(text: str) -> list:
                """Parse bold formatting (**text**) from text"""
                if '**' not in text:
                    return [{"type": "text", "text": text}] if text else []
                
                parts = []
                segments = text.split('**')
                for idx, segment in enumerate(segments):
                    if not segment:
                        continue
                    if idx % 2 == 0:
                        # Normal text
                        parts.append({"type": "text", "text": segment})
                    else:
                        # Bold text
                        parts.append({"type": "text", "text": segment, "marks": [{"type": "strong"}]})
                return parts
            
            def parse_inline_formatting(text: str) -> list:
                """Parse inline markdown formatting (bold, links, etc.) from text"""
                if not text:
                    return []
                
                parts = []
                
                # First, extract all markdown links [text](url) or [Figma: text](url)
                # Pattern: [text](url) or [Figma: text](url)
                link_pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
                link_matches = list(re.finditer(link_pattern, text))
                
                if not link_matches and '**' not in text:
                    # No links or bold, just return plain text
                    return [{"type": "text", "text": text}]
                
                # Process text with links and bold formatting
                last_pos = 0
                for link_match in link_matches:
                    # Add text before the link
                    before_text = text[last_pos:link_match.start()]
                    if before_text:
                        parts.extend(parse_bold_text(before_text))
                    
                    # Add the link
                    link_text = link_match.group(1)
                    link_url = link_match.group(2)
                    
                    # Check if link text has bold formatting
                    if '**' in link_text:
                        # Parse bold within link text
                        link_parts = parse_bold_text(link_text)
                        # Wrap each part in link mark
                        for part in link_parts:
                            if part.get('type') == 'text':
                                # Combine marks: bold + link
                                marks = part.get('marks', [])
                                marks.append({"type": "link", "attrs": {"href": link_url}})
                                part['marks'] = marks
                                parts.append(part)
                    else:
                        # Simple link without bold
                        parts.append({
                            "type": "text",
                            "text": link_text,
                            "marks": [{"type": "link", "attrs": {"href": link_url}}]
                        })
                    
                    last_pos = link_match.end()
                
                # Add remaining text after last link
                remaining_text = text[last_pos:]
                if remaining_text:
                    parts.extend(parse_bold_text(remaining_text))
                
                # If no links were found, just parse bold
                if not link_matches:
                    parts = parse_bold_text(text)
                
                return parts if parts else [{"type": "text", "text": text}]
            
            def flush_bullet_list():
                """Flush current bullet list to content blocks"""
                nonlocal current_bullet_list
                if current_bullet_list:
                    list_items = []
                    for item_text in current_bullet_list:
                        item_content = parse_inline_formatting(item_text)
                        if item_content:
                            list_items.append({
                                "type": "listItem",
                                "content": [{
                                    "type": "paragraph",
                                    "content": item_content
                                }]
                            })
                    if list_items:
                        content_blocks.append({
                            "type": "bulletList",
                            "content": list_items
                        })
                    current_bullet_list = []
            
            while i < len(lines):
                line = lines[i]
                line_stripped = line.strip()
                
                # Handle code blocks (```)
                if line_stripped.startswith('```'):
                    if in_code_block:
                        # End of code block
                        flush_bullet_list()
                        if code_block_lines:
                            code_text = '\n'.join(code_block_lines)
                            content_blocks.append({
                                "type": "codeBlock",
                                "attrs": {"language": code_block_language} if code_block_language else {},
                                "content": [{"type": "text", "text": code_text}]
                            })
                        code_block_lines = []
                        code_block_language = ""
                        in_code_block = False
                    else:
                        # Start of code block
                        flush_bullet_list()
                        in_code_block = True
                        # Extract language if specified (```json, ```python, etc.)
                        lang = line_stripped[3:].strip()
                        if lang:
                            code_block_language = lang
                    i += 1
                    continue
                
                if in_code_block:
                    code_block_lines.append(line)
                    i += 1
                    continue
                
                # Skip empty lines (but flush lists first)
                if not line_stripped:
                    flush_bullet_list()
                    i += 1
                    continue
                
                # Handle markdown headers
                if line_stripped.startswith('### '):
                    flush_bullet_list()
                    header_text = line_stripped[4:].strip()
                    content_blocks.append({
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": parse_inline_formatting(header_text)
                    })
                elif line_stripped.startswith('## '):
                    flush_bullet_list()
                    header_text = line_stripped[3:].strip()
                    content_blocks.append({
                        "type": "heading",
                        "attrs": {"level": 2},
                        "content": parse_inline_formatting(header_text)
                    })
                elif line_stripped.startswith('# '):
                    flush_bullet_list()
                    header_text = line_stripped[2:].strip()
                    content_blocks.append({
                        "type": "heading",
                        "attrs": {"level": 1},
                        "content": parse_inline_formatting(header_text)
                    })
                
                # Handle markdown separator lines (---)
                elif line_stripped.startswith('---') or line_stripped == '---':
                    flush_bullet_list()
                    content_blocks.append({"type": "rule"})
                
                # Handle bullet lists (- or *)
                elif line_stripped.startswith('- ') or line_stripped.startswith('* '):
                    list_item_text = line_stripped[2:].strip()
                    current_bullet_list.append(list_item_text)
                
                # Handle numbered lists (1. 2. etc.)
                elif len(line_stripped) > 2 and line_stripped[0].isdigit() and line_stripped[1:3] == '. ':
                    flush_bullet_list()
                    numbered_text = line_stripped[3:].strip()
                    content_blocks.append({
                        "type": "paragraph",
                        "content": parse_inline_formatting(numbered_text)
                    })
                
                # Handle image links [Image: filename](url) - convert to text reference
                elif re.match(r'^\[Image[^\]]*\]\([^\)]+\)', line_stripped):
                    flush_bullet_list()
                    # Extract image info for display
                    img_match = re.match(r'\[Image[^\]]*\]\(([^\)]+)\)', line_stripped)
                    if img_match:
                        img_url = img_match.group(1)
                        # Extract filename from URL
                        filename = img_url.split('/')[-1]
                        if '?' in filename:
                            filename = filename.split('?')[0]
                        # Create a paragraph with image reference text
                        # Note: Image will be attached separately, this is just a reference
                        paragraph_content = [
                            {"type": "text", "text": "Image: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": filename}
                        ]
                        content_blocks.append({
                            "type": "paragraph",
                            "content": paragraph_content
                        })
                    else:
                        # Fallback: just parse as regular text
                        paragraph_content = parse_inline_formatting(line_stripped)
                        if paragraph_content:
                            content_blocks.append({
                                "type": "paragraph",
                                "content": paragraph_content
                            })
                
                # Handle regular paragraphs (including those with bold)
                else:
                    flush_bullet_list()
                    paragraph_content = parse_inline_formatting(line_stripped)
                    if paragraph_content:
                        content_blocks.append({
                            "type": "paragraph",
                            "content": paragraph_content
                        })
                
                i += 1
            
            # Flush any remaining bullet list
            flush_bullet_list()
            
            # If no content blocks, add empty paragraph
            if not content_blocks:
                content_blocks.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": ""}]
                })
            
            adf_doc = {
                "type": "doc",
                "version": 1,
                "content": content_blocks
            }
            
            logger.debug(f"🔍 ADF conversion complete: {len(content_blocks)} content blocks generated")
            return adf_doc
            
        except Exception as e:
            logger.error(f"Error converting to ADF: {str(e)}", exc_info=True)
            # Fallback to simple ADF document
            return {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": markdown_content
                            }
                        ]
                    }
                ]
            }
    
    def should_update_ticket(self, ticket_data: Dict[str, Any]) -> bool:
        """Check if a ticket should be updated (empty or placeholder description)"""
        description = ticket_data.get('fields', {}).get('description')
        
        # No description at all
        if not description:
            return True
        
        # Check for Atlassian Document Format (ADF) structure
        if isinstance(description, dict):
            content = description.get('content', [])
            if not content:
                return True
            
            # Check if content is just empty paragraphs or placeholders
            text_content = self._extract_text_from_adf(description)
            if not text_content.strip():
                return True
            
            # Check for placeholder text
            placeholder_indicators = [
                'todo',
                'tbd',
                'placeholder',
                'fill this in',
                'add description'
            ]
            
            text_lower = text_content.lower()
            return any(indicator in text_lower for indicator in placeholder_indicators)
        
        # Handle plain text description
        if isinstance(description, str):
            if not description.strip():
                return True
            
            placeholder_indicators = [
                'todo',
                'tbd', 
                'placeholder',
                'fill this in',
                'add description'
            ]
            
            text_lower = description.lower()
            return any(indicator in text_lower for indicator in placeholder_indicators)
        
        return False
    
    def _extract_text_from_adf(self, adf_content: Dict[str, Any]) -> str:
        """Extract plain text from Atlassian Document Format"""
        def extract_text(node):
            if isinstance(node, dict):
                if node.get('type') == 'text':
                    return node.get('text', '')
                elif 'content' in node:
                    return ''.join(extract_text(child) for child in node['content'])
            elif isinstance(node, list):
                return ''.join(extract_text(item) for item in node)
            return ''
        
        return extract_text(adf_content)
    
    def extract_prd_url(self, ticket_data: Dict[str, Any]) -> Optional[str]:
        """Extract PRD/RFC URL from the custom field"""
        fields = ticket_data.get('fields', {})
        prd_field = fields.get(self.prd_custom_field)
        
        if not prd_field:
            return None
        
        # Handle different custom field types
        if isinstance(prd_field, str):
            return prd_field if prd_field.strip() else None
        elif isinstance(prd_field, dict):
            return prd_field.get('value') or prd_field.get('url')
        elif isinstance(prd_field, list) and prd_field:
            first_item = prd_field[0]
            if isinstance(first_item, dict):
                return first_item.get('value') or first_item.get('url')
            return str(first_item)
        
        return None
    
    def extract_rfc_url(self, ticket_data: Dict[str, Any]) -> Optional[str]:
        """Extract RFC URL from the RFC custom field"""
        if not self.rfc_custom_field:
            return None
            
        fields = ticket_data.get('fields', {})
        rfc_field = fields.get(self.rfc_custom_field)
        
        if not rfc_field:
            return None
        
        # Handle different custom field types (same logic as PRD)
        if isinstance(rfc_field, str):
            # Look for URL in the string
            url_match = re.search(r'https?://[^\s<>"{}|\\^`\[\]]+', rfc_field)
            return url_match.group(0) if url_match else (rfc_field if rfc_field.strip() else None)
        elif isinstance(rfc_field, dict):
            # Check common dictionary keys
            for key in ['value', 'url', 'content']:
                value = rfc_field.get(key)
                if value:
                    if isinstance(value, str):
                        url_match = re.search(r'https?://[^\s<>"{}|\\^`\[\]]+', value)
                        return url_match.group(0) if url_match else value
                    return str(value)
        elif isinstance(rfc_field, list) and rfc_field:
            first_item = rfc_field[0]
            if isinstance(first_item, dict):
                for key in ['value', 'url', 'content']:
                    value = first_item.get(key)
                    if value:
                        if isinstance(value, str):
                            url_match = re.search(r'https?://[^\s<>"{}|\\^`\[\]]+', value)
                            return url_match.group(0) if url_match else value
                        return str(value)
            return str(first_item)
        
        return None
    
    def extract_document_urls(self, ticket_data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """Extract both PRD and RFC URLs from the ticket
        
        Returns:
            Tuple of (prd_url, rfc_url)
        """
        prd_url = self.extract_prd_url(ticket_data)
        rfc_url = self.extract_rfc_url(ticket_data)
        return (prd_url, rfc_url)
    
    def test_connection(self) -> bool:
        """Test the Jira connection"""
        try:
            # First try to get user info
            url = urljoin(self.server_url, '/rest/api/3/myself')
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            # Also test the enhanced search API with a simple query
            search_url = urljoin(self.server_url, '/rest/api/3/search/jql')
            search_params = {
                'jql': 'created >= -1d',  # Simple query for recent issues
                'maxResults': 1,
                'fields': 'key'
            }
            
            search_response = self.session.get(search_url, params=search_params, timeout=10)
            
            # If enhanced search fails, try deprecated API
            if search_response.status_code != 200:
                logger.warning("Enhanced search API not available, checking deprecated API")
                deprecated_url = urljoin(self.server_url, '/rest/api/3/search')
                deprecated_response = self.session.get(deprecated_url, params=search_params, timeout=10)
                deprecated_response.raise_for_status()
            else:
                search_response.raise_for_status()
            
            return True
        except Exception as e:
            logger.error(f"Jira connection test failed: {e}")
            return False

    # =====================================
    # BULK OPERATIONS (Phase 3)
    # =====================================
    
    def create_story_ticket(self, story_plan, project_key: str, confluence_server_url: Optional[str] = None) -> Optional[str]:
        """
        Create a story ticket in JIRA
        
        Args:
            story_plan: StoryPlan object with story details
            project_key: JIRA project key
            confluence_server_url: Optional Confluence server URL for downloading image attachments
            
        Returns:
            Created ticket key or None if failed
        """
        try:
            # Prepare story description in ADF format with fallback
            try:
                description_adf = story_plan.format_description_for_jira_adf()
                
                # If format_description_for_jira_adf returns None, it means description already contains
                # acceptance criteria and we should convert the markdown description to ADF
                if description_adf is None:
                    # Description already has acceptance criteria, convert markdown to ADF
                    description_adf = self._convert_markdown_to_adf(story_plan.description)
                    logger.debug(f"Converted markdown description to ADF for story: {story_plan.summary}")
                else:
                    # Description doesn't have acceptance criteria, but might still have markdown
                    # Check if description contains markdown formatting
                    if '**' in story_plan.description or '##' in story_plan.description or '```' in story_plan.description:
                        # Convert the full description (which may include markdown) to ADF
                        # and merge with acceptance criteria if needed
                        description_adf = self._convert_markdown_to_adf(story_plan.description)
                        logger.debug(f"Converted markdown description to ADF for story: {story_plan.summary}")
                    else:
                        logger.debug(f"Using ADF format for story description: {story_plan.summary}")
            except Exception as e:
                logger.warning(f"Failed to format ADF description for story, using markdown conversion fallback: {e}")
                # Try markdown conversion as fallback
                try:
                    description_adf = self._convert_markdown_to_adf(story_plan.description)
                except Exception as e2:
                    logger.warning(f"Markdown conversion also failed, using plain text fallback: {e2}")
                    description_text = story_plan.format_description()
                    description_adf = {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": description_text
                                    }
                                ]
                            }
                        ]
                    }
            
            # Prepare issue data
            issue_data = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": story_plan.summary,
                    "description": description_adf,
                    "issuetype": {"name": "Story"}
                }
            }
            
            # Add epic link if provided
            if story_plan.epic_key:
                issue_data["fields"]["parent"] = {"key": story_plan.epic_key}
            
            # Calculate mandays from child tasks if available
            if self.mandays_custom_field and hasattr(story_plan, 'tasks') and story_plan.tasks:
                total_mandays = 0.0
                for task in story_plan.tasks:
                    if hasattr(task, 'cycle_time_estimate') and task.cycle_time_estimate:
                        total_mandays += task.cycle_time_estimate.total_days
                
                if total_mandays > 0:
                    issue_data["fields"][self.mandays_custom_field] = total_mandays
                    logger.debug(f"Setting mandays field {self.mandays_custom_field} to {total_mandays} for story (calculated from {len(story_plan.tasks)} tasks)")
            
            # Add test cases to custom field if available
            test_cases_content = story_plan.format_test_cases()
            if test_cases_content and self.test_case_custom_field:
                # Convert Markdown to ADF format
                test_cases_adf = self._convert_markdown_to_adf(test_cases_content)
                issue_data["fields"][self.test_case_custom_field] = test_cases_adf
            
            # Create the ticket
            url = urljoin(self.server_url, '/rest/api/3/issue')
            response = self.session.post(url, json=issue_data, timeout=30)
            
            if response.status_code == 201:
                result = response.json()
                ticket_key = result.get('key')
                logger.info(f"Created story ticket: {ticket_key}")
                
                # Handle image attachments if description contains images
                self._attach_images_from_description(ticket_key, story_plan.description, confluence_server_url)
                
                return ticket_key
            else:
                logger.error(f"Failed to create story ticket: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating story ticket: {str(e)}")
            return None
    
    def create_task_ticket(self, task_plan, project_key: str, story_key: Optional[str] = None, raw_description: Optional[str] = None) -> Optional[str]:
        """
        Create a task ticket in JIRA
        
        Args:
            task_plan: TaskPlan object with task details
            project_key: JIRA project key
            story_key: Parent story key (optional)
            raw_description: Optional raw description to use directly (bypasses TaskPlan formatting)
            
        Returns:
            Created ticket key or None if failed
        """
        try:
            # Prepare task description in ADF format
            if raw_description:
                # Use raw description directly, convert to ADF
                logger.debug(f"Using raw description for task: {task_plan.summary}")
                description_adf = self._convert_markdown_to_adf(raw_description)
            else:
                # Use TaskPlan structured formatting
                try:
                    description_adf = task_plan.format_description_for_jira_adf()
                    logger.debug(f"Using ADF format for task description: {task_plan.summary}")
                except Exception as e:
                    logger.warning(f"Failed to format ADF description for task, using plain text fallback: {e}")
                    description_text = task_plan.format_description()
                    description_adf = {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": description_text
                                    }
                                ]
                            }
                        ]
                    }
            
            # Prepare issue data
            issue_data = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": task_plan.summary,
                    "description": description_adf,
                    "issuetype": {"name": "Task"}
                }
            }
            
            # Add parent relationships - use epic as parent (stories cannot parent tasks in this hierarchy)
            # Verify epic_key is actually an Epic before setting as parent
            if task_plan.epic_key:
                epic_type = self.get_ticket_type(task_plan.epic_key)
                if epic_type and 'epic' in epic_type.lower():
                    issue_data["fields"]["parent"] = {"key": task_plan.epic_key}
                    if story_key:
                        logger.debug(f"Setting task parent to epic: {task_plan.epic_key} (will link to story {story_key} via relationship)")
                    else:
                        logger.debug(f"Setting task parent to epic: {task_plan.epic_key} (no story parent)")
                else:
                    logger.warning(f"Epic key {task_plan.epic_key} is not an Epic (type: {epic_type}), skipping parent relationship")
            else:
                logger.warning(f"No epic key provided for task: {task_plan.summary}")
            
            # Add mandays estimation as custom field if available
            if task_plan.cycle_time_estimate and self.mandays_custom_field:
                mandays_value = task_plan.cycle_time_estimate.total_days
                issue_data["fields"][self.mandays_custom_field] = mandays_value
                logger.debug(f"Setting mandays field {self.mandays_custom_field} to {mandays_value} for task")
            
            # Add test cases to custom field if available
            test_cases_content = task_plan.format_test_cases()
            if test_cases_content and self.test_case_custom_field:
                # Convert Markdown to ADF format
                test_cases_adf = self._convert_markdown_to_adf(test_cases_content)
                issue_data["fields"][self.test_case_custom_field] = test_cases_adf
            
            # Create the ticket
            url = urljoin(self.server_url, '/rest/api/3/issue')
            response = self.session.post(url, json=issue_data, timeout=30)
            
            if response.status_code == 201:
                result = response.json()
                ticket_key = result.get('key')
                logger.info(f"Created task ticket: {ticket_key}")
                
                # Handle image attachments if description contains images
                description_text = raw_description if raw_description else task_plan.description
                self._attach_images_from_description(ticket_key, description_text)
                
                return ticket_key
            else:
                error_message = f"Failed to create task ticket: {response.status_code} - {response.text}"
                logger.error(error_message)
                raise ValueError(error_message)
                
        except Exception as e:
            logger.error(f"Error creating task ticket: {str(e)}")
            return None
    
    def create_issue_link(self, inward_key: str, outward_key: str, link_type: str = "Relates") -> bool:
        """
        Create a link between two JIRA issues
        
        Args:
            inward_key: Source issue key
            outward_key: Target issue key  
            link_type: Link type (e.g., "Relates", "Blocks", "Split From")
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.debug(f"🔗 Creating JIRA link: {inward_key} -> {outward_key} ({link_type})")
            
            link_data = {
                "type": {"name": link_type},
                "inwardIssue": {"key": inward_key},
                "outwardIssue": {"key": outward_key}
            }
            
            url = urljoin(self.server_url, '/rest/api/3/issueLink')
            response = self.session.post(url, json=link_data, timeout=30)
            
            if response.status_code == 201:
                logger.debug(f"✅ Successfully created JIRA link {inward_key} -> {outward_key} ({link_type})")
                return True
            else:
                # Enhanced error debugging for "Split From" failures
                error_details = ""
                full_response = ""
                try:
                    error_response = response.json()
                    full_response = str(error_response)
                    if 'errors' in error_response:
                        error_details = f" - Errors: {error_response['errors']}"
                    elif 'errorMessages' in error_response:
                        error_details = f" - Messages: {error_response['errorMessages']}"
                except:
                    error_details = f" - Response: {response.text[:200]}"
                    full_response = response.text
                
                # Special debugging for "Work item split" link type
                if link_type == "Work item split":
                    logger.error(f"🚨 WORK ITEM SPLIT LINK FAILED - DEBUG INFO:")
                    logger.error(f"   📋 Request payload: {link_data}")
                    logger.error(f"   🌐 URL: {url}")
                    logger.error(f"   📊 Status code: {response.status_code}")
                    logger.error(f"   📝 Full response: {full_response}")
                    logger.error(f"   🔍 Parsed error details: {error_details}")
                    
                    # Check if it's a link type availability issue
                    if "does not exist" in full_response.lower() or "invalid" in full_response.lower():
                        logger.error(f"   💡 ANALYSIS: 'Work item split' link type may not be available in this JIRA instance")
                        logger.error(f"   💡 SUGGESTION: Check JIRA administration > Issue linking to see available link types")
                else:
                    logger.debug(f"❌ Failed to create JIRA link {inward_key} -> {outward_key} ({link_type}): {response.status_code}{error_details}")
                
                return False
                
        except Exception as e:
            logger.error(f"💥 Exception creating issue link {inward_key} -> {outward_key} ({link_type}): {str(e)}")
            return False
    
    def get_available_link_types(self) -> List[Dict[str, Any]]:
        """
        Get all available issue link types in this JIRA instance
        
        Returns:
            List of link type definitions
        """
        try:
            url = urljoin(self.server_url, '/rest/api/3/issueLinkType')
            response = self.session.get(url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                link_types = data.get('issueLinkTypes', [])
                logger.info(f"📋 Available link types in JIRA instance: {len(link_types)} types")
                for link_type in link_types:
                    name = link_type.get('name', 'Unknown')
                    inward = link_type.get('inward', 'N/A')
                    outward = link_type.get('outward', 'N/A')
                    logger.info(f"   🔗 {name}: {inward} ↔ {outward}")
                return link_types
            else:
                logger.error(f"Failed to get link types: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting available link types: {str(e)}")
            return []
    
    def bulk_create_tickets(self, tickets_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create multiple tickets in bulk
        
        Args:
            tickets_data: List of ticket creation data
            
        Returns:
            Dictionary with created tickets and any errors
        """
        results = {
            "created_tickets": [],
            "failed_tickets": [],
            "errors": []
        }
        
        # JIRA bulk create endpoint
        url = urljoin(self.server_url, '/rest/api/3/issue/bulk')
        
        try:
            bulk_data = {"issueUpdates": tickets_data}
            response = self.session.post(url, json=bulk_data, timeout=60)
            
            if response.status_code == 201:
                result = response.json()
                
                # Process successful creations
                if "issues" in result:
                    for issue in result["issues"]:
                        results["created_tickets"].append(issue.get("key"))
                        logger.info(f"Bulk created ticket: {issue.get('key')}")
                
                # Process errors
                if "errors" in result:
                    for error in result["errors"]:
                        results["failed_tickets"].append(error)
                        results["errors"].append(str(error))
                        logger.error(f"Bulk creation error: {error}")
                        
            else:
                error_msg = f"Bulk creation failed: {response.status_code} - {response.text}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
                
        except Exception as e:
            error_msg = f"Error in bulk ticket creation: {str(e)}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
        
        return results
    
    def get_project_key_from_epic(self, epic_key: str) -> Optional[str]:
        """
        Extract project key from epic key
        
        Args:
            epic_key: Epic key like "PROJ-123"
            
        Returns:
            Project key like "PROJ" or None
        """
        try:
            if '-' in epic_key:
                return epic_key.split('-')[0]
            return None
        except Exception:
            return None
    
    def validate_ticket_relationships(self, epic_key: str) -> Dict[str, Any]:
        """
        Validate the relationship integrity of an epic structure
        
        Args:
            epic_key: Epic key to validate
            
        Returns:
            Validation results with any issues found
        """
        validation_results = {
            "epic_key": epic_key,
            "valid": True,
            "issues": [],
            "story_count": 0,
            "task_count": 0,
            "orphaned_tasks": []
        }
        
        try:
            # Get all stories in epic
            stories_jql = f'"Epic Link" = {epic_key} AND issuetype = Story'
            stories = self.search_tickets(stories_jql, max_results=1000)
            validation_results["story_count"] = len(stories)
            
            # Get all tasks in epic
            tasks_jql = f'"Epic Link" = {epic_key} AND issuetype in (Task, Sub-task)'
            tasks = self.search_tickets(tasks_jql, max_results=1000)
            validation_results["task_count"] = len(tasks)
            
            # Check for orphaned tasks (tasks not linked to any story)
            story_keys = [story['key'] for story in stories]
            for task in tasks:
                task_key = task['key']
                
                # Check if task has a parent story
                parent_field = task.get('fields', {}).get('parent')
                if parent_field:
                    parent_key = parent_field.get('key')
                    if parent_key not in story_keys:
                        validation_results["orphaned_tasks"].append(task_key)
                        validation_results["valid"] = False
                        validation_results["issues"].append(f"Task {task_key} has invalid parent {parent_key}")
                else:
                    # Task has no parent - might be directly under epic
                    validation_results["orphaned_tasks"].append(task_key)
                    validation_results["issues"].append(f"Task {task_key} has no parent story")
            
            logger.info(f"Validated epic {epic_key}: {validation_results['story_count']} stories, {validation_results['task_count']} tasks")
            
        except Exception as e:
            validation_results["valid"] = False
            validation_results["issues"].append(f"Validation error: {str(e)}")
            logger.error(f"Error validating epic relationships: {str(e)}")
        
        return validation_results
    
    # =====================================
    # STORY COVERAGE ANALYSIS (New Feature)
    # =====================================
    
    def get_story_tasks(self, story_key: str) -> List[Dict[str, Any]]:
        """
        Get all task tickets related to a story ticket
        
        Fetches tasks via:
        1. Parent relationship (parent = story_key)
        2. "Split from" relationship via issue links
        
        Args:
            story_key: Story ticket key
            
        Returns:
            List of task ticket data dictionaries
        """
        try:
            tasks = []
            task_keys_seen = set()
            
            # Method 1: Search for tasks with this story as parent
            parent_jql = f'parent = {story_key} AND issuetype in (Task, Sub-task)'
            logger.info(f"Searching for tasks with parent {story_key}")
            parent_tasks = self.search_tickets(parent_jql, max_results=500)
            
            for task in parent_tasks:
                task_key = task.get('key')
                if task_key and task_key not in task_keys_seen:
                    tasks.append(task)
                    task_keys_seen.add(task_key)
            
            logger.info(f"Found {len(tasks)} tasks via parent relationship")
            
            # Method 2: Search via "split from" issue links
            issue_links = self.get_issue_links(story_key)
            logger.info(f"Checking {len(issue_links)} issue links for split relationships")
            
            for link in issue_links:
                link_type = link.get('type', {})
                link_name = link_type.get('name', '').lower()
                
                # Check for split relationships
                if 'split' in link_name:
                    # Check both inward and outward links
                    outward_issue = link.get('outwardIssue')  # Story splits TO task
                    
                    if outward_issue:
                        issue_type = outward_issue.get('fields', {}).get('issuetype', {}).get('name', '').lower()
                        
                        # If the linked issue is a task, get its full data
                        if 'task' in issue_type or 'sub-task' in issue_type:
                            task_key = outward_issue['key']
                            if task_key not in task_keys_seen:
                                logger.info(f"Found task {task_key} via split relationship")
                                task_data = self.get_ticket(task_key)
                                if task_data:
                                    tasks.append(task_data)
                                    task_keys_seen.add(task_key)
            
            logger.info(f"Total tasks found for story {story_key}: {len(tasks)}")
            return tasks
            
        except Exception as e:
            logger.error(f"Failed to get tasks for story {story_key}: {e}")
            return []
    
    def extract_test_cases(self, ticket_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract test cases from a ticket's test case custom field
        
        Args:
            ticket_data: JIRA ticket data dictionary
            
        Returns:
            Test cases as plain text string, or None if not found
        """
        try:
            if not self.test_case_custom_field:
                logger.debug("No test case custom field configured")
                return None
            
            fields = ticket_data.get('fields', {})
            test_case_field = fields.get(self.test_case_custom_field)
            
            if not test_case_field:
                logger.debug(f"No test cases found in custom field {self.test_case_custom_field}")
                return None
            
            # Handle ADF format (Atlassian Document Format)
            if isinstance(test_case_field, dict):
                test_cases_text = self._extract_text_from_adf(test_case_field)
                if test_cases_text.strip():
                    return test_cases_text
                return None
            
            # Handle plain text
            if isinstance(test_case_field, str):
                return test_case_field if test_case_field.strip() else None
            
            # Handle list format
            if isinstance(test_case_field, list) and test_case_field:
                return '\n'.join(str(item) for item in test_case_field)
            
            return None
            
        except Exception as e:
            logger.warning(f"Error extracting test cases: {e}")
            return None
    
    # =====================================
    # GENERIC TICKET UPDATE OPERATIONS
    # =====================================
    
    def update_ticket_summary(self, ticket_key: str, summary: str) -> bool:
        """
        Update the summary/title of a ticket
        
        Args:
            ticket_key: JIRA ticket key
            summary: New summary text
            
        Returns:
            True if successful, False otherwise
        """
        try:
            url = urljoin(self.server_url, f'/rest/api/3/issue/{ticket_key}')
            
            payload = {
                'fields': {
                    'summary': summary
                }
            }
            
            response = self.session.put(url, json=payload, timeout=30)
            response.raise_for_status()
            
            logger.info(f"✅ Successfully updated summary for ticket {ticket_key}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to update summary for ticket {ticket_key}: {e}")
            return False
    
    def update_ticket_parent(self, ticket_key: str, parent_key: str) -> bool:
        """
        Update the parent epic of a ticket (typically used for Story tickets)
        
        Args:
            ticket_key: JIRA ticket key to update
            parent_key: New parent epic key
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Verify parent is actually an Epic
            parent_type = self.get_ticket_type(parent_key)
            if not parent_type or 'epic' not in parent_type.lower():
                logger.warning(f"Parent {parent_key} is not an Epic (type: {parent_type}), but proceeding with update")
            
            url = urljoin(self.server_url, f'/rest/api/3/issue/{ticket_key}')
            
            payload = {
                'fields': {
                    'parent': {
                        'key': parent_key
                    }
                }
            }
            
            response = self.session.put(url, json=payload, timeout=30)
            response.raise_for_status()
            
            logger.info(f"✅ Successfully updated parent for ticket {ticket_key} to {parent_key}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to update parent for ticket {ticket_key}: {e}")
            return False
    
    def get_ticket_type(self, ticket_key: str) -> Optional[str]:
        """
        Get the issue type of a ticket (e.g., Story, Task, Epic)
        
        Args:
            ticket_key: JIRA ticket key
            
        Returns:
            Issue type name in lowercase (e.g., 'story', 'task') or None if not found
        """
        try:
            ticket_data = self.get_ticket(ticket_key)
            if not ticket_data:
                logger.warning(f"Could not get ticket data for {ticket_key}")
                return None
            
            issue_type = ticket_data.get('fields', {}).get('issuetype', {}).get('name', '')
            if issue_type:
                return issue_type.lower()
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting ticket type for {ticket_key}: {e}")
            return None
    
    def create_issue_link_generic(self, source_key: str, target_key: str, link_type: str, direction: str = "outward") -> bool:
        """
        Create a generic link between two JIRA issues with direction control
        
        Args:
            source_key: Source issue key (the issue being updated)
            target_key: Target issue key (the issue to link to)
            link_type: Link type name (e.g., "Blocks", "Relates", "Split")
            direction: Direction of the link - "outward" or "inward"
                      - "outward": source -> target (source is inwardIssue, target is outwardIssue)
                      - "inward": target -> source (source is outwardIssue, target is inwardIssue)
            
        Returns:
            True if successful, False otherwise
            
        Examples:
            - create_issue_link_generic("TASK-1", "STORY-1", "Split", "inward")
              Creates: TASK-1 "split from" STORY-1
            - create_issue_link_generic("STORY-1", "TASK-1", "Split", "outward")  
              Creates: STORY-1 "split to" TASK-1
            - create_issue_link_generic("TASK-1", "TASK-2", "Blocks", "outward")
              Creates: TASK-1 "blocks" TASK-2
        """
        try:
            logger.debug(f"🔗 Creating generic link: {source_key} -> {target_key} ({link_type}, {direction})")
            
            # Set up link data based on direction
            if direction.lower() == "outward":
                # Source is inward, target is outward (normal direction)
                link_data = {
                    "type": {"name": link_type},
                    "inwardIssue": {"key": source_key},
                    "outwardIssue": {"key": target_key}
                }
            else:  # inward
                # Source is outward, target is inward (reverse direction)
                link_data = {
                    "type": {"name": link_type},
                    "inwardIssue": {"key": target_key},
                    "outwardIssue": {"key": source_key}
                }
            
            url = urljoin(self.server_url, '/rest/api/3/issueLink')
            response = self.session.post(url, json=link_data, timeout=30)
            
            if response.status_code == 201:
                logger.info(f"✅ Successfully created link: {source_key} -> {target_key} ({link_type}, {direction})")
                return True
            else:
                error_details = ""
                try:
                    error_response = response.json()
                    if 'errors' in error_response:
                        error_details = f" - Errors: {error_response['errors']}"
                    elif 'errorMessages' in error_response:
                        error_details = f" - Messages: {error_response['errorMessages']}"
                except:
                    error_details = f" - Response: {response.text[:200]}"
                
                logger.error(f"❌ Failed to create link: {source_key} -> {target_key} ({link_type}): {response.status_code}{error_details}")
                return False
                
        except Exception as e:
            logger.error(f"💥 Exception creating generic link {source_key} -> {target_key} ({link_type}): {str(e)}")
            return False
    
    # ==================== Sprint API Methods ====================
    
    def get_board_sprints(self, board_id: int, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get sprints for a board
        
        Args:
            board_id: JIRA board ID
            state: Optional sprint state filter (e.g., "active", "closed", "future")
            
        Returns:
            List of sprint dictionaries
        """
        try:
            url = urljoin(self.server_url, f'/rest/agile/1.0/board/{board_id}/sprint')
            params = {}
            if state:
                params['state'] = state
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            sprints = data.get('values', [])
            logger.info(f"✅ Retrieved {len(sprints)} sprints for board {board_id}")
            return sprints
            
        except Exception as e:
            logger.error(f"❌ Failed to get sprints for board {board_id}: {str(e)}")
            raise
    
    def get_sprint(self, sprint_id: int) -> Dict[str, Any]:
        """
        Get sprint details
        
        Args:
            sprint_id: JIRA sprint ID
            
        Returns:
            Sprint dictionary
        """
        try:
            url = urljoin(self.server_url, f'/rest/agile/1.0/sprint/{sprint_id}')
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            sprint = response.json()
            logger.info(f"✅ Retrieved sprint {sprint_id}: {sprint.get('name', 'Unknown')}")
            return sprint
            
        except Exception as e:
            logger.error(f"❌ Failed to get sprint {sprint_id}: {str(e)}")
            raise
    
    def create_sprint(self, name: str, board_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new sprint
        
        Args:
            name: Sprint name
            board_id: JIRA board ID
            start_date: Sprint start date (ISO format: YYYY-MM-DD)
            end_date: Sprint end date (ISO format: YYYY-MM-DD)
            
        Returns:
            Created sprint dictionary
        """
        try:
            url = urljoin(self.server_url, f'/rest/agile/1.0/board/{board_id}/sprint')
            
            sprint_data = {
                "name": name,
                "originBoardId": board_id
            }
            
            if start_date:
                sprint_data["startDate"] = start_date
            if end_date:
                sprint_data["endDate"] = end_date
            
            response = self.session.post(url, json=sprint_data, timeout=30)
            response.raise_for_status()
            
            sprint = response.json()
            logger.info(f"✅ Created sprint: {name} (ID: {sprint.get('id')})")
            return sprint
            
        except Exception as e:
            logger.error(f"❌ Failed to create sprint {name}: {str(e)}")
            raise
    
    def update_sprint(self, sprint_id: int, name: Optional[str] = None, start_date: Optional[str] = None, 
                     end_date: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
        """
        Update sprint
        
        Args:
            sprint_id: JIRA sprint ID
            name: New sprint name (optional)
            start_date: New start date (ISO format: YYYY-MM-DD, optional)
            end_date: New end date (ISO format: YYYY-MM-DD, optional)
            state: New sprint state (optional)
            
        Returns:
            Updated sprint dictionary
        """
        try:
            url = urljoin(self.server_url, f'/rest/agile/1.0/sprint/{sprint_id}')
            
            update_data = {}
            if name is not None:
                update_data["name"] = name
            if start_date is not None:
                update_data["startDate"] = start_date
            if end_date is not None:
                update_data["endDate"] = end_date
            if state is not None:
                update_data["state"] = state
            
            response = self.session.put(url, json=update_data, timeout=30)
            response.raise_for_status()
            
            sprint = response.json()
            logger.info(f"✅ Updated sprint {sprint_id}")
            return sprint
            
        except Exception as e:
            logger.error(f"❌ Failed to update sprint {sprint_id}: {str(e)}")
            raise
    
    def add_issues_to_sprint(self, sprint_id: int, issue_keys: List[str]) -> bool:
        """
        Add issues to a sprint
        
        Args:
            sprint_id: JIRA sprint ID
            issue_keys: List of issue keys to add
            
        Returns:
            True if successful, False otherwise
        """
        try:
            url = urljoin(self.server_url, f'/rest/agile/1.0/sprint/{sprint_id}/issue')
            
            payload = {
                "issues": issue_keys
            }
            
            response = self.session.post(url, json=payload, timeout=30)
            
            if response.status_code == 204:
                logger.info(f"✅ Added {len(issue_keys)} issues to sprint {sprint_id}")
                return True
            else:
                error_details = ""
                try:
                    error_response = response.json()
                    if 'errors' in error_response:
                        error_details = f" - Errors: {error_response['errors']}"
                    elif 'errorMessages' in error_response:
                        error_details = f" - Messages: {error_response['errorMessages']}"
                except:
                    error_details = f" - Response: {response.text[:200]}"
                
                logger.error(f"❌ Failed to add issues to sprint {sprint_id}: {response.status_code}{error_details}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Exception adding issues to sprint {sprint_id}: {str(e)}")
            return False
    
    def remove_issues_from_sprint(self, issue_keys: List[str]) -> bool:
        """
        Remove issues from their current sprint
        
        Args:
            issue_keys: List of issue keys to remove from sprint
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Remove issues from sprint by moving them to backlog
            url = urljoin(self.server_url, '/rest/agile/1.0/backlog/issue')
            
            payload = {
                "issues": issue_keys
            }
            
            response = self.session.post(url, json=payload, timeout=30)
            
            if response.status_code == 204:
                logger.info(f"✅ Removed {len(issue_keys)} issues from sprint")
                return True
            else:
                error_details = ""
                try:
                    error_response = response.json()
                    if 'errors' in error_response:
                        error_details = f" - Errors: {error_response['errors']}"
                    elif 'errorMessages' in error_response:
                        error_details = f" - Messages: {error_response['errorMessages']}"
                except:
                    error_details = f" - Response: {response.text[:200]}"
                
                logger.error(f"❌ Failed to remove issues from sprint: {response.status_code}{error_details}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Exception removing issues from sprint: {str(e)}")
            return False
    
    def get_sprint_issues(self, sprint_id: int) -> List[Dict[str, Any]]:
        """
        Get all issues in a sprint
        
        Args:
            sprint_id: JIRA sprint ID
            
        Returns:
            List of issue dictionaries
        """
        try:
            url = urljoin(self.server_url, f'/rest/agile/1.0/sprint/{sprint_id}/issue')
            params = {
                'fields': self._get_fields_list()
            }
            
            all_issues = []
            start_at = 0
            max_results = 50
            
            while True:
                params['startAt'] = start_at
                params['maxResults'] = max_results
                
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                issues = data.get('issues', [])
                all_issues.extend(issues)
                
                if data.get('isLast', True) or len(issues) < max_results:
                    break
                
                start_at += max_results
            
            logger.info(f"✅ Retrieved {len(all_issues)} issues from sprint {sprint_id}")
            return all_issues
            
        except Exception as e:
            logger.error(f"❌ Failed to get issues for sprint {sprint_id}: {str(e)}")
            raise
    
    def get_board_id(self, project_key: str) -> Optional[int]:
        """
        Get board ID for a project
        
        Args:
            project_key: JIRA project key
            
        Returns:
            Board ID if found, None otherwise
        """
        try:
            url = urljoin(self.server_url, '/rest/agile/1.0/board')
            params = {
                'projectKeyOrId': project_key,
                'type': 'scrum'  # or 'kanban'
            }
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            boards = data.get('values', [])
            
            if boards:
                board_id = boards[0].get('id')
                logger.info(f"✅ Found board {board_id} for project {project_key}")
                return board_id
            else:
                logger.warning(f"⚠️ No board found for project {project_key}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Failed to get board ID for project {project_key}: {str(e)}")
            return None
    
    def _extract_image_urls_from_description(self, description: str) -> List[Dict[str, str]]:
        """
        Extract image URLs from description text
        
        Args:
            description: Description text that may contain image links
            
        Returns:
            List of dicts with 'url' and 'filename' keys
        """
        image_urls = []
        
        # Pattern 1: [Image: filename](url)
        pattern1 = r'\[Image[^\]]*\]\(([^\)]+)\)'
        matches = re.findall(pattern1, description, re.IGNORECASE)
        for url in matches:
            # Extract filename from URL if possible
            filename = url.split('/')[-1] if '/' in url else 'image.png'
            # Clean up filename (remove query params)
            if '?' in filename:
                filename = filename.split('?')[0]
            image_urls.append({'url': url, 'filename': filename})
        
        # Pattern 2: [Image: filename] (without URL - Confluence attachment)
        pattern2 = r'\[Image:\s*([^\]]+)\]'
        matches2 = re.findall(pattern2, description, re.IGNORECASE)
        for filename in matches2:
            # This is just a filename, we'll need to construct the URL
            # But we don't have page context here, so skip for now
            # These should have been converted to pattern1 format by the parser
            pass
        
        return image_urls
    
    def _download_image(self, image_url: str, confluence_server_url: Optional[str] = None) -> Optional[BytesIO]:
        """
        Download an image from a URL (supports Confluence attachments and external URLs)
        
        Args:
            image_url: URL to the image
            confluence_server_url: Confluence server URL if image is a Confluence attachment
            
        Returns:
            BytesIO object with image data or None if failed
        """
        try:
            logger.info(f"Attempting to download image from: {image_url}")
            
            # If it's a relative Confluence URL, make it absolute
            if image_url.startswith('/wiki/download/attachments/'):
                if confluence_server_url:
                    # Ensure confluence_server_url has /wiki suffix if not present
                    base_url = confluence_server_url.rstrip('/')
                    if not base_url.endswith('/wiki'):
                        # Try to add /wiki if it's missing
                        if '/wiki' not in base_url:
                            base_url = base_url + '/wiki'
                    full_url = urljoin(base_url, image_url)
                    logger.info(f"Converting relative Confluence URL using server URL: {confluence_server_url} -> {full_url}")
                else:
                    # Try to infer from JIRA server URL (often same domain)
                    # Replace /rest/api with /wiki
                    base_url = self.server_url.replace('/rest/api', '').replace('/api', '')
                    if not base_url.endswith('/wiki'):
                        base_url = base_url + '/wiki'
                    full_url = urljoin(base_url, image_url)
                    logger.warning(f"No Confluence server URL provided, inferring from JIRA URL: {base_url} -> {full_url}")
            elif image_url.startswith('/download/attachments/'):
                if confluence_server_url:
                    base_url = confluence_server_url.rstrip('/')
                    if not base_url.endswith('/wiki'):
                        if '/wiki' not in base_url:
                            base_url = base_url + '/wiki'
                    full_url = urljoin(base_url, image_url)
                    logger.info(f"Converting relative Confluence URL (no /wiki prefix): {full_url}")
                else:
                    base_url = self.server_url.replace('/rest/api', '').replace('/api', '')
                    if not base_url.endswith('/wiki'):
                        base_url = base_url + '/wiki'
                    full_url = urljoin(base_url, image_url)
                    logger.warning(f"No Confluence server URL provided, inferring: {full_url}")
            else:
                full_url = image_url
                logger.info(f"Using absolute URL: {full_url}")
            
            # Download the image
            logger.debug(f"Downloading image from: {full_url}")
            response = self.session.get(full_url, timeout=30, stream=True)
            response.raise_for_status()
            
            # Check if it's actually an image
            content_type = response.headers.get('content-type', '')
            logger.debug(f"Response content-type: {content_type}")
            if not content_type.startswith('image/'):
                logger.warning(f"URL does not appear to be an image (content-type: {content_type}): {full_url}")
                return None
            
            # Read image data
            image_data = BytesIO(response.content)
            logger.info(f"Successfully downloaded image from {full_url} ({len(response.content)} bytes, type: {content_type})")
            return image_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error downloading image from {image_url}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}, Response text: {e.response.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading image from {image_url}: {e}", exc_info=True)
            return None
    
    def _attach_file_to_ticket(self, ticket_key: str, file_data: BytesIO, filename: str) -> bool:
        """
        Attach a file to a JIRA ticket
        
        Args:
            ticket_key: JIRA ticket key
            file_data: BytesIO object with file data
            filename: Name for the file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            url = urljoin(self.server_url, f'/rest/api/3/issue/{ticket_key}/attachments')
            
            # Reset file pointer
            file_data.seek(0)
            
            # Prepare multipart form data
            files = {
                'file': (filename, file_data, 'application/octet-stream')
            }
            
            # JIRA requires special header for attachments
            headers = {
                'X-Atlassian-Token': 'no-check'
            }
            
            # Use requests directly (not session) to handle multipart/form-data properly
            response = requests.post(
                url,
                files=files,
                headers=headers,
                auth=self.auth,
                timeout=60
            )
            
            if response.status_code == 200:
                logger.info(f"Successfully attached {filename} to ticket {ticket_key}")
                return True
            else:
                logger.error(f"Failed to attach {filename} to ticket {ticket_key}: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error attaching file {filename} to ticket {ticket_key}: {e}")
            return False
    
    def _attach_images_from_description(self, ticket_key: str, description: str, confluence_server_url: Optional[str] = None) -> int:
        """
        Extract images from description and attach them to the JIRA ticket
        
        Args:
            ticket_key: JIRA ticket key
            description: Description text that may contain image links
            confluence_server_url: Optional Confluence server URL for downloading attachments
            
        Returns:
            Number of images successfully attached
        """
        try:
            logger.info(f"Extracting images from description for ticket {ticket_key}")
            if confluence_server_url:
                logger.info(f"Using Confluence server URL: {confluence_server_url}")
            else:
                logger.warning(f"No Confluence server URL provided for ticket {ticket_key}, will try to infer from JIRA URL")
            
            image_urls = self._extract_image_urls_from_description(description)
            
            if not image_urls:
                logger.debug(f"No images found in description for ticket {ticket_key}")
                return 0
            
            logger.info(f"Found {len(image_urls)} image(s) in description for ticket {ticket_key}:")
            for i, img_info in enumerate(image_urls, 1):
                logger.info(f"  Image {i}: {img_info['filename']} from {img_info['url']}")
            
            attached_count = 0
            for img_info in image_urls:
                image_url = img_info['url']
                filename = img_info['filename']
                
                logger.info(f"Processing image: {filename} from {image_url}")
                
                # Download the image
                image_data = self._download_image(image_url, confluence_server_url)
                
                if image_data:
                    logger.info(f"Image downloaded successfully, attaching to ticket {ticket_key}")
                    # Attach to ticket
                    if self._attach_file_to_ticket(ticket_key, image_data, filename):
                        attached_count += 1
                        logger.info(f"✅ Successfully attached image {filename} to ticket {ticket_key}")
                    else:
                        logger.error(f"❌ Failed to attach image {filename} to ticket {ticket_key}")
                else:
                    logger.error(f"❌ Failed to download image from {image_url}")
            
            if attached_count > 0:
                logger.info(f"✅ Successfully attached {attached_count}/{len(image_urls)} image(s) to ticket {ticket_key}")
            else:
                logger.warning(f"⚠️ No images were successfully attached to ticket {ticket_key} (attempted {len(image_urls)})")
            
            return attached_count
            
        except Exception as e:
            logger.error(f"Error attaching images to ticket {ticket_key}: {e}", exc_info=True)
            return 0