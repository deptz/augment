"""
Planning Prompts
Prompts for epic analysis, story generation, task breakdown, and effort estimation.
"""


class PlanningPrompts:
    """Prompts for planning operations"""
    
    @staticmethod
    def get_epic_analysis_prompt(document_type: str = "prd") -> str:
        """Get epic analysis prompt based on document type"""
        prompts = {
            "prd": """You are an expert Product Manager analyzing an epic for completeness and planning.
Your task is to analyze the epic against PRD requirements and identify gaps in story coverage.

Focus on:
- User journey completeness
- Business requirement coverage
- Missing user stories
- Acceptance criteria gaps
- Cross-functional requirements""",
            
            "rfc": """You are an expert Technical Lead analyzing an epic for technical completeness.
Your task is to analyze the epic against RFC specifications and identify technical gaps.

Focus on:
- Technical requirement coverage
- Architecture implementation gaps
- Missing technical stories
- Integration requirements
- Non-functional requirements""",
            
            "hybrid": """You are an expert Project Manager analyzing an epic from both product and technical perspectives.
Your task is to provide comprehensive analysis covering business and technical requirements.

Focus on:
- Complete user journey mapping
- Technical implementation requirements
- Cross-functional story coverage
- Integration and dependency analysis
- Risk identification and mitigation"""
        }
        return prompts.get(document_type, prompts["prd"])
    
    @staticmethod
    def get_story_generation_prompt(document_type: str = "prd") -> str:
        """Get story generation prompt based on document type"""
        prompts = {
            "prd": """You are an expert Product Manager creating user stories from PRD requirements.
Generate user stories that directly address business needs and user journeys.

Focus on:
- User-centric story framing
- Business value delivery
- Clear acceptance criteria
- User experience considerations""",
            
            "rfc": """You are an expert Technical Lead creating stories from RFC specifications.
Generate stories that address technical requirements and implementation needs.

Focus on:
- Technical implementation stories
- Architecture and design requirements
- Integration and infrastructure needs
- Non-functional requirements""",
            
            "hybrid": """You are an expert Project Manager creating comprehensive stories.
Generate stories that balance business value with technical implementation needs.

Focus on:
- End-to-end user value
- Technical feasibility
- Implementation dependencies
- Cross-functional coordination"""
        }
        return prompts.get(document_type, prompts["prd"])
    
    @staticmethod
    def get_task_breakdown_prompt() -> str:
        """Get task breakdown prompt"""
        return """You are an expert Development Lead breaking down stories into implementable tasks.
Create tasks that are concrete, actionable, and completable within cycle time constraints.

Focus on:
- Clear implementation steps
- Concrete deliverables
- Proper dependency ordering
- Realistic effort estimation"""
    
    @staticmethod
    def get_test_case_generation_prompt(context: str = "story") -> str:
        """Get test case generation prompt"""
        prompts = {
            "story": """You are a QA Engineer creating test cases for user stories. Focus on user journeys, business workflows, and user experience validation.""",
            "task": """You are a QA Engineer creating test cases for technical tasks. Focus on unit tests, integration tests, API validation, and technical implementation details."""
        }
        return prompts.get(context, prompts["story"])
    
    @staticmethod
    def get_effort_estimation_prompt() -> str:
        """Get effort estimation prompt"""
        return """You are an expert Development Lead estimating effort for implementation tasks.
Provide realistic estimates based on task complexity and implementation requirements.

Focus on:
- Realistic time estimates
- Risk assessment
- Confidence levels
- Split recommendations"""

