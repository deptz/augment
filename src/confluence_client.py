import requests
from typing import Dict, Optional, Any
import logging
from urllib.parse import urljoin
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ConfluenceClient:
    """Confluence API client for fetching PRD/RFC documents"""
    
    def __init__(self, server_url: str, username: str, api_token: str):
        self.server_url = server_url.rstrip('/')
        self.auth = (username, api_token)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({
            'Accept': 'application/json'
        })
    
    def get_page_content(self, page_url: str) -> Optional[Dict[str, Any]]:
        """Get Confluence page content from URL"""
        try:
            # Extract page ID from various Confluence URL formats
            page_id = self._extract_page_id(page_url)
            if not page_id:
                logger.error(f"Could not extract page ID from URL: {page_url}")
                return None
            
            return self._get_page_by_id(page_id)
            
        except Exception as e:
            logger.error(f"Failed to get page content from {page_url}: {e}")
            return None
    
    def _extract_page_id(self, url: str) -> Optional[str]:
        """Extract page ID from Confluence URL"""
        # Common Confluence URL patterns
        patterns = [
            r'/pages/viewpage\.action\?pageId=(\d+)',  # Legacy format
            r'/display/[^/]+/([^/?]+)',  # Display format - extract title
            r'/wiki/spaces/[^/]+/pages/(\d+)/',  # New format with page ID
            r'/wiki/display/[^/]+/([^/?]+)',  # Wiki display format
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                page_id = match.group(1)
                # If it's a title, try to resolve it to page ID
                if not page_id.isdigit():
                    return self._resolve_page_title_to_id(page_id)
                return page_id
        
        return None
    
    def _resolve_page_title_to_id(self, title: str) -> Optional[str]:
        """Resolve page title to page ID"""
        # This is a simplified approach - in practice, you might need space info
        url = f"{self.server_url}/rest/api/content"
        params = {
            'title': title,
            'expand': 'version,body.storage'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            results = data.get('results', [])
            
            if results:
                return results[0]['id']
            
        except Exception as e:
            logger.warning(f"Failed to resolve title '{title}' to page ID: {e}")
        
        return None
    
    def _detect_prd_template(self, prd_sections: Dict[str, str]) -> str:
        """Detect which PRD template is being used
        
        Returns:
            'template_1': User Value focused template
            'template_2': Goals focused template  
            'unknown': Cannot determine template type
        """
        # Template 1 indicators: user_value, business_value, strategic_impact
        template_1_indicators = ['user_value', 'business_value', 'strategic_impact']
        template_1_score = sum(1 for key in template_1_indicators if key in prd_sections)
        
        # Template 2 indicators: goals, business_goals, user_goals, tldr, problem_alignment
        template_2_indicators = ['goals', 'business_goals', 'user_goals', 'tldr', 'problem_alignment', 'product_narrative']
        template_2_score = sum(1 for key in template_2_indicators if key in prd_sections)
        
        if template_2_score >= 2:
            return 'template_2'
        elif template_1_score >= 2:
            return 'template_1'
        elif template_2_score > template_1_score:
            return 'template_2'
        elif template_1_score > 0:
            return 'template_1'
        else:
            return 'unknown'
    
    def _get_page_by_id(self, page_id: str) -> Optional[Dict[str, Any]]:
        """Get page content by page ID"""
        url = f"{self.server_url}/rest/api/content/{page_id}"
        params = {
            'expand': 'body.storage,version,space'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract PRD sections first to enable template detection
            prd_sections = self._extract_prd_sections(data)
            
            # Extract summary and goals using traditional methods
            summary = self._extract_summary(data)
            goals = self._extract_goals(data)
            
            # If traditional summary/goals not found, use PRD sections based on template type
            if not summary or not goals:
                template_type = self._detect_prd_template(prd_sections)
                logger.debug(f"Detected PRD template: {template_type}")
                
                if template_type == 'template_1':
                    # Template 1: User Value focused
                    if not summary:
                        summary = (prd_sections.get('user_value') or 
                                  prd_sections.get('user_problem_definition') or
                                  prd_sections.get('proposed_solution'))
                    
                    if not goals:
                        goals_parts = []
                        if prd_sections.get('business_value'):
                            goals_parts.append(f"Business Value: {prd_sections['business_value']}")
                        if prd_sections.get('strategic_impact'):
                            goals_parts.append(f"Strategic Impact: {prd_sections['strategic_impact']}")
                        if prd_sections.get('success_criteria'):
                            goals_parts.append(f"Success Criteria: {prd_sections['success_criteria']}")
                        if prd_sections.get('business_impact'):
                            goals_parts.append(f"Business Impact: {prd_sections['business_impact']}")
                        
                        if goals_parts:
                            goals = " | ".join(goals_parts)
                
                elif template_type == 'template_2':
                    # Template 2: Goals focused
                    if not summary:
                        summary = (prd_sections.get('tldr') or 
                                  prd_sections.get('product_narrative') or
                                  prd_sections.get('problem_statement') or
                                  prd_sections.get('proposed_solution'))
                    
                    if not goals:
                        goals_parts = []
                        if prd_sections.get('business_goals'):
                            goals_parts.append(f"Business Goals: {prd_sections['business_goals']}")
                        if prd_sections.get('user_goals'):
                            goals_parts.append(f"User Goals: {prd_sections['user_goals']}")
                        if prd_sections.get('success_criteria'):
                            goals_parts.append(f"Success Metrics: {prd_sections['success_criteria']}")
                        if prd_sections.get('why_it_matters'):
                            goals_parts.append(f"Why It Matters: {prd_sections['why_it_matters']}")
                        
                        if goals_parts:
                            goals = " | ".join(goals_parts)
                
                else:
                    # Unknown template - try to use any available sections
                    if not summary and prd_sections:
                        # Prefer description-like sections
                        summary = (prd_sections.get('tldr') or 
                                  prd_sections.get('user_value') or
                                  prd_sections.get('product_narrative') or
                                  prd_sections.get('problem_statement') or
                                  prd_sections.get('proposed_solution'))
                    
                    if not goals and prd_sections:
                        # Combine any goal-like sections
                        goals_parts = []
                        for key in ['business_goals', 'user_goals', 'business_value', 
                                   'strategic_impact', 'success_criteria', 'business_impact']:
                            if prd_sections.get(key):
                                goals_parts.append(prd_sections[key])
                        
                        if goals_parts:
                            goals = " | ".join(goals_parts)
            
            # Extract relevant content
            # Include raw body structure for PRD parser compatibility
            page_content = {
                'id': data['id'],
                'title': data['title'],
                'url': f"{self.server_url}/wiki/spaces/{data['space']['key']}/pages/{data['id']}",
                'content': self._extract_text_content(data.get('body', {}).get('storage', {}).get('value', '')),
                'summary': summary,
                'goals': goals,
                'prd_sections': prd_sections,
                'rfc_sections': self._extract_rfc_sections(data),
                # Include raw body structure for PRD parser
                'body': data.get('body', {})
            }
            
            return page_content
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get page {page_id}: {e}")
            return None
    
    def _extract_text_content(self, html_content: str) -> str:
        """Extract plain text from Confluence HTML content using BeautifulSoup"""
        if not html_content:
            return ""
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Handle Confluence-specific structured macros
            for macro in soup.find_all('ac:structured-macro'):
                macro_name = macro.get('ac:name', '')
                
                # Extract content from code macros
                if macro_name == 'code':
                    plain_text_body = macro.find('ac:plain-text-body')
                    if plain_text_body:
                        # Replace with formatted code block
                        code_content = plain_text_body.get_text()
                        macro.replace_with(f"\n\nCODE:\n{code_content}\n\n")
                    else:
                        macro.decompose()
                        
                # Extract content from info/warning/note macros
                elif macro_name in ['info', 'warning', 'note', 'tip']:
                    rich_text_body = macro.find('ac:rich-text-body')
                    if rich_text_body:
                        content = rich_text_body.get_text()
                        macro.replace_with(f"\n\n{macro_name.upper()}: {content}\n\n")
                    else:
                        macro.decompose()
                        
                # Remove other complex macros but keep any text content
                else:
                    text_content = macro.get_text()
                    if text_content.strip():
                        macro.replace_with(text_content)
                    else:
                        macro.decompose()
            
            # Get clean text
            text = soup.get_text()
            
            # Clean up whitespace
            text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)  # Remove excessive newlines
            text = re.sub(r'[ \t]+', ' ', text)  # Normalize spaces
            text = text.strip()
            
            return text
            
        except Exception as e:
            logger.warning(f"BeautifulSoup parsing failed, falling back to regex: {e}")
            # Fallback to original regex method
            text = re.sub(r'<[^>]+>', ' ', html_content)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()
    
    def _extract_summary(self, page_data: Dict[str, Any]) -> Optional[str]:
        """Extract summary/overview section from the page"""
        content = page_data.get('body', {}).get('storage', {}).get('value', '')
        if not content:
            return None
        
        # Look for common summary section patterns including PRD-specific sections
        summary_patterns = [
            # Standard summary sections
            r'<h[1-6][^>]*>(?:Summary|Overview|Abstract|Executive Summary)</h[1-6]>(.*?)(?=<h[1-6]|$)',
            r'<strong>Summary:?</strong>(.*?)(?=<strong>|<h[1-6]|$)',
            r'<b>Summary:?</b>(.*?)(?=<b>|<h[1-6]|$)',
            # PRD-specific sections that often contain summary information
            r'<h[1-6][^>]*>(?:Target Population|User Value)</h[1-6]>(.*?)(?=<h[1-6]|$)',
            # Check for "User Problem Definition" within User Value section
            r'id="User-Problem-Definition"[^>]*>(.*?)(?=<h[1-6]|$)',
        ]
        
        for pattern in summary_patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                summary_html = match.group(1)
                extracted_text = self._extract_text_content(summary_html)
                # Return first non-empty extraction
                if extracted_text and len(extracted_text.strip()) > 20:
                    return extracted_text
        
        # If no specific summary section, return first meaningful paragraph
        first_para_match = re.search(r'<p[^>]*>(.*?)</p>', content, re.DOTALL)
        if first_para_match:
            text = self._extract_text_content(first_para_match.group(1))
            if text and len(text.strip()) > 20:
                return text
        
        return None
    
    def _extract_goals(self, page_data: Dict[str, Any]) -> Optional[str]:
        """Extract goals/objectives section from the page"""
        content = page_data.get('body', {}).get('storage', {}).get('value', '')
        if not content:
            return None
        
        # Look for common goals section patterns including PRD-specific sections
        goals_patterns = [
            # Standard goals sections
            r'<h[1-6][^>]*>(?:Goals?|Objectives?|Requirements?|Success Criteria)</h[1-6]>(.*?)(?=<h[1-6]|$)',
            r'<strong>Goals?:?</strong>(.*?)(?=<strong>|<h[1-6]|$)',
            r'<strong>Objectives?:?</strong>(.*?)(?=<strong>|<h[1-6]|$)',
            # PRD-specific sections
            r'id="Success-Criteria"[^>]*>(.*?)(?=<h[1-6]|$)',
            r'id="Business-Value"[^>]*>(.*?)(?=<h[1-6]|$)',
            r'id="Proposed-solution"[^>]*>(.*?)(?=<h[1-6]|$)',
            # Look for Business Impact and Strategic Impact
            r'id="Business-Impact"[^>]*>(.*?)(?=<h[1-6]|$)',
            r'id="Strategic-Impact"[^>]*>(.*?)(?=<h[1-6]|$)',
        ]
        
        extracted_sections = []
        
        for pattern in goals_patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                goals_html = match.group(1)
                extracted_text = self._extract_text_content(goals_html)
                if extracted_text and len(extracted_text.strip()) > 20:
                    extracted_sections.append(extracted_text)
        
        # Combine multiple sections if found
        if extracted_sections:
            return " ".join(extracted_sections)
        
        return None
    
    def _extract_prd_sections(self, page_data: Dict[str, Any]) -> Dict[str, str]:
        """Extract all PRD-specific sections from the page using BeautifulSoup for better parsing
        
        Supports two PRD templates:
        - Template 1: User Value focused (User Value, Business Value, Strategic Impact)
        - Template 2: Goals focused (Goals, Problem Alignment, TL;DR)
        """
        content = page_data.get('body', {}).get('storage', {}).get('value', '')
        if not content:
            return {}
        
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # Define PRD section patterns with more flexible matching
            # Combined mappings for both Template 1 and Template 2
            prd_section_mappings = {
                # Template 1 sections (User Value focused)
                'target_population': ['Target-Population', 'Target Population'],
                'target_description': ['Target-Description'],
                'user_value': ['User-Value', 'User Value'],
                'user_problem_definition': ['User-Problem-Definition', 'User Problem Definition'],
                'user_problem_frequency': ['User-Problem-Frequency', 'User-Problem-Frequency-&-Severity', 'User Problem Frequency & Severity'],
                'user_problem_severity': ['User-Problem-Severity'],
                'business_value': ['Business-Value', 'Business Value'],
                'business_impact': ['Business-Impact', 'Business Impact'],
                'strategic_impact': ['Strategic-Impact', 'Strategic Impact'],
                'proposed_solution': ['Proposed-solution', 'Proposed Solution'],
                'description_flow': ['Description-&amp;-Flow', 'Description-Flow', 'Description & Flow', 'User-Experience-Flow', 'User Experience Flow'],
                'mockup_design': ['Mockup-&amp;-Design', 'Mockup-Design', 'Mockup & Design'],
                'technical_documentation': ['Technical-Documentation', 'Technical Documentation'],
                'success_criteria': ['Success-Criteria', 'Success Criteria', 'Success-Metrics', 'Success Metrics'],
                'constraints_limitation': ['Constraints-&amp;-Limitation', 'Constraints-Limitation', 'Constraints & Limitation'],
                'supporting_documents': ['Supporting-Documents', 'Supporting Documents', 'Supporting-Evidence', 'Supporting Evidence'],
                'user_stories': ['User-Stories', 'User Stories', 'User-Stories-and-Acceptance-Criteria', 'User Stories and Acceptance Criteria'],
                
                # Template 2 sections (Goals focused)
                'tldr': ['TL;DR', 'TL-DR', 'TLDR'],
                'problem_alignment': ['Problem-Alignment', 'Problem Alignment'],
                'problem_statement': ['Problem-Statement', 'Problem Statement'],
                'why_it_matters': ['Why-It-Matters', 'Why It Matters'],
                'what_happens_if_we_dont_build': ['What-Happens-If-We-Don\'t-Build-This', 'What Happens If We Don\'t Build This', 'What-Happens-If-We-Don-t-Build-This'],
                'goals': ['Goals'],
                'business_goals': ['Business-Goals', 'Business Goals'],
                'user_goals': ['User-Goals', 'User Goals'],
                'opportunity_strategic_fit': ['Opportunity-&amp;-Strategic-Fit', 'Opportunity-Strategic-Fit', 'Opportunity & Strategic Fit'],
                'product_narrative': ['Product-Narrative', 'Product Narrative'],
                'scope_solution_hypothesis': ['Scope-&amp;-Solution-Hypothesis', 'Scope-Solution-Hypothesis', 'Scope & Solution Hypothesis'],
                'pain_points_solved': ['Pain-Points-Solved', 'Pain Points Solved'],
                'key_features': ['Key-Features', 'Key Features'],
                'future_considerations': ['Future-Considerations', 'Future Considerations'],
                'decision_type': ['Decision-Type', 'Decision Type'],
                'final_recommendation': ['Final-Recommendation', 'Final Recommendation']
            }
            
            extracted_sections = {}
            
            for section_name, id_patterns in prd_section_mappings.items():
                section_content = self._extract_section_content_bs(soup, id_patterns)
                if section_content and len(section_content.strip()) > 10:
                    extracted_sections[section_name] = section_content
            
            return extracted_sections
            
        except Exception as e:
            logger.warning(f"BeautifulSoup PRD extraction failed, falling back to regex: {e}")
            return self._extract_prd_sections_regex(page_data)
    
    def _extract_section_content_bs(self, soup: BeautifulSoup, id_patterns: list) -> Optional[str]:
        """Extract content for a section using BeautifulSoup with multiple ID patterns"""
        for pattern in id_patterns:
            # Try to find by ID attribute (most reliable)
            section_element = soup.find(attrs={'id': pattern})
            
            if not section_element:
                # Try to find by ID with HTML entities decoded
                section_element = soup.find(attrs={'id': pattern.replace('&amp;', '&')})
                
            if not section_element:
                # Try to find by heading text content
                for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    if heading.get_text().strip().replace('&', '&amp;') == pattern.replace('-', ' '):
                        section_element = heading
                        break
            
            if section_element:
                # Extract content until next heading of same or higher level
                content_parts = []
                current_element = section_element.next_sibling
                
                # Determine the heading level
                section_level = 1
                if section_element.name and section_element.name.startswith('h'):
                    try:
                        section_level = int(section_element.name[1])
                    except (ValueError, IndexError):
                        section_level = 1
                
                while current_element:
                    if hasattr(current_element, 'name') and current_element.name:
                        # Stop at next heading of same or higher level
                        if current_element.name.startswith('h'):
                            try:
                                current_level = int(current_element.name[1])
                                if current_level <= section_level:
                                    break
                            except (ValueError, IndexError):
                                pass
                        
                        # Collect content
                        element_text = current_element.get_text() if hasattr(current_element, 'get_text') else str(current_element)
                        if element_text.strip():
                            content_parts.append(element_text.strip())
                    
                    current_element = current_element.next_sibling
                
                if content_parts:
                    return ' '.join(content_parts)
        
        return None
    
    def _extract_prd_sections_regex(self, page_data: Dict[str, Any]) -> Dict[str, str]:
        """Fallback PRD extraction using regex (original method)"""
        content = page_data.get('body', {}).get('storage', {}).get('value', '')
        if not content:
            return {}
        
        # Original regex-based implementation as fallback
        prd_section_patterns = {
            'target_population': [
                r'id="Target-Population"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Target Population</h1>(.*?)(?=<h1|$)',
            ],
            'target_description': [
                r'id="Target-Description"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'user_value': [
                r'id="User-Value"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>User Value</h1>(.*?)(?=<h1|$)',
            ],
            'user_problem_definition': [
                r'id="User-Problem-Definition"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'business_value': [
                r'id="Business-Value"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Business Value</h1>(.*?)(?=<h1|$)',
            ],
            'proposed_solution': [
                r'id="Proposed-solution"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Proposed solution</h1>(.*?)(?=<h1|$)',
            ],
            'success_criteria': [
                r'id="Success-Criteria"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Success Criteria</h1>(.*?)(?=<h1|$)',
            ],
        }
        
        extracted_sections = {}
        
        for section_name, patterns in prd_section_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
                if match:
                    section_html = match.group(1)
                    section_text = self._extract_text_content(section_html)
                    if section_text and len(section_text.strip()) > 10:
                        extracted_sections[section_name] = section_text
                        break
        
        return extracted_sections
        
        # Define PRD section patterns based on the analyzed template
        prd_section_patterns = {
            'target_population': [
                r'id="Target-Population"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Target Population</h1>(.*?)(?=<h1|$)',
            ],
            'target_description': [
                r'id="Target-Description"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'user_value': [
                r'id="User-Value"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>User Value</h1>(.*?)(?=<h1|$)',
            ],
            'user_problem_definition': [
                r'id="User-Problem-Definition"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'user_problem_frequency': [
                r'id="User-Problem-Frequency"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'user_problem_severity': [
                r'id="User-Problem-Severity"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'business_value': [
                r'id="Business-Value"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Business Value</h1>(.*?)(?=<h1|$)',
            ],
            'business_impact': [
                r'id="Business-Impact"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'strategic_impact': [
                r'id="Strategic-Impact"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'proposed_solution': [
                r'id="Proposed-solution"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Proposed solution</h1>(.*?)(?=<h1|$)',
            ],
            'description_flow': [
                r'id="Description-&amp;-Flow"[^>]*>(.*?)(?=<h[1-6]|$)',
                r'id="Description-.*?-Flow"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'mockup_design': [
                r'id="Mockup-&amp;-Design"[^>]*>(.*?)(?=<h[1-6]|$)',
                r'id="Mockup-.*?-Design"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'technical_documentation': [
                r'id="Technical-Documentation"[^>]*>(.*?)(?=<h[1-6]|$)',
            ],
            'success_criteria': [
                r'id="Success-Criteria"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Success Criteria</h1>(.*?)(?=<h1|$)',
            ],
            'constraints_limitation': [
                r'id="Constraints-&amp;-Limitation"[^>]*>(.*?)(?=<h1|$)',
                r'id="Constraints-.*?-Limitation"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Constraints.*?Limitation</h1>(.*?)(?=<h1|$)',
            ],
            'supporting_documents': [
                r'id="Supporting-Documents"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>Supporting Documents</h1>(.*?)(?=<h1|$)',
            ],
            'user_stories': [
                r'id="User-Stories"[^>]*>(.*?)(?=<h1|$)',
                r'<h1[^>]*>User Stories</h1>(.*?)(?=<h1|$)',
            ]
        }
        
        extracted_sections = {}
        
        for section_name, patterns in prd_section_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
                if match:
                    section_html = match.group(1)
                    section_text = self._extract_text_content(section_html)
                    if section_text and len(section_text.strip()) > 10:
                        extracted_sections[section_name] = section_text
                        break  # Use first successful match for this section
        
        return extracted_sections
    
    def _extract_rfc_sections(self, page_data: Dict[str, Any]) -> Dict[str, str]:
        """Extract all RFC-specific sections from the page using BeautifulSoup for better parsing"""
        content = page_data.get('body', {}).get('storage', {}).get('value', '')
        if not content:
            return {}
        
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # Define RFC section patterns with more flexible matching
            rfc_section_mappings = {
                # Metadata
                'status': ['Status'],
                'owner': ['Owner'],
                'authors': ['Authors', 'Author'],
                
                # 1. Overview section
                'overview': ['Overview', '1. Overview'],
                'success_criteria': ['Success-Criteria', 'Success Criteria'],
                'out_of_scope': ['Out-of-Scope', 'Out of Scope'],
                'related_documents': ['Related-Documents', 'Related Documents'],
                'assumptions': ['Assumptions', 'Assumption'],
                'dependencies': ['Dependencies'],
                
                # 2. Technical Design section
                'technical_design': ['Technical-Design', 'Technical Design', '2. Technical Design'],
                'architecture_tech_stack': ['Architecture-&amp;-Tech-Stack', 'Architecture-Tech-Stack', 'Architecture & Tech Stack'],
                'sequence': ['Sequence'],
                'database_model': ['Database-Model', 'Database Model'],
                'apis': ['APIs', 'API'],
                
                # 3. High-Availability & Security section
                'high_availability_security': ['High-Availability-&amp;-Security', 'High-Availability-Security', 'High Availability & Security', '3. High Availability & Security'],
                'performance_requirement': ['Performance-Requirements', 'Performance Requirements', 'Performance-Requirement'],
                'monitoring_alerting': ['Monitoring-&amp;-Alerting', 'Monitoring-Alerting', 'Monitoring & Alerting'],
                'logging': ['Logging'],
                'security_implications': ['Security-Implications', 'Security Implications'],
                
                # 4. Backwards Compatibility and Rollout Plan section
                'backwards_compatibility_rollout': ['Backwards-Compatibility-&amp;-Rollout-Plan', 'Backwards Compatibility & Rollout Plan', '4. Backwards Compatibility & Rollout Plan'],
                'compatibility': ['Compatibility'],
                'rollout_strategy': ['Rollout-Strategy', 'Rollout Strategy'],
                
                # 5. Concerns, Questions, or Known Limitations section
                'concerns_questions_limitations': ['Concerns-Questions-Known-Limitations', 'Concerns, Questions, or Known Limitations', '5. Concerns, Questions, or Known Limitations'],
                
                # Additional common sections
                'alternatives_considered': ['Alternatives-Considered', 'Alternatives Considered'],
                'risks_and_mitigations': ['Risks-&amp;-Mitigations', 'Risks-Mitigations', 'Risks & Mitigations'],
                'testing_strategy': ['Testing-Strategy', 'Testing Strategy'],
                'timeline': ['Timeline', 'Milestones']
            }
            
            extracted_sections = {}
            
            for section_name, id_patterns in rfc_section_mappings.items():
                section_content = self._extract_section_content_bs(soup, id_patterns)
                if section_content and len(section_content.strip()) > 10:
                    extracted_sections[section_name] = section_content
            
            return extracted_sections
            
        except Exception as e:
            logger.warning(f"BeautifulSoup RFC extraction failed, falling back to regex: {e}")
            return self._extract_rfc_sections_regex(page_data)
    
    def _extract_rfc_sections_regex(self, page_data: Dict[str, Any]) -> Dict[str, str]:
        """Fallback RFC extraction using regex (original method)"""
        content = page_data.get('body', {}).get('storage', {}).get('value', '')
        if not content:
            return {}
        
        # Original RFC regex patterns as fallback
        rfc_section_patterns = {
            'overview': [
                r'<h1[^>]*>Overview</h1>(.*?)(?=<h[1-6]|$)',
                r'<h1[^>]*>1\.?\s*Overview</h1>(.*?)(?=<h[1-6]|$)',
            ],
            'technical_design': [
                r'<h1[^>]*>Technical Design</h1>(.*?)(?=<h[1-6]|$)',
                r'<h1[^>]*>2\.?\s*Technical Design</h1>(.*?)(?=<h[1-6]|$)',
            ],
            'architecture_tech_stack': [
                r'id="Architecture.*?Tech.*?Stack"[^>]*>(.*?)(?=<h[1-6]|$)',
                r'<h2[^>]*>Architecture.*?Tech.*?Stack</h2>(.*?)(?=<h[1-6]|$)',
            ],
            'security_implications': [
                r'id="Security-Implications?"[^>]*>(.*?)(?=<h[1-6]|$)',
                r'<h1[^>]*>Security Implications?</h1>(.*?)(?=<h[1-6]|$)',
            ],
            'performance_requirement': [
                r'id="Performance-Requirements?"[^>]*>(.*?)(?=<h[1-6]|$)',
                r'<h2[^>]*>Performance Requirements?</h2>(.*?)(?=<h[1-6]|$)',
            ],
        }
        
        extracted_sections = {}
        
        for section_name, patterns in rfc_section_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
                if match:
                    section_html = match.group(1)
                    section_text = self._extract_text_content(section_html)
                    if section_text and len(section_text.strip()) > 10:
                        extracted_sections[section_name] = section_text
                        break
        
        return extracted_sections

    def test_connection(self) -> bool:
        """Test the Confluence connection"""
        try:
            # Use the spaces endpoint which is more reliable
            # Construct URL properly for Confluence Cloud
            url = f"{self.server_url}/rest/api/space"
            logger.info(f"Testing Confluence connection to: {url}")
            response = self.session.get(url, timeout=10, params={'limit': 1})
            
            if response.status_code == 401:
                logger.error("401 Unauthorized - Check your Confluence username and API token")
                return False
            elif response.status_code == 404:
                logger.error("404 Not Found - Check your Confluence server URL (should include /wiki)")
                return False
                
            response.raise_for_status()
            logger.info("Confluence connection successful")
            return True
        except Exception as e:
            logger.error(f"Confluence connection test failed: {e}")
            return False
