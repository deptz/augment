import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from .models import (
    TicketInfo, PRDContent, RFCContent, PullRequest, Commit, 
    GenerationContext, GeneratedDescription, ProcessingResult, StoryInfo
)
from .planning_models import (
    PlanningContext, PlanningResult, OperationMode
)
from .planning_service import PlanningService
from .jira_client import JiraClient
from .bitbucket_client import BitbucketClient
from .confluence_client import ConfluenceClient
from .llm_client import LLMClient
from .prompts import Prompts

logger = logging.getLogger(__name__)


class DescriptionGenerator:
    """Main class for generating ticket descriptions and planning epics"""
    
    def __init__(
        self,
        jira_client: JiraClient,
        bitbucket_client: Optional[BitbucketClient],
        confluence_client: Optional[ConfluenceClient],
        llm_client: LLMClient,
        prompt_template: Optional[str] = None,
        include_code_analysis: bool = True,
        story_description_max_length: int = 300,
        story_description_summary_threshold: int = 500
    ):
        self.jira_client = jira_client
        self.bitbucket_client = bitbucket_client
        self.confluence_client = confluence_client
        self.llm_client = llm_client
        # Use centralized prompt as default, allow override via parameter
        self.prompt_template = prompt_template or Prompts.get_description_template()
        self.include_code_analysis = include_code_analysis
        
        # Configuration for story description handling
        self.story_description_max_length = story_description_max_length
        self.story_description_summary_threshold = story_description_summary_threshold
        
        logger.info(f"Story description config initialized: max_length={story_description_max_length}, summary_threshold={story_description_summary_threshold}")
        
        # Initialize planning service for dual-mode support
        self.planning_service = PlanningService(
            jira_client, confluence_client, llm_client
        )
        
        # Initialize enhanced test generator for test case generation
        from .enhanced_test_generator import EnhancedTestGenerator, TestCoverageLevel
        from .planning_prompt_engine import PlanningPromptEngine
        self.test_generator = EnhancedTestGenerator(
            llm_client,
            PlanningPromptEngine(),
            jira_client=jira_client,
            confluence_client=confluence_client
        ) if confluence_client else None
    
    def process_ticket(self, ticket_key: str, dry_run: bool = True, 
                    llm_model: Optional[str] = None, llm_provider: Optional[str] = None,
                    additional_context: Optional[str] = None) -> ProcessingResult:
        """Process a single ticket and generate description
        
        Args:
            ticket_key: JIRA ticket key
            dry_run: If True, don't actually update JIRA
            llm_model: Optional LLM model to override default
            llm_provider: Optional LLM provider to override default
            additional_context: Optional additional context to guide generation
        """
        try:
            logger.info(f"Processing ticket: {ticket_key}")
            
            # Get ticket information
            ticket_data = self.jira_client.get_ticket(ticket_key)
            if not ticket_data:
                return ProcessingResult(
                    ticket_key=ticket_key,
                    success=False,
                    error="Failed to fetch ticket data"
                )
            
            # Check if ticket should be updated (only when not in dry_run mode)
            # In preview mode (dry_run=True), we generate descriptions even if ticket already has one
            if not dry_run and not self.jira_client.should_update_ticket(ticket_data):
                return ProcessingResult(
                    ticket_key=ticket_key,
                    success=False,
                    skipped_reason="Ticket already has description"
                )
            
            # Build context
            context = self._build_context(ticket_data, additional_context)
            
            # Generate description (pass dry_run to include existing description when in preview mode)
            description = self._generate_description(context, llm_model, llm_provider, dry_run)
            if not description:
                return ProcessingResult(
                    ticket_key=ticket_key,
                    success=False,
                    error="Failed to generate description"
                )
            
            # Update ticket
            success = self.jira_client.update_ticket_description(
                ticket_key, description.description, dry_run
            )
            
            # Handle image attachments if description contains images (only if not dry run)
            if success and not dry_run:
                confluence_server_url = None
                if self.confluence_client:
                    confluence_server_url = self.confluence_client.server_url
                
                self.jira_client._attach_images_from_description(
                    ticket_key, 
                    description.description, 
                    confluence_server_url
                )
            
            # Add model and provider to the result
            llm_provider = None
            llm_model = None
            
            if description:
                llm_provider = description.llm_provider
                llm_model = description.llm_model
            
            return ProcessingResult(
                ticket_key=ticket_key,
                success=success,
                description=description,
                llm_provider=llm_provider,
                llm_model=llm_model
            )
            
        except Exception as e:
            logger.error(f"Error processing ticket {ticket_key}: {e}")
            return ProcessingResult(
                ticket_key=ticket_key,
                success=False,
                error=str(e)
            )
    
    def process_batch(self, jql: str, dry_run: bool = True, max_results: int = 100) -> List[ProcessingResult]:
        """Process multiple tickets based on JQL query"""
        logger.info(f"Processing batch with JQL: {jql}")
        
        try:
            tickets = self.jira_client.search_tickets(jql, max_results)
            logger.info(f"Found {len(tickets)} tickets to process")
            
            results = []
            for i, ticket_data in enumerate(tickets, 1):
                ticket_key = ticket_data['key']
                logger.info(f"Processing {i}/{len(tickets)}: {ticket_key}")
                
                result = self.process_ticket(ticket_key, dry_run)
                results.append(result)
                
                # Log progress
                if result.success:
                    logger.info(f"✓ Successfully processed {ticket_key}")
                elif result.skipped_reason:
                    logger.info(f"⊝ Skipped {ticket_key}: {result.skipped_reason}")
                else:
                    logger.error(f"✗ Failed {ticket_key}: {result.error}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error processing batch: {e}")
            return []
    
    def _build_context(self, ticket_data: Dict[str, Any], additional_context: Optional[str] = None) -> GenerationContext:
        """Build context for description generation"""
        fields = ticket_data.get('fields', {})
        
        # Get ALL story information via split relationships
        story_tickets_data = self.jira_client.find_story_tickets(ticket_data['key'])
        stories = []
        
        for story_data in story_tickets_data:
            if story_data:
                story_fields = story_data.get('fields', {})
                story_key = story_data['key']
                story_title = story_fields.get('summary', '')
                story_description = self._extract_description_text(story_fields.get('description'))
                
                stories.append(StoryInfo(
                    key=story_key,
                    title=story_title,
                    description=story_description
                ))
                logger.debug(f"Added story {story_key} for ticket {ticket_data['key']}")
        
        # Build ticket info
        ticket = TicketInfo(
            key=ticket_data['key'],
            title=fields.get('summary', ''),
            description=self._extract_description_text(fields.get('description')),
            status=fields.get('status', {}).get('name', ''),
            parent_key=fields.get('parent', {}).get('key') if fields.get('parent') else None,
            parent_summary=fields.get('parent', {}).get('fields', {}).get('summary') if fields.get('parent') else None,
            stories=stories,
            prd_url=self._extract_prd_url_from_hierarchy(ticket_data),
            rfc_url=self._extract_rfc_url_from_hierarchy(ticket_data),
            created=self._parse_jira_datetime(fields.get('created')),
            updated=self._parse_jira_datetime(fields.get('updated'))
        )
        
        context = GenerationContext(ticket=ticket)
        
        # Store additional context
        context.additional_context = additional_context
        
        # Get PRD content
        if ticket.prd_url and self.confluence_client:
            prd_content = self._fetch_prd_content(ticket.prd_url)
            if prd_content:
                context.prd = prd_content
                
        # Get RFC content
        if ticket.rfc_url and self.confluence_client:
            rfc_content = self._fetch_rfc_content(ticket.rfc_url)
            if rfc_content:
                context.rfc = rfc_content
        
        # Get Bitbucket data
        if self.bitbucket_client:
            logger.debug(f"Fetching pull requests and commits for {ticket.key}, include_code_analysis={self.include_code_analysis}")
            pull_requests = self._fetch_pull_requests(ticket.key, self.include_code_analysis)
            commits = self._fetch_commits(ticket.key, self.include_code_analysis)
            
            logger.debug(f"Found {len(pull_requests)} PRs and {len(commits)} commits for {ticket.key}")
            
            # Debug: check if PRs have code_changes
            for i, pr in enumerate(pull_requests):
                if pr.code_changes:
                    logger.debug(f"PR {i+1} has code_changes: {len(pr.code_changes.get('files_changed', []))} files")
                else:
                    logger.debug(f"PR {i+1} has no code_changes")
            
            context.pull_requests = pull_requests
            context.commits = commits
        
        return context
    
    def _fetch_prd_content(self, prd_url: str) -> Optional[PRDContent]:
        """Fetch PRD/RFC content from Confluence with enhanced section extraction"""
        try:
            page_data = self.confluence_client.get_page_content(prd_url)
            if not page_data:
                return None
            
            # Extract enhanced PRD sections
            prd_sections = page_data.get('prd_sections', {})
            
            # Build enhanced content with structured sections
            enhanced_content = page_data.get('content', '')
            
            # Add structured section information if available
            if prd_sections:
                section_summary = []
                
                # Get content limits based on operation mode (detect if we're in planning mode)
                content_limits = self._get_prd_content_limits()
                
                # Get priority sections based on operation mode
                priority_sections = self._get_priority_prd_sections()
                
                for section_key, section_title in priority_sections:
                    if section_key in prd_sections:
                        section_content = prd_sections[section_key]
                        if len(section_content.strip()) > 20:  # Only include meaningful content
                            # Apply adaptive content limits
                            max_section_length = content_limits['prd_section_max']
                            truncated_content = self._truncate_content(section_content, max_section_length)
                            section_summary.append(f"**{section_title}**: {truncated_content}")
                
                if section_summary:
                    enhanced_content = "\n\n".join(section_summary) + "\n\n" + enhanced_content
            
            return PRDContent(
                title=page_data['title'],
                url=page_data['url'],
                summary=page_data.get('summary'),
                goals=page_data.get('goals'),
                content=enhanced_content
            )
            
        except Exception as e:
            logger.warning(f"Failed to fetch PRD content from {prd_url}: {e}")
            return None
    
    def _get_prd_content_limits(self) -> Dict[str, int]:
        """Get content limits for PRD sections based on operation context"""
        # Try to detect if we're in planning mode by checking the call stack
        import inspect
        
        frame = inspect.currentframe()
        is_planning_mode = False
        
        try:
            # Look up the call stack to see if we're called from planning methods
            while frame:
                frame = frame.f_back
                if frame and frame.f_code:
                    func_name = frame.f_code.co_name
                    if func_name in ['plan_epic_complete', 'generate_stories_for_epic', 'generate_tasks_for_stories']:
                        is_planning_mode = True
                        break
        except:
            pass
        finally:
            del frame  # Prevent reference cycles
        
        if is_planning_mode:
            return {
                'prd_section_max': 800,     # More context for planning
                'total_sections': 12        # More sections for comprehensive planning
            }
        else:
            return {
                'prd_section_max': 500,     # Current behavior for generation
                'total_sections': 8         # Focused selection for single task generation
            }

    def _get_priority_prd_sections(self) -> List[Tuple[str, str]]:
        """Get priority PRD sections based on operation context
        
        Supports two PRD templates:
        - Template 1: User Value focused (user_value, business_value, strategic_impact)
        - Template 2: Goals focused (goals, business_goals, user_goals, tldr)
        
        Sections are tried in order; whichever exists in the PRD will be used.
        """
        # Try to detect if we're in planning mode
        import inspect
        
        frame = inspect.currentframe()
        is_planning_mode = False
        
        try:
            while frame:
                frame = frame.f_back
                if frame and frame.f_code:
                    func_name = frame.f_code.co_name
                    if func_name in ['plan_epic_complete', 'generate_stories_for_epic', 'generate_tasks_for_stories']:
                        is_planning_mode = True
                        break
        except:
            pass
        finally:
            del frame
        
        # Core sections for all modes - includes both templates
        core_sections = [
            # Template 2 sections (try first for Goals-focused PRDs)
            ('tldr', 'TL;DR'),
            ('problem_statement', 'Problem Statement'),
            ('business_goals', 'Business Goals'),
            ('user_goals', 'User Goals'),
            
            # Template 1 sections (fallback for User Value-focused PRDs)
            ('user_problem_definition', 'User Problem Definition'),
            ('user_value', 'User Value'),
            ('business_value', 'Business Value'),
            
            # Common sections (both templates)
            ('proposed_solution', 'Proposed Solution'),
            ('success_criteria', 'Success Criteria / Metrics'),
        ]
        
        if is_planning_mode:
            # Planning needs comprehensive context - sections from both templates
            planning_sections = [
                ('target_population', 'Target Population'),
                
                # Template 2 strategic sections
                ('product_narrative', 'Product Narrative'),
                ('opportunity_strategic_fit', 'Opportunity & Strategic Fit'),
                ('why_it_matters', 'Why It Matters'),
                ('pain_points_solved', 'Pain Points Solved'),
                ('key_features', 'Key Features'),
                
                # Template 1 strategic sections
                ('strategic_impact', 'Strategic Impact'),
                ('business_impact', 'Business Impact'),
                
                # Implementation context
                ('constraints_limitation', 'Constraints & Limitations'),
                ('user_stories', 'User Stories & Acceptance Criteria'),
                ('description_flow', 'Description & Flow / User Experience Flow'),
                ('user_problem_frequency', 'User Problem Frequency & Severity'),
                ('user_problem_severity', 'User Problem Severity'),
                ('future_considerations', 'Future Considerations'),
            ]
            return core_sections + planning_sections
        else:
            # Generation mode focuses on implementation context - both templates
            generation_sections = [
                ('target_population', 'Target Population'),
                
                # Template 2 implementation sections
                ('pain_points_solved', 'Pain Points Solved'),
                ('key_features', 'Key Features'),
                
                # Template 1 implementation sections
                ('business_impact', 'Business Impact'),
                
                # Common implementation context
                ('constraints_limitation', 'Constraints & Limitations'),
                ('user_stories', 'User Stories & Acceptance Criteria'),
                ('description_flow', 'User Experience Flow'),
            ]
            return core_sections + generation_sections

    def _truncate_content(self, content: str, max_length: int) -> str:
        """Truncate content to fit within prompt length limits with smart truncation"""
        if len(content) <= max_length:
            return content
        
        # Try to truncate at sentence boundary
        truncated = content[:max_length - 100]
        
        # Look for sentence endings within a reasonable range
        sentence_endings = ['. ', '! ', '? ', '\n\n']
        best_cut = -1
        
        # Look backwards from the truncation point for a good sentence ending
        for i in range(min(50, len(truncated))):  # Look back up to 50 chars
            pos = max_length - 100 - i
            if pos < max_length // 2:  # Don't cut too much (less than half)
                break
                
            for ending in sentence_endings:
                if pos + len(ending) <= len(truncated) and truncated[pos:pos+len(ending)] == ending:
                    best_cut = pos + len(ending)
                    break
            
            if best_cut != -1:
                break
        
        if best_cut != -1:
            return truncated[:best_cut].strip() + "\n... [Content truncated for length] ..."
        else:
            # No good sentence boundary found, do regular truncation
            return truncated + "\n... [Content truncated for length] ..."
    
    def _fetch_rfc_content(self, rfc_url: str) -> Optional[RFCContent]:
        """Fetch RFC content from Confluence with comprehensive section extraction"""
        try:
            page_data = self.confluence_client.get_page_content(rfc_url)
            if not page_data:
                return None
            
            # Extract RFC sections using the new extraction method
            rfc_sections = page_data.get('rfc_sections', {})
            
            # Build RFC content with the comprehensive field coverage
            rfc_content = RFCContent(
                # Metadata
                status=rfc_sections.get('status'),
                owner=rfc_sections.get('owner'),
                authors=rfc_sections.get('authors'),
                
                # 1. Overview section
                overview=rfc_sections.get('overview'),
                success_criteria=rfc_sections.get('success_criteria'),
                out_of_scope=rfc_sections.get('out_of_scope'),
                related_documents=rfc_sections.get('related_documents'),
                assumptions=rfc_sections.get('assumptions'),
                dependencies=rfc_sections.get('dependencies'),
                
                # 2. Technical Design section
                technical_design=rfc_sections.get('technical_design'),
                architecture_tech_stack=rfc_sections.get('architecture_tech_stack'),
                sequence=rfc_sections.get('sequence'),
                database_model=rfc_sections.get('database_model'),
                apis=rfc_sections.get('apis'),
                
                # 3. High-Availability & Security section
                high_availability_security=rfc_sections.get('high_availability_security'),
                performance_requirement=rfc_sections.get('performance_requirement'),
                monitoring_alerting=rfc_sections.get('monitoring_alerting'),
                logging=rfc_sections.get('logging'),
                security_implications=rfc_sections.get('security_implications'),
                
                # 4. Backwards Compatibility and Rollout Plan section
                backwards_compatibility_rollout=rfc_sections.get('backwards_compatibility_rollout'),
                compatibility=rfc_sections.get('compatibility'),
                rollout_strategy=rfc_sections.get('rollout_strategy'),
                
                # 5. Concern, Questions, or Known Limitations section
                concerns_questions_limitations=rfc_sections.get('concerns_questions_limitations'),
                
                # Additional common sections
                alternatives_considered=rfc_sections.get('alternatives_considered'),
                risks_and_mitigations=rfc_sections.get('risks_and_mitigations'),
                testing_strategy=rfc_sections.get('testing_strategy'),
                timeline=rfc_sections.get('timeline')
            )
            
            return rfc_content
            
        except Exception as e:
            logger.warning(f"Failed to fetch RFC content from {rfc_url}: {e}")
            return None
    
    def _fetch_pull_requests(self, ticket_key: str, include_code_analysis: bool = False) -> List[PullRequest]:
        """Fetch pull requests related to the ticket"""
        try:
            pr_data = self.bitbucket_client.find_pull_requests_for_ticket(ticket_key, include_diff=include_code_analysis)
            
            pull_requests = []
            for pr in pr_data:
                pull_requests.append(PullRequest(
                    id=str(pr['id']),
                    title=pr['title'],
                    description=pr.get('description'),
                    source_branch=pr['source_branch'],
                    destination_branch=pr['destination_branch'],
                    state=pr['state'],
                    created_on=self._parse_bitbucket_datetime(pr.get('created_on')),
                    diff=pr.get('diff'),
                    code_changes=pr.get('code_changes')
                ))
            
            return pull_requests
            
        except Exception as e:
            logger.warning(f"Failed to fetch pull requests for {ticket_key}: {e}")
            return []
    
    def _fetch_commits(self, ticket_key: str, include_code_analysis: bool = False) -> List[Commit]:
        """Fetch commits related to the ticket"""
        try:
            commit_data = self.bitbucket_client.find_commits_for_ticket(ticket_key, include_diff=include_code_analysis)
            
            commits = []
            for commit in commit_data:
                commits.append(Commit(
                    hash=commit['hash'],
                    message=commit['message'],
                    author=commit['author'],
                    date=self._parse_bitbucket_datetime(commit.get('date')),
                    diff=commit.get('diff'),
                    code_changes=commit.get('code_changes')
                ))
            
            return commits
            
        except Exception as e:
            logger.warning(f"Failed to fetch commits for {ticket_key}: {e}")
            return []
    
    def _generate_description(self, context: GenerationContext, 
                         llm_model: Optional[str] = None, 
                         llm_provider: Optional[str] = None,
                         dry_run: bool = True) -> Optional[GeneratedDescription]:
        """Generate description using LLM
        
        Args:
            context: Generation context with ticket info, PRD, PRs, etc.
            llm_model: Optional LLM model to override default
            llm_provider: Optional LLM provider to override default
            dry_run: Whether this is a dry run (preview mode)
        """
        try:
            logger.debug(f"Generating description for {context.ticket.key}")
            
            # Build prompt using template (this is the user prompt)
            user_prompt = self._build_prompt(context, dry_run)
            
            # Generate description using the prompt
            used_provider = None
            used_model = None
            system_prompt = None
            
            if llm_model or llm_provider:
                # Get fresh config for the specified provider
                from .config import Config
                config = Config()
                current_config = config.get_llm_config(llm_provider, llm_model)
                
                logger.info(f"Using custom LLM configuration: provider={current_config['provider']}, model={current_config['model']}")
                
                # Create temporary client with these settings
                temp_client = LLMClient(current_config)
                system_prompt = temp_client.get_system_prompt()
                # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
                description_text = temp_client.generate_description(user_prompt)
                
                used_provider = current_config['provider']
                used_model = current_config['model']
            else:
                # Use the default client
                system_prompt = self.llm_client.get_system_prompt()
                # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
                description_text = self.llm_client.provider.generate_description(user_prompt, max_tokens=None)
                used_provider = self.llm_client.provider_name
                used_model = self.llm_client.provider.model
            
            # Determine sources used
            sources_used = ["Jira ticket"]
            if context.prd:
                sources_used.append("PRD/RFC")
            if context.pull_requests:
                sources_used.append("Pull requests")
            if context.commits:
                sources_used.append("Commits")
            
            # Check for warnings
            warnings = []
            if not context.prd:
                warnings.append("No PRD/RFC found - purpose may be generic")
            if not context.pull_requests and not context.commits:
                warnings.append("No code artifacts found - scopes may be limited")
            
            return GeneratedDescription(
                ticket_key=context.ticket.key,
                description=description_text,
                sources_used=sources_used,
                warnings=warnings,
                llm_provider=used_provider,
                llm_model=used_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )
            
        except Exception as e:
            logger.error(f"Failed to generate description for {context.ticket.key}: {e}")
            return None
    
    def _build_prompt(self, context: GenerationContext, dry_run: bool = True) -> str:
        """Build the prompt for LLM
        
        Args:
            context: Generation context with ticket info, PRD, PRs, etc.
            dry_run: Whether this is a dry run (preview mode). When True and ticket has existing description, it will be explicitly included.
        """
        # Format ticket description - when in dry_run mode and description exists, ensure it's included
        ticket_description = self._format_ticket_description(context.ticket.description, dry_run)
        
        # Prepare template variables - prioritizing ticket-specific information
        template_vars = {
            'ticket_key': context.ticket.key,
            'ticket_title': context.ticket.title,
            'ticket_description': ticket_description,
            'parent_summary': context.ticket.parent_summary or 'N/A',
            'story_information': self._format_story_information(context.ticket.stories),
            'prd_title': context.prd.title if context.prd else 'N/A',
            'prd_summary': context.prd.summary if context.prd else 'N/A',
            'prd_goals': context.prd.goals if context.prd else 'N/A',
            'rfc_technical_summary': self._format_rfc_technical_summary(context.rfc),
            'rfc_implementation_summary': self._format_rfc_implementation_summary(context.rfc),
            'rfc_security_performance_summary': self._format_rfc_security_performance_summary(context.rfc),
            'pull_request_details': self._format_pull_request_details(context.pull_requests),
            'commit_messages': self._format_commit_messages(context.commits),
            'changed_files': self._format_changed_files(context.pull_requests, context.commits),
            'code_changes_summary': self._format_code_changes_summary(context.pull_requests, context.commits),
            'additional_context': self._format_additional_context(context.additional_context)
        }
        
        # Replace template variables
        prompt = self.prompt_template
        for var, value in template_vars.items():
            prompt = prompt.replace(f'{{{{{var}}}}}', str(value))
        
        return prompt
    
    def _format_story_information(self, stories: List[StoryInfo]) -> str:
        """Format story information for the prompt - providing broader context"""
        if not stories:
            return "N/A"
        
        formatted_stories = []
        for story in stories:
            story_info = f"**Story {story.key}**: {story.title}"
            if story.description and story.description.strip():
                description = story.description.strip()
                original_length = len(description)
                
                # Use AI summarization for long descriptions, smart truncation for medium ones
                if len(description) > self.story_description_summary_threshold:
                    logger.debug(f"Story {story.key}: Using AI summarization ({original_length} chars > {self.story_description_summary_threshold} threshold)")
                    # Use AI to summarize while preserving key context
                    description = self._summarize_story_description(description, self.story_description_max_length)
                elif len(description) > self.story_description_max_length:
                    logger.debug(f"Story {story.key}: Using smart truncation ({original_length} chars > {self.story_description_max_length} max_length)")
                    # Smart truncation at sentence boundary
                    description = self._smart_truncate(description, self.story_description_max_length)
                else:
                    logger.debug(f"Story {story.key}: Keeping full description ({original_length} chars <= {self.story_description_max_length} max_length)")
                
                story_info += f"\n  Context: {description}"
            formatted_stories.append(story_info)
        
        return "\n\n".join(formatted_stories)

    def _format_rfc_technical_summary(self, rfc: Optional[RFCContent]) -> str:
        """Format RFC technical summary for the prompt"""
        if not rfc:
            return "N/A"
        
        return rfc.get_technical_summary()
    
    def _format_rfc_implementation_summary(self, rfc: Optional[RFCContent]) -> str:
        """Format RFC implementation summary for the prompt"""
        if not rfc:
            return "N/A"
        
        return rfc.get_implementation_summary()
    
    def _format_rfc_security_performance_summary(self, rfc: Optional[RFCContent]) -> str:
        """Format RFC security and performance summary for the prompt"""
        if not rfc:
            return "N/A"
        
        return rfc.get_security_and_performance_summary()

    def _format_additional_context(self, additional_context: Optional[str]) -> str:
        """Format additional context for the prompt"""
        if not additional_context:
            return "N/A"
        
        # Truncate to 1000 chars max with smart boundary
        if len(additional_context) > 1000:
            return self._smart_truncate(additional_context, 1000)
        
        return additional_context

    def _format_pull_request_titles(self, pull_requests: List[PullRequest]) -> str:
        """Format pull request titles for the prompt"""
        if not pull_requests:
            return "N/A"
        
        titles = []
        for pr in pull_requests[:5]:  # Limit to 5
            title_line = f"- {pr.title}"
            if pr.code_changes and pr.code_changes.get('change_summary'):
                summary = ', '.join(pr.code_changes['change_summary'])
                title_line += f" ({summary})"
            titles.append(title_line)
        
        return "\n".join(titles)
    
    def _format_commit_messages(self, commits: List[Commit]) -> str:
        """Format commit messages for the prompt"""
        if not commits:
            return "N/A"
        
        messages = []
        for commit in commits[:10]:  # Limit to 10, first line only
            first_line = commit.message.split('\n')[0]
            message_line = f"- {first_line}"
            if commit.code_changes and commit.code_changes.get('change_summary'):
                summary = ', '.join(commit.code_changes['change_summary'])
                message_line += f" ({summary})"
            messages.append(message_line)
        
        return "\n".join(messages)
    
    def _format_code_changes_summary(self, pull_requests: List[PullRequest], commits: List[Commit]) -> str:
        """Format a comprehensive code changes summary"""
        if not pull_requests and not commits:
            return "N/A"
        
        summary_parts = []
        
        # Aggregate file types and changes
        all_file_types = set()
        total_files = 0
        total_additions = 0
        total_deletions = 0
        all_files_changed = set()
        has_detailed_diff_data = False
        
        # From pull requests
        for pr in pull_requests:
            if pr.code_changes:
                has_detailed_diff_data = True
                changes = pr.code_changes
                all_file_types.update(changes.get('file_types', []))
                files_changed = changes.get('files_changed', [])
                total_files += len(files_changed)
                total_additions += changes.get('additions', 0)
                total_deletions += changes.get('deletions', 0)
                
                # Collect actual file names
                for file_info in files_changed:
                    if isinstance(file_info, dict) and 'file' in file_info:
                        all_files_changed.add(file_info['file'])
                    elif isinstance(file_info, str):
                        all_files_changed.add(file_info)
        
        # From commits (if no PR data available)
        if not pull_requests:
            for commit in commits:
                if commit.code_changes:
                    has_detailed_diff_data = True
                    changes = commit.code_changes
                    all_file_types.update(changes.get('file_types', []))
                    files_changed = changes.get('files_changed', [])
                    total_files += len(files_changed)
                    total_additions += changes.get('additions', 0)
                    total_deletions += changes.get('deletions', 0)
                    
                    # Collect actual file names
                    for file_info in files_changed:
                        if isinstance(file_info, dict) and 'file' in file_info:
                            all_files_changed.add(file_info['file'])
                        elif isinstance(file_info, str):
                            all_files_changed.add(file_info)
        
        # If we have detailed diff data, use it
        if has_detailed_diff_data and total_files > 0:
            summary_parts.append(f"Modified {total_files} files")
            summary_parts.append(f"+{total_additions} -{total_deletions} lines")
            
            if all_file_types:
                file_types_list = list(all_file_types)[:5]  # Limit to 5
                file_types_str = ', '.join(file_types_list)
                if len(all_file_types) > 5:
                    file_types_str += f" and {len(all_file_types) - 5} more"
                summary_parts.append(f"File types: {file_types_str}")
            
            # Add actual file names (limited to prevent prompt overflow)
            if all_files_changed:
                files_list = list(all_files_changed)[:10]  # Limit to 10 files
                files_str = ', '.join(files_list)
                if len(all_files_changed) > 10:
                    files_str += f" and {len(all_files_changed) - 10} more files"
                summary_parts.append(f"Affected files: {files_str}")
        else:
            # Fallback: extract information from PR titles and commit messages
            activities = []
            
            # Analyze PR titles for patterns
            for pr in pull_requests:
                if pr.title:
                    activities.append(pr.title)
            
            # Analyze commit messages for patterns
            for commit in commits:
                if commit.message:
                    first_line = commit.message.split('\n')[0]
                    activities.append(first_line)
            
            if activities:
                # Extract common patterns and infer activities
                inferred_changes = self._infer_changes_from_messages(activities)
                if inferred_changes:
                    summary_parts.append(f"Inferred changes: {inferred_changes}")
                
                # Also provide a summary of the actual activities
                activity_summary = []
                if pull_requests:
                    pr_titles = [pr.title for pr in pull_requests if pr.title]
                    if pr_titles:
                        activity_summary.append(f"PRs: {'; '.join(pr_titles[:2])}")
                        if len(pr_titles) > 2:
                            activity_summary.append(f"and {len(pr_titles) - 2} more PRs")
                
                if commits:
                    commit_msgs = [commit.message.split('\n')[0] for commit in commits if commit.message]
                    unique_commits = list(set(commit_msgs))[:3]  # Deduplicate and limit
                    if unique_commits:
                        activity_summary.append(f"Commits: {'; '.join(unique_commits)}")
                        if len(commit_msgs) > 3:
                            activity_summary.append(f"and {len(commit_msgs) - 3} more commits")
                
                if activity_summary:
                    summary_parts.append(" | ".join(activity_summary))
                else:
                    summary_parts.append(f"Activities: {len(pull_requests)} PRs, {len(commits)} commits")
            else:
                summary_parts.append("No detailed diff data available")
        
        return "; ".join(summary_parts) if summary_parts else "N/A"
    
    def _infer_changes_from_messages(self, messages: List[str]) -> str:
        """Infer types of changes from commit messages and PR titles"""
        change_patterns = {
            'configuration': ['env', 'config', 'setting', 'property', 'variable'],
            'authentication': ['auth', 'login', 'verify', 'credential', 'token'],
            'api': ['api', 'endpoint', 'service', 'rest'],
            'database': ['db', 'database', 'migration', 'schema'],
            'ui': ['ui', 'frontend', 'component', 'page', 'view'],
            'test': ['test', 'spec', 'junit', 'unit'],
            'fix': ['fix', 'bug', 'issue', 'error'],
            'feature': ['feature', 'add', 'new', 'implement'],
            'refactor': ['refactor', 'cleanup', 'optimize', 'improve']
        }
        
        detected_changes = set()
        
        for message in messages:
            message_lower = message.lower()
            for change_type, keywords in change_patterns.items():
                if any(keyword in message_lower for keyword in keywords):
                    detected_changes.add(change_type)
        
        if detected_changes:
            return ', '.join(sorted(detected_changes))
        
        return ""

    def _format_changed_files(self, pull_requests: List[PullRequest], commits: List[Commit]) -> str:
        """Format a list of changed files according to PRD specification"""
        if not pull_requests and not commits:
            return "N/A"
        
        all_files_changed = set()
        has_detailed_diff_data = False
        
        # From pull requests
        for pr in pull_requests:
            if pr.code_changes:
                has_detailed_diff_data = True
                changes = pr.code_changes
                files_changed = changes.get('files_changed', [])
                
                # Collect actual file names
                for file_info in files_changed:
                    if isinstance(file_info, dict) and 'file' in file_info:
                        all_files_changed.add(file_info['file'])
                    elif isinstance(file_info, str):
                        all_files_changed.add(file_info)
        
        # From commits (if no PR data available)
        if not pull_requests:
            for commit in commits:
                if commit.code_changes:
                    has_detailed_diff_data = True
                    changes = commit.code_changes
                    files_changed = changes.get('files_changed', [])
                    
                    # Collect actual file names
                    for file_info in files_changed:
                        if isinstance(file_info, dict) and 'file' in file_info:
                            all_files_changed.add(file_info['file'])
                        elif isinstance(file_info, str):
                            all_files_changed.add(file_info)
        
        if has_detailed_diff_data and all_files_changed:
            # Format as a simple list, limited to prevent prompt overflow
            files_list = list(all_files_changed)[:15]  # Limit to 15 files
            files_str = ', '.join(files_list)
            if len(all_files_changed) > 15:
                files_str += f" and {len(all_files_changed) - 15} more files"
            return files_str
        else:
            # Fallback: indicate we have activity but no detailed file data
            total_activities = len(pull_requests) + len(commits)
            if total_activities > 0:
                return f"File details unavailable ({len(pull_requests)} PRs, {len(commits)} commits detected)"
        
        return "N/A"
    
    def _format_ticket_description(self, description, dry_run: bool = True) -> str:
        """Format ticket description for the prompt
        
        Args:
            description: The ticket description (can be ADF format or plain text)
            dry_run: Whether this is a dry run. When True and description exists, explicitly includes it for LLM context.
        """
        if not description:
            return "N/A"
        
        # Extract text from Jira description format
        description_text = self._extract_description_text(description)
        if not description_text or not description_text.strip():
            return "N/A"
        
        # Truncate if too long
        if len(description_text) > 800:
            description_text = description_text[:800] + "..."
        
        formatted_text = description_text.strip()
        
        # When in dry_run mode and description exists, explicitly note it's an existing description
        # This helps the LLM understand it should consider/improve the existing content
        if dry_run and formatted_text and formatted_text != "N/A":
            return f"[EXISTING DESCRIPTION - Use as context for improvement/regeneration]\n{formatted_text}"
        
        return formatted_text
    
    def _format_pull_request_details(self, pull_requests: List[PullRequest]) -> str:
        """Format pull request details including titles and descriptions for the prompt"""
        if not pull_requests:
            return "N/A"
        
        pr_details = []
        for pr in pull_requests[:3]:  # Limit to 3 PRs
            detail_line = f"- **{pr.title}**"
            
            # Add code changes summary if available
            if pr.code_changes and pr.code_changes.get('change_summary'):
                summary = ', '.join(pr.code_changes['change_summary'])
                detail_line += f" (Changes: {summary})"
            
            # Add PR description if available and meaningful
            if pr.description and pr.description.strip() and len(pr.description.strip()) > 10:
                # Truncate description if too long
                desc = pr.description.strip()
                if len(desc) > 200:
                    desc = desc[:200] + "..."
                detail_line += f"\n  Description: {desc}"
            
            pr_details.append(detail_line)
        
        return "\n\n".join(pr_details)

    def _parse_jira_datetime(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse Jira datetime string"""
        if not date_str:
            return None
        
        try:
            # Jira format: 2023-08-15T10:30:00.000+0000
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except Exception:
            return None
    
    def _parse_bitbucket_datetime(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse Bitbucket datetime string"""
        if not date_str:
            return None
        
        try:
            # Bitbucket format: 2023-08-15T10:30:00+00:00
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except Exception:
            return None
    
    def _extract_prd_url_from_hierarchy(self, ticket_data: Dict[str, Any]) -> Optional[str]:
        """Extract PRD URL from the ticket hierarchy (parent/EPIC first, then current ticket)"""
        fields = ticket_data.get('fields', {})
        
        # First, check if the current ticket has a parent (Story -> EPIC relationship)
        if fields.get('parent'):
            parent_key = fields['parent']['key']
            logger.debug(f"Found parent ticket: {parent_key}")
            
            try:
                # Get parent ticket data
                parent_data = self.jira_client.get_ticket(parent_key)
                parent_prd_url = self.jira_client.extract_prd_url(parent_data)
                if parent_prd_url:
                    logger.debug(f"Found PRD URL in parent {parent_key}: {parent_prd_url}")
                    return parent_prd_url
                    
                # If parent doesn't have PRD, check if parent has a parent (EPIC)
                parent_fields = parent_data.get('fields', {})
                if parent_fields.get('parent'):
                    grandparent_key = parent_fields['parent']['key']
                    logger.debug(f"Found grandparent ticket: {grandparent_key}")
                    
                    grandparent_data = self.jira_client.get_ticket(grandparent_key)
                    grandparent_prd_url = self.jira_client.extract_prd_url(grandparent_data)
                    if grandparent_prd_url:
                        logger.debug(f"Found PRD URL in grandparent {grandparent_key}: {grandparent_prd_url}")
                        return grandparent_prd_url
                        
            except Exception as e:
                logger.warning(f"Failed to fetch parent ticket data: {e}")
        
        # Fallback: check current ticket
        current_prd_url = self.jira_client.extract_prd_url(ticket_data)
        if current_prd_url:
            logger.debug(f"Found PRD URL in current ticket: {current_prd_url}")
            return current_prd_url
            
        logger.debug("No PRD URL found in ticket hierarchy")
        return None
    
    def _extract_rfc_url_from_hierarchy(self, ticket_data: Dict[str, Any]) -> Optional[str]:
        """Extract RFC URL from the ticket hierarchy (parent/EPIC first, then current ticket)"""
        fields = ticket_data.get('fields', {})
        
        # First, check if the current ticket has a parent (Story -> EPIC relationship)
        if fields.get('parent'):
            parent_key = fields['parent']['key']
            logger.debug(f"Found parent ticket: {parent_key}")
            
            try:
                # Get parent ticket data
                parent_data = self.jira_client.get_ticket(parent_key)
                parent_rfc_url = self.jira_client.extract_rfc_url(parent_data)
                if parent_rfc_url:
                    logger.debug(f"Found RFC URL in parent {parent_key}: {parent_rfc_url}")
                    return parent_rfc_url
                    
                # If parent doesn't have RFC, check if parent has a parent (EPIC)
                parent_fields = parent_data.get('fields', {})
                if parent_fields.get('parent'):
                    grandparent_key = parent_fields['parent']['key']
                    logger.debug(f"Found grandparent ticket: {grandparent_key}")
                    
                    grandparent_data = self.jira_client.get_ticket(grandparent_key)
                    grandparent_rfc_url = self.jira_client.extract_rfc_url(grandparent_data)
                    if grandparent_rfc_url:
                        logger.debug(f"Found RFC URL in grandparent {grandparent_key}: {grandparent_rfc_url}")
                        return grandparent_rfc_url
                        
            except Exception as e:
                logger.warning(f"Failed to fetch parent ticket data for RFC: {e}")
        
        # Fallback: check current ticket
        current_rfc_url = self.jira_client.extract_rfc_url(ticket_data)
        if current_rfc_url:
            logger.debug(f"Found RFC URL in current ticket: {current_rfc_url}")
            return current_rfc_url
            
        logger.debug("No RFC URL found in ticket hierarchy")
        return None
    
    def _extract_description_text(self, description_field: Any) -> Optional[str]:
        """Extract plain text from Jira description field (which might be ADF format)"""
        if not description_field:
            return None
        
        # If it's already a string, return it
        if isinstance(description_field, str):
            return description_field.strip() if description_field.strip() else None
        
        # If it's ADF (Atlassian Document Format), extract text
        if isinstance(description_field, dict):
            try:
                # Use the same extraction logic as the Jira client
                return self.jira_client._extract_text_from_adf(description_field)
            except Exception as e:
                logger.warning(f"Failed to extract text from ADF description: {e}")
                return None
        
        return None

    # =====================================
    # PLANNING MODE METHODS (Top-Down)
    # =====================================
    
    def plan_epic_complete(
        self, 
        epic_key: str, 
        dry_run: bool = True,
        split_oversized_tasks: bool = True,
        generate_test_cases: bool = True,
        max_task_cycle_days: float = 3.0
    ) -> PlanningResult:
        """
        Complete planning for an epic - analyze gaps and generate all missing stories/tasks
        
        Args:
            epic_key: JIRA epic key to plan
            dry_run: If True, don't actually create tickets
            split_oversized_tasks: Automatically split tasks exceeding cycle time limit
            generate_test_cases: Generate test cases for stories and tasks
            max_task_cycle_days: Maximum cycle time allowed per task
            
        Returns:
            PlanningResult with generated plan and execution details
        """
        if not self.planning_service:
            return PlanningResult(
                epic_key=epic_key,
                mode=OperationMode.PLANNING,
                success=False,
                errors=["Planning service not available - requires Confluence client"]
            )
        
        logger.info(f"Starting complete epic planning for {epic_key}")
        
        context = PlanningContext(
            mode=OperationMode.PLANNING,
            epic_key=epic_key,
            max_task_cycle_days=max_task_cycle_days,
            split_oversized_tasks=split_oversized_tasks,
            generate_test_cases=generate_test_cases,
            create_missing_stories=True,
            create_missing_tasks=True,
            dry_run=dry_run
        )
        
        return self.planning_service.plan_epic_complete(context)
    
    def generate_stories_for_epic(
        self, 
        epic_key: str, 
        dry_run: bool = True
    ) -> PlanningResult:
        """
        Generate only stories for an epic (without tasks)
        
        Args:
            epic_key: JIRA epic key
            dry_run: If True, don't actually create tickets
            
        Returns:
            PlanningResult with generated stories
        """
        if not self.planning_service:
            return PlanningResult(
                epic_key=epic_key,
                mode=OperationMode.PLANNING,
                success=False,
                errors=["Planning service not available - requires Confluence client"]
            )
        
        logger.info(f"Generating stories for epic {epic_key}")
        
        context = PlanningContext(
            mode=OperationMode.PLANNING,
            epic_key=epic_key,
            create_missing_stories=True,
            create_missing_tasks=False,
            dry_run=dry_run
        )
        
        return self.planning_service.generate_stories_for_epic(context)
    
    def generate_tasks_for_stories(
        self, 
        story_keys: List[str], 
        epic_key: str,
        dry_run: bool = True,
        split_oversized_tasks: bool = True,
        max_task_cycle_days: float = 3.0,
        max_tasks_per_story: int = 10,
        custom_llm_client: Optional['LLMClient'] = None,
        additional_context: Optional[str] = None
    ) -> PlanningResult:
        """
        Generate tasks for specific stories
        
        Args:
            story_keys: List of story keys to generate tasks for
            epic_key: Parent epic key
            dry_run: If True, don't actually create tickets
            split_oversized_tasks: Automatically split oversized tasks
            max_task_cycle_days: Maximum cycle time allowed per task
            max_tasks_per_story: Maximum number of tasks per story
            custom_llm_client: Optional custom LLM client to use for generation
            additional_context: Optional additional context to guide task generation
            
        Returns:
            PlanningResult with generated tasks
        """
        if not self.planning_service:
            return PlanningResult(
                epic_key=epic_key,
                mode=OperationMode.PLANNING,
                success=False,
                errors=["Planning service not available - requires Confluence client"]
            )
        
        logger.info(f"Generating tasks for {len(story_keys)} stories")
        
        # Retrieve PRD/RFC content from epic
        prd_content = None
        rfc_content = None
        
        try:
            # Get epic details to retrieve PRD/RFC URLs
            epic_issue = self.jira_client.get_ticket(epic_key)
            if epic_issue:
                # Get PRD content using planning service method
                prd_content = self.planning_service._get_prd_content(epic_issue)
                # Get RFC content using planning service method
                rfc_content = self.planning_service._get_rfc_content(epic_issue)
                
                if prd_content:
                    logger.info(f"Retrieved PRD content: {prd_content.get('title', 'Unknown')}")
                if rfc_content:
                    logger.info(f"Retrieved RFC content: {rfc_content.get('title', 'Unknown')}")
        except Exception as e:
            logger.warning(f"Failed to retrieve PRD/RFC content for epic {epic_key}: {e}")
        
        context = PlanningContext(
            mode=OperationMode.PLANNING,
            epic_key=epic_key,
            max_task_cycle_days=max_task_cycle_days,
            max_tasks_per_story=max_tasks_per_story,
            split_oversized_tasks=split_oversized_tasks,
            generate_test_cases=True,
            create_missing_stories=False,
            create_missing_tasks=True,
            dry_run=dry_run,
            prd_content=prd_content,
            rfc_content=rfc_content,
            additional_context=additional_context
        )
        
        return self.planning_service.generate_tasks_for_stories(story_keys, context, custom_llm_client)
    
    def analyze_epic_gaps(self, epic_key: str) -> Dict[str, Any]:
        """
        Analyze an epic to identify gaps in story/task structure
        
        Args:
            epic_key: JIRA epic key to analyze
            
        Returns:
            Dictionary with gap analysis results
        """
        if not self.planning_service:
            return {
                "error": "Planning service not available - requires Confluence client"
            }
        
        logger.info(f"Analyzing epic gaps for {epic_key}")
        
        gap_analysis = self.planning_service.analysis_engine.analyze_epic_structure(epic_key)
        
        return {
            "epic_key": gap_analysis.epic_key,
            "existing_stories": gap_analysis.existing_stories,
            "missing_stories": gap_analysis.missing_stories,
            "incomplete_stories": gap_analysis.incomplete_stories,
            "orphaned_tasks": gap_analysis.orphaned_tasks,
            "prd_requirements": gap_analysis.prd_requirements,
            "rfc_requirements": gap_analysis.rfc_requirements,
            "needs_stories": gap_analysis.needs_stories,
            "needs_tasks": gap_analysis.needs_tasks,
            "is_complete": gap_analysis.is_complete,
            "summary": {
                "total_existing_stories": len(gap_analysis.existing_stories),
                "total_missing_stories": len(gap_analysis.missing_stories),
                "total_incomplete_stories": len(gap_analysis.incomplete_stories),
                "total_orphaned_tasks": len(gap_analysis.orphaned_tasks),
                "completion_percentage": self._calculate_completion_percentage(gap_analysis)
            }
        }
    
    def sync_stories_from_prd(
        self,
        epic_key: str,
        prd_url: str,
        dry_run: bool = True,
        existing_ticket_action: str = "skip"
    ) -> 'PlanningResult':
        """
        Sync story tickets from PRD table to JIRA
        
        Args:
            epic_key: JIRA epic key
            prd_url: PRD document URL
            dry_run: If True, don't actually create tickets
            existing_ticket_action: Action for existing tickets: "skip", "update", or "error"
            
        Returns:
            PlanningResult with synced stories
        """
        if not self.planning_service:
            return PlanningResult(
                epic_key=epic_key,
                mode=OperationMode.PLANNING,
                success=False,
                errors=["Planning service not available - requires Confluence client"]
            )
        
        logger.info(f"Syncing stories from PRD for epic {epic_key}")
        
        # Get PRD content
        prd_content = self.confluence_client.get_page_content(prd_url)
        if not prd_content:
            return PlanningResult(
                epic_key=epic_key,
                mode=OperationMode.PLANNING,
                success=False,
                errors=[f"Failed to retrieve PRD content from {prd_url}"]
            )
        
        # Verify PRD content has the expected structure for parsing
        has_body = 'body' in prd_content
        if not has_body:
            logger.warning(f"PRD content missing 'body' structure. Available keys: {list(prd_content.keys())}")
            # Try to use the content as-is if it's already in the right format
            # Some Confluence clients might return different structures
        
        # Sync stories from PRD table
        result = self.planning_service.sync_stories_from_prd_table(
            epic_key=epic_key,
            prd_content=prd_content,
            existing_ticket_action=existing_ticket_action,
            dry_run=dry_run
        )
        
        # Log result summary for debugging
        if result.epic_plan and result.epic_plan.stories:
            logger.info(f"PRD sync completed: {len(result.epic_plan.stories)} stories in epic plan")
        else:
            logger.warning(f"PRD sync completed but epic_plan has no stories. Success: {result.success}, Errors: {result.errors}")
        
        return result
    
    def _calculate_completion_percentage(self, gap_analysis) -> float:
        """Calculate epic completion percentage based on gap analysis"""
        total_expected = len(gap_analysis.existing_stories) + len(gap_analysis.missing_stories)
        if total_expected == 0:
            return 0.0
        
        complete_stories = len(gap_analysis.existing_stories) - len(gap_analysis.incomplete_stories)
        return (complete_stories / total_expected) * 100.0

    def _summarize_story_description(self, description: str, target_length: int = 300) -> str:
        """Use AI to intelligently summarize story description while preserving key context"""
        try:
            logger.debug(f"Summarizing story description: {len(description)} chars -> target {target_length} chars")
            
            summarization_prompt = Prompts.get_summarization_prompt_template().format(
                target_length=target_length,
                description=description
            )

            # Use the existing LLM client to generate summary
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            summary = self.llm_client.provider.generate_description(summarization_prompt, max_tokens=None)
            
            # Fallback to smart truncation if AI summarization fails
            if not summary or len(summary.strip()) == 0:
                logger.warning("AI summarization failed, falling back to smart truncation")
                return self._smart_truncate(description, target_length)
            
            # If AI summary is still too long, truncate it
            if len(summary) > target_length * 1.2:  # Allow 20% buffer
                logger.debug(f"AI summary too long ({len(summary)} chars), truncating to {target_length}")
                summary = self._smart_truncate(summary, target_length)
            
            logger.debug(f"Story description summarized: {len(description)} -> {len(summary)} chars")
            return summary.strip()
            
        except Exception as e:
            logger.warning(f"Failed to summarize story description: {e}, falling back to smart truncation")
            return self._smart_truncate(description, target_length)

    def _smart_truncate(self, text: str, max_length: int) -> str:
        """Intelligently truncate text at sentence boundaries when possible"""
        if len(text) <= max_length:
            return text
        
        # Try to truncate at sentence boundary
        truncated = text[:max_length]
        
        # Look for sentence endings within a reasonable range
        sentence_endings = ['. ', '! ', '? ', '\n\n']
        best_cut = -1
        
        # Look backwards from the truncation point for a good sentence ending
        for i in range(min(50, len(truncated))):  # Look back up to 50 chars
            pos = max_length - i
            if pos < max_length // 2:  # Don't cut too much (less than half)
                break
                
            for ending in sentence_endings:
                if truncated[pos:pos+len(ending)] == ending:
                    best_cut = pos + len(ending)
                    break
        
        # Return the best cut or fallback to simple truncation
        if best_cut > 0:
            return text[:best_cut].strip() + "..."
        else:
            return text[:max_length].strip() + "..."
    
    # =============================================================================
    # ENHANCED TEST GENERATION INTEGRATION METHODS
    # =============================================================================
    
    def generate_description_with_test_cases(self,
                                           ticket_key: str,
                                           include_test_cases: bool = True,
                                           test_coverage_level: str = "standard") -> Dict[str, Any]:
        """
        Generate ticket description with optional test cases
        
        Args:
            ticket_key: JIRA ticket key
            include_test_cases: Whether to generate test cases
            test_coverage_level: Level of test coverage (basic, standard, comprehensive)
            
        Returns:
            Enhanced generation result with test cases
        """
        logger.info(f"Generating description with test cases for {ticket_key}")
        
        try:
            # Generate regular description
            base_result = self.process_ticket(ticket_key)
            
            if not base_result.success:
                return base_result.dict()
            
            result = base_result.dict()
            
            # Add test cases if requested
            if include_test_cases:
                from .enhanced_test_generator import TestCoverageLevel
                
                # Map string to enum
                coverage_map = {
                    "basic": TestCoverageLevel.BASIC,
                    "standard": TestCoverageLevel.STANDARD,
                    "comprehensive": TestCoverageLevel.COMPREHENSIVE,
                    "minimal": TestCoverageLevel.MINIMAL
                }
                coverage = coverage_map.get(test_coverage_level.lower(), TestCoverageLevel.STANDARD)
                
                # Get ticket info
                ticket_info = self.jira_client.get_ticket(ticket_key)
                if ticket_info:
                    ticket_type = ticket_info.get('fields', {}).get('issuetype', {}).get('name', '').lower()
                    
                    if 'story' in ticket_type:
                        # Generate story test cases
                        test_cases = self._generate_story_tests_for_ticket(ticket_key, coverage)
                    elif 'task' in ticket_type or 'sub-task' in ticket_type:
                        # Generate task test cases with full context
                        test_cases = self._generate_task_tests_for_ticket(ticket_key, coverage)
                    else:
                        # Default to task-based testing
                        test_cases = self._generate_task_tests_for_ticket(ticket_key, coverage)
                    
                    result["test_cases"] = {
                        "generated": True,
                        "coverage_level": test_coverage_level,
                        "test_count": len(test_cases),
                        "test_cases": [self._serialize_test_case(tc) for tc in test_cases]
                    }
                else:
                    result["test_cases"] = {
                        "generated": False,
                        "error": "Could not fetch ticket information"
                    }
            
            return result
            
        except Exception as e:
            logger.error(f"Error generating description with test cases: {str(e)}")
            return {
                "success": False,
                "error": f"Generation with test cases failed: {str(e)}",
                "ticket_key": ticket_key
            }
    
    def bulk_generate_with_tests(self,
                               ticket_keys: List[str],
                               include_test_cases: bool = True,
                               test_coverage_level: str = "standard") -> Dict[str, Any]:
        """
        Bulk generate descriptions with test cases for multiple tickets
        
        Args:
            ticket_keys: List of JIRA ticket keys
            include_test_cases: Whether to generate test cases
            test_coverage_level: Level of test coverage
            
        Returns:
            Bulk generation results with test cases
        """
        logger.info(f"Bulk generating descriptions with test cases for {len(ticket_keys)} tickets")
        
        results = {
            "success": True,
            "total_tickets": len(ticket_keys),
            "processed_tickets": 0,
            "successful_generations": 0,
            "failed_generations": 0,
            "results": {},
            "errors": []
        }
        
        for ticket_key in ticket_keys:
            try:
                result = self.generate_description_with_test_cases(
                    ticket_key=ticket_key,
                    include_test_cases=include_test_cases,
                    test_coverage_level=test_coverage_level
                )
                
                results["results"][ticket_key] = result
                results["processed_tickets"] += 1
                
                if result.get("success", False):
                    results["successful_generations"] += 1
                else:
                    results["failed_generations"] += 1
                    results["errors"].append(f"{ticket_key}: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                results["failed_generations"] += 1
                results["errors"].append(f"{ticket_key}: {str(e)}")
                logger.error(f"Error in bulk generation for {ticket_key}: {str(e)}")
        
        results["success"] = results["failed_generations"] == 0
        return results
    
    def _generate_story_tests_for_ticket(self, ticket_key: str, coverage_level) -> List[Any]:
        """Generate test cases for a story ticket"""
        try:
            # Get story information from JIRA
            ticket_info = self.jira_client.get_ticket(ticket_key)
            if not ticket_info:
                return []
            
            # Convert to StoryPlan for test generation
            from .planning_models import StoryPlan, AcceptanceCriteria
            
            fields = ticket_info.get('fields', {})
            description = fields.get('description', '')
            
            # Handle ADF format
            if isinstance(description, dict):
                description = self._extract_text_from_adf(description)
            
            # Create basic story plan
            story_plan = StoryPlan(
                summary=fields.get('summary', ''),
                description=description,
                acceptance_criteria=self._extract_acceptance_criteria_from_description(description)
            )
            
            # Generate test cases
            return self.test_generator.generate_story_test_cases(
                story=story_plan,
                coverage_level=coverage_level,
                domain_context=self._detect_domain_from_text(f"{story_plan.summary} {story_plan.description}")
            )
            
        except Exception as e:
            logger.error(f"Error generating story tests for {ticket_key}: {str(e)}")
            return []
    
    def _generate_task_tests_for_ticket(self, ticket_key: str, coverage_level) -> List[Any]:
        """Generate test cases for a task ticket with full context"""
        try:
            # Use enhanced test generator with full story and document context
            return self.test_generator.generate_task_test_cases_with_story_context(
                task_key=ticket_key,
                coverage_level=coverage_level,
                technical_context=None,  # Auto-detected
                include_documents=True   # Include PRD/RFC context
            )
            
        except Exception as e:
            logger.error(f"Error generating task tests for {ticket_key}: {str(e)}")
            return []
    
    def _extract_acceptance_criteria_from_description(self, description: str) -> List[Any]:
        """Extract acceptance criteria from ticket description"""
        try:
            from .planning_models import AcceptanceCriteria
            import re
            
            criteria = []
            
            # Look for Gherkin format
            gherkin_patterns = [
                r'Given\s+(.+?)\s+When\s+(.+?)\s+Then\s+(.+?)(?=Given|$)',
                r'Scenario[:\s]+(.+?)(?=Scenario|$)'
            ]
            
            for pattern in gherkin_patterns:
                matches = re.findall(pattern, description, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    if len(match) == 3:  # Given, When, Then
                        criteria.append(AcceptanceCriteria(
                            scenario="User scenario",
                            given=match[0].strip(),
                            when=match[1].strip(),
                            then=match[2].strip()
                        ))
            
            # If no Gherkin format found, look for bullet points or numbered lists
            if not criteria:
                bullet_patterns = [
                    r'[-*•]\s*(.+?)(?=\n|$)',
                    r'\d+\.\s*(.+?)(?=\n|$)'
                ]
                
                for pattern in bullet_patterns:
                    matches = re.findall(pattern, description, re.MULTILINE)
                    for i, match in enumerate(matches[:3]):  # Limit to 3
                        criteria.append(AcceptanceCriteria(
                            scenario=f"Requirement {i+1}",
                            given="the system is ready",
                            when="user performs the action",
                            then=match.strip()
                        ))
            
            return criteria
            
        except Exception as e:
            logger.warning(f"Error extracting acceptance criteria: {str(e)}")
            return []
    
    def _detect_domain_from_text(self, text: str) -> Optional[str]:
        """Detect domain context from text"""
        try:
            text_lower = text.lower()
            
            domain_patterns = {
                "financial": ["payment", "money", "financial", "bank", "transaction", "billing"],
                "healthcare": ["health", "medical", "patient", "hipaa", "clinical"],
                "ecommerce": ["shop", "cart", "order", "product", "purchase", "inventory"],
                "security": ["auth", "security", "login", "permission", "encrypt", "access"],
                "api": ["api", "endpoint", "service", "integration"]
            }
            
            for domain, keywords in domain_patterns.items():
                if any(keyword in text_lower for keyword in keywords):
                    return domain
            
            return None
            
        except Exception:
            return None
    
    def _serialize_test_case(self, test_case) -> Dict[str, Any]:
        """Serialize test case object to dictionary"""
        try:
            return {
                "title": test_case.title,
                "type": test_case.type,
                "description": test_case.description,
                "expected_result": test_case.expected_result,
                "priority": getattr(test_case, 'priority', 'medium'),
                "steps": getattr(test_case, 'steps', [])
            }
        except Exception as e:
            logger.warning(f"Error serializing test case: {str(e)}")
            return {
                "title": str(test_case),
                "type": "unknown",
                "description": "Test case serialization failed",
                "expected_result": "Expected functionality works"
            }
    
    def _extract_text_from_adf(self, adf_content: Dict[str, Any]) -> str:
        """Extract plain text from Atlassian Document Format"""
        try:
            if not isinstance(adf_content, dict):
                return str(adf_content)
            
            text_parts = []
            
            def extract_text_recursive(node):
                if isinstance(node, dict):
                    if node.get('type') == 'text':
                        text_parts.append(node.get('text', ''))
                    elif 'content' in node:
                        for item in node['content']:
                            extract_text_recursive(item)
                elif isinstance(node, list):
                    for item in node:
                        extract_text_recursive(item)
                elif isinstance(node, str):
                    text_parts.append(node)
            
            extract_text_recursive(adf_content)
            return ' '.join(text_parts).strip()
            
        except Exception as e:
            logger.warning(f"Error extracting text from ADF: {str(e)}")
            return str(adf_content)[:500]
    
    def _extract_description_text(self, description_field) -> Optional[str]:
        """Extract description text handling both string and ADF formats"""
        if not description_field:
            return None
        
        # If it's already a string, return it
        if isinstance(description_field, str):
            return description_field
        
        # If it's an ADF dictionary, extract text from it
        if isinstance(description_field, dict):
            return self._extract_text_from_adf(description_field)
        
        # Fallback to string conversion
        return str(description_field)
