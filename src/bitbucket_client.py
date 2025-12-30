import requests
from typing import Dict, List, Optional, Any
import logging
from urllib.parse import urljoin
from datetime import datetime

logger = logging.getLogger(__name__)


class BitbucketClient:
    """Bitbucket API client for fetching pull requests and commits via Jira Development Panel API"""
    
    def __init__(self, workspaces: List[str] = None, workspace: str = None, email: str = None, api_token: str = None, jira_server_url: Optional[str] = None, jira_credentials: Optional[Dict[str, str]] = None):
        """
        Initialize Bitbucket client with optional Jira credentials for Development Panel API.
        
        Supports multiple workspaces. If workspaces is provided, it will search across all workspaces.
        For backward compatibility, workspace (singular) can still be used.
        
        Args:
            workspaces: List of workspace names to search across
            workspace: Single workspace name (backward compatibility, ignored if workspaces is provided)
            email: Atlassian account email
            api_token: Atlassian API token
            jira_server_url: Optional Jira server URL for Development Panel API
            jira_credentials: Optional Jira credentials dict with 'username' and 'api_token'
        """
        # Handle workspace/workspaces parameter
        if workspaces:
            self.workspaces = workspaces if isinstance(workspaces, list) else [workspaces]
        elif workspace:
            # Backward compatibility: single workspace
            self.workspaces = [workspace]
        else:
            raise ValueError("Either 'workspaces' or 'workspace' must be provided")
        
        # Remove empty strings and ensure all are strings
        self.workspaces = [w.strip() for w in self.workspaces if w and isinstance(w, str) and w.strip()]
        if not self.workspaces:
            raise ValueError("At least one valid workspace must be provided")
        
        # Maintain backward compatibility: self.workspace points to first workspace
        self.workspace = self.workspaces[0]
        
        if not email or not api_token:
            raise ValueError("email and api_token are required")
        
        self.email = email
        self.api_token = api_token
        self.jira_server_url = jira_server_url
        self.jira_credentials = jira_credentials or {}
        self.base_url = "https://api.bitbucket.org/2.0"
        
        # Setup session for Bitbucket API
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def find_pull_requests_for_ticket(self, ticket_key: str, repo_slug: Optional[str] = None, include_diff: bool = False) -> List[Dict[str, Any]]:
        """Find pull requests related to a Jira ticket using Development Panel API"""
        logger.debug(f"find_pull_requests_for_ticket called: ticket_key={ticket_key}, include_diff={include_diff}")
        
        if not self.jira_server_url:
            logger.warning("Jira server URL not provided, falling back to repository search")
            return self._find_pull_requests_via_search(ticket_key, repo_slug, include_diff)
        
        try:
            logger.debug(f"Using Jira Development Panel API for ticket {ticket_key}")
            # Get issue ID first
            issue_id = self._get_issue_id(ticket_key)
            if not issue_id:
                logger.warning(f"Could not find issue ID for {ticket_key}")
                return []
            
            logger.debug(f"Found issue ID: {issue_id}")
            
            # Create Jira session for Development Panel API
            jira_session = self._create_jira_session()
            if not jira_session:
                logger.warning("Could not create Jira session, falling back to repository search")
                return self._find_pull_requests_via_search(ticket_key, repo_slug, include_diff)
            
            # Use Jira Development Panel API
            url = f"{self.jira_server_url}/rest/dev-status/latest/issue/detail"
            params = {
                'issueId': issue_id,
                'applicationType': 'bitbucket',
                'dataType': 'pullrequest'
            }
            
            response = jira_session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            pull_requests = []
            
            # Extract pull requests from response
            detail = data.get('detail', [])
            if detail:
                prs = detail[0].get('pullRequests', [])
                for pr in prs:
                    pr_data = {
                        'id': pr.get('id'),
                        'title': pr.get('name', ''),
                        'description': '',  # Description not in dev panel response
                        'state': pr.get('state', 'OPEN'),  # Default to OPEN if not specified
                        'url': pr.get('url', ''),
                        'source_branch': pr.get('source', {}).get('branch', ''),
                        'destination_branch': pr.get('destination', {}).get('branch', ''),
                        'author': pr.get('author', {}).get('name', ''),
                        'created_on': pr.get('createdDate'),
                        'updated_on': pr.get('updatedDate')
                    }
                    
                    # Add diff analysis if requested
                    if include_diff and pr.get('url'):
                        logger.debug(f"Analyzing PR diff for {pr.get('url')}")
                        code_changes = self._analyze_pr_diff_from_url(pr.get('url'))
                        pr_data['code_changes'] = code_changes
                        if code_changes:
                            logger.debug(f"Successfully analyzed PR diff: {len(code_changes.get('files_changed', []))} files")
                        else:
                            logger.debug(f"Failed to analyze PR diff for {pr.get('url')}")
                    else:
                        logger.debug(f"Skipping diff analysis: include_diff={include_diff}, url={pr.get('url')}")
                    
                    pull_requests.append(pr_data)
            
            logger.info(f"Found {len(pull_requests)} pull requests for {ticket_key} via Development Panel API")
            return pull_requests
            
        except Exception as e:
            logger.error(f"Failed to get pull requests via Development Panel API for {ticket_key}: {e}")
            logger.info("Falling back to repository search")
            return self._find_pull_requests_via_search(ticket_key, repo_slug, include_diff)
    
    def find_commits_for_ticket(self, ticket_key: str, repo_slug: Optional[str] = None, include_diff: bool = False) -> List[Dict[str, Any]]:
        """Find commits related to a Jira ticket using Development Panel API"""
        if not self.jira_server_url:
            logger.warning("Jira server URL not provided, falling back to repository search")
            return self._find_commits_via_search(ticket_key, repo_slug, include_diff)
        
        try:
            # Get issue ID first
            issue_id = self._get_issue_id(ticket_key)
            if not issue_id:
                logger.warning(f"Could not find issue ID for {ticket_key}")
                return []
            
            # Create Jira session for Development Panel API
            jira_session = self._create_jira_session()
            if not jira_session:
                logger.warning("Could not create Jira session, falling back to repository search")
                return self._find_commits_via_search(ticket_key, repo_slug, include_diff)
            
            # Use Jira Development Panel API
            url = f"{self.jira_server_url}/rest/dev-status/latest/issue/detail"
            params = {
                'issueId': issue_id,
                'applicationType': 'bitbucket',
                'dataType': 'repository'
            }
            
            response = jira_session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            commits = []
            
            # Extract commits from response
            detail = data.get('detail', [])
            if detail:
                repositories = detail[0].get('repositories', [])
                if repositories:
                    commit_list = repositories[0].get('commits', [])
                    for commit in commit_list:
                        commit_data = {
                            'id': commit.get('id'),
                            'hash': commit.get('id'),
                            'message': commit.get('message', ''),
                            'author': commit.get('author', {}).get('name', ''),
                            'date': commit.get('authorTimestamp'),
                            'url': commit.get('url', '')
                        }
                        
                        # Add diff analysis if requested - this will get the actual affected files
                        if include_diff and commit.get('url'):
                            commit_data['code_changes'] = self._analyze_commit_diff_from_url(commit.get('url'))
                        
                        commits.append(commit_data)
            
            logger.info(f"Found {len(commits)} commits for {ticket_key} via Development Panel API")
            return commits
            
        except Exception as e:
            logger.error(f"Failed to get commits via Development Panel API for {ticket_key}: {e}")
            logger.info("Falling back to repository search")
            return self._find_commits_via_search(ticket_key, repo_slug, include_diff)
    
    def _get_issue_id(self, ticket_key: str) -> Optional[str]:
        """Get Jira issue ID from ticket key using Jira authentication"""
        try:
            # Create a session with Jira authentication
            jira_session = self._create_jira_session()
            if not jira_session:
                return None
            
            url = f"{self.jira_server_url}/rest/api/3/issue/{ticket_key}"
            response = jira_session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            return data.get('id')
            
        except Exception as e:
            logger.error(f"Failed to get issue ID for {ticket_key}: {e}")
            return None
    
    def _create_jira_session(self) -> Optional[requests.Session]:
        """Create a session with Jira authentication"""
        try:
            import base64
            
            # Get credentials from instance or environment
            jira_username = self.jira_credentials.get('username')
            jira_api_token = self.jira_credentials.get('api_token')
            
            if not jira_username or not jira_api_token:
                # Fallback to environment variables
                import os
                jira_username = os.getenv('JIRA_USERNAME')
                jira_api_token = os.getenv('JIRA_API_TOKEN')
            
            if not jira_username or not jira_api_token:
                logger.debug("Jira credentials not available for Development Panel API")
                return None
            
            jira_session = requests.Session()
            credentials = base64.b64encode(f"{jira_username}:{jira_api_token}".encode()).decode()
            jira_session.headers.update({
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            })
            
            return jira_session
            
        except Exception as e:
            logger.error(f"Failed to create Jira session: {e}")
            return None
    
    def _find_pull_requests_via_search(self, ticket_key: str, repo_slug: Optional[str] = None, include_diff: bool = False) -> List[Dict[str, Any]]:
        """Fallback method: Find pull requests by searching repositories across all workspaces"""
        pull_requests = []
        
        if repo_slug:
            # If repo_slug is provided, search in all workspaces
            repos = [(workspace, repo_slug) for workspace in self.workspaces]
        else:
            repos = self._get_repositories()
        
        for repo_info in repos:
            try:
                if isinstance(repo_info, tuple):
                    workspace, repo = repo_info
                else:
                    # Backward compatibility: if it's just a string, use first workspace
                    workspace = self.workspace
                    repo = repo_info
                
                prs = self._search_pull_requests_in_repo(workspace, repo, ticket_key, include_diff)
                pull_requests.extend(prs)
            except Exception as e:
                logger.error(f"Failed to search PRs in {repo_info}: {e}")
        
        return pull_requests
    
    def _find_commits_via_search(self, ticket_key: str, repo_slug: Optional[str] = None, include_diff: bool = False) -> List[Dict[str, Any]]:
        """Fallback method: Find commits by searching repositories across all workspaces"""
        commits = []
        
        if repo_slug:
            # If repo_slug is provided, search in all workspaces
            repos = [(workspace, repo_slug) for workspace in self.workspaces]
        else:
            repos = self._get_repositories()
        
        for repo_info in repos:
            try:
                if isinstance(repo_info, tuple):
                    workspace, repo = repo_info
                else:
                    # Backward compatibility: if it's just a string, use first workspace
                    workspace = self.workspace
                    repo = repo_info
                
                repo_commits = self._search_commits_in_repo(workspace, repo, ticket_key, include_diff)
                commits.extend(repo_commits)
            except Exception as e:
                logger.error(f"Failed to search commits in {repo_info}: {e}")
        
        return commits
    
    def _get_repositories(self) -> List[tuple]:
        """
        Get list of repositories across all configured workspaces.
        
        Returns:
            List of tuples (workspace, repo_slug) for each repository found
        """
        all_repos = []
        
        for workspace in self.workspaces:
            url = f"{self.base_url}/repositories/{workspace}"
            
            try:
                logger.debug(f"Fetching repositories from workspace: {workspace}")
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                # Use 'full_name' or 'slug' instead of 'name' for URL-safe repository identifiers
                workspace_repos = []
                for repo in data.get('values', []):
                    # Use the slug or the second part of full_name (workspace/repo-slug)
                    repo_slug = repo.get('slug') or repo.get('full_name', '').split('/')[-1]
                    if repo_slug:
                        workspace_repos.append((workspace, repo_slug))
                        logger.debug(f"Found repository: {repo.get('name')} (workspace: {workspace}, slug: {repo_slug})")
                
                all_repos.extend(workspace_repos)
                logger.info(f"Found {len(workspace_repos)} repositories in workspace '{workspace}'")
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    logger.warning(f"Workspace '{workspace}' not found or not accessible (404)")
                elif e.response.status_code == 403:
                    logger.warning(f"Access denied to workspace '{workspace}' (403)")
                else:
                    logger.error(f"Failed to get repositories from workspace '{workspace}': {e}")
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to get repositories from workspace '{workspace}': {e}")
        
        logger.info(f"Found {len(all_repos)} total repositories across {len(self.workspaces)} workspace(s)")
        return all_repos
    
    def _search_pull_requests_in_repo(self, workspace: str, repo_slug: str, ticket_key: str, include_diff: bool = False) -> List[Dict[str, Any]]:
        """Search for pull requests in a specific repository within a workspace"""
        url = f"{self.base_url}/repositories/{workspace}/{repo_slug}/pullrequests"
        
        # Search in title, description, and branch names
        params = {
            'q': f'(title ~ "{ticket_key}" OR description ~ "{ticket_key}" OR source.branch.name ~ "{ticket_key}")',
            'state': 'MERGED',  # Focus on merged PRs for completed work
            'sort': '-created_on'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            pull_requests = []
            
            for pr in data.get('values', []):
                pr_data = {
                    'id': pr['id'],
                    'title': pr['title'],
                    'description': pr.get('description', ''),
                    'source_branch': pr['source']['branch']['name'],
                    'destination_branch': pr['destination']['branch']['name'],
                    'state': pr['state'],
                    'created_on': pr['created_on'],
                    'repository': repo_slug,
                    'url': pr['links']['html']['href']
                }
                
                # Add diff content if requested
                if include_diff:
                    diff_content = self._get_pull_request_diff(workspace, repo_slug, pr['id'])
                    if diff_content:
                        pr_data['diff'] = diff_content
                        pr_data['code_changes'] = self._analyze_diff_content(diff_content)
                
                pull_requests.append(pr_data)
            
            return pull_requests
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to search PRs in {workspace}/{repo_slug}: {e}")
            return []
    
    def _search_commits_in_repo(self, workspace: str, repo_slug: str, ticket_key: str, include_diff: bool = False) -> List[Dict[str, Any]]:
        """Search for commits in a specific repository within a workspace"""
        url = f"{self.base_url}/repositories/{workspace}/{repo_slug}/commits"
        
        # Search in commit messages
        params = {
            'q': f'message ~ "{ticket_key}"',
            'sort': '-date'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            commits = []
            
            for commit in data.get('values', []):
                commit_data = {
                    'hash': commit['hash'],
                    'message': commit['message'],
                    'author': commit['author']['raw'],
                    'date': commit['date'],
                    'repository': repo_slug,
                    'url': commit['links']['html']['href']
                }
                
                # Add diff content if requested
                if include_diff:
                    diff_content = self._get_commit_diff(workspace, repo_slug, commit['hash'])
                    if diff_content:
                        commit_data['diff'] = diff_content
                        commit_data['code_changes'] = self._analyze_diff_content(diff_content)
                
                commits.append(commit_data)
            
            return commits
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to search commits in {workspace}/{repo_slug}: {e}")
            return []
    
    def _get_pull_request_diff(self, workspace: str, repo_slug: str, pr_id: str) -> Optional[str]:
        """Get the diff content for a pull request in a specific workspace"""
        url = f"{self.base_url}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/diff"
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Return the raw diff content
            return response.text
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to get PR diff {workspace}/{repo_slug}/{pr_id}: {e}")
            return None
    
    def _get_commit_diff(self, workspace: str, repo_slug: str, commit_hash: str) -> Optional[str]:
        """Get the diff content for a commit in a specific workspace"""
        url = f"{self.base_url}/repositories/{workspace}/{repo_slug}/diff/{commit_hash}"
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Return the raw diff content
            return response.text
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to get commit diff {workspace}/{repo_slug}/{commit_hash}: {e}")
            return None
    
    def _analyze_pr_diff_from_url(self, pr_url: str) -> Optional[Dict[str, Any]]:
        """Analyze PR diff from Bitbucket URL"""
        try:
            logger.debug(f"Attempting to analyze PR diff from URL: {pr_url}")
            
            # Convert Bitbucket web URL to API URL for diff
            # Example: https://bitbucket.org/workspace/repo/pull-requests/123
            # Or: https://bitbucket.org/{uuid1}/{uuid2}/pull-requests/123
            if 'bitbucket.org' in pr_url and '/pull-requests/' in pr_url:
                parts = pr_url.split('/')
                workspace_or_uuid = parts[3]
                repo_or_uuid = parts[4]
                pr_id = parts[6].split('?')[0]  # Remove query params
                
                # Use workspace name instead of UUID for better compatibility
                if workspace_or_uuid.startswith('{') and workspace_or_uuid.endswith('}'):
                    logger.debug(f"Detected UUID format workspace: {workspace_or_uuid}, using configured workspace: {self.workspace}")
                    workspace_or_uuid = self.workspace
                
                # Repository UUID is fine to use directly
                if repo_or_uuid.startswith('{') and repo_or_uuid.endswith('}'):
                    logger.debug(f"Repository is UUID format: {repo_or_uuid}, proceeding with API call")
                
                # Construct URL without any additional encoding
                diff_url = f"{self.base_url}/repositories/{workspace_or_uuid}/{repo_or_uuid}/pullrequests/{pr_id}/diff"
                logger.debug(f"Fetching diff from: {diff_url}")
                logger.debug(f"Session auth: {self.session.auth}")
                logger.debug(f"Session headers: {self.session.headers}")
                
                response = self.session.get(diff_url, timeout=30)
                logger.debug(f"Response status: {response.status_code}")
                logger.debug(f"Response headers: {dict(response.headers)}")
                
                # If we get 404 and we're using UUIDs, try with configured workspace
                if response.status_code == 404 and repo_or_uuid.startswith('{'):
                    logger.debug(f"404 error with UUID repo, this might be expected - repo UUID {repo_or_uuid} not accessible")
                    return None
                
                response.raise_for_status()
                
                logger.debug(f"Successfully fetched diff, analyzing content ({len(response.text)} chars)")
                result = self._analyze_diff_content(response.text)
                
                if result:
                    logger.debug(f"Diff analysis successful: {result}")
                else:
                    logger.debug("Diff analysis returned no results")
                
                return result
            else:
                logger.debug(f"URL format not recognized: {pr_url}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                logger.warning(f"Authentication failed for Bitbucket API. Please check your BITBUCKET_API_TOKEN and permissions.")
                logger.debug(f"Failed URL: {pr_url}")
            elif e.response.status_code == 404:
                logger.debug(f"PR not found or not accessible: {pr_url}")
            else:
                logger.warning(f"HTTP error analyzing PR diff from URL {pr_url}: {e}")
        except Exception as e:
            logger.warning(f"Failed to analyze PR diff from URL {pr_url}: {e}")
        
        return None
    
    def _analyze_commit_diff_from_url(self, commit_url: str) -> Optional[Dict[str, Any]]:
        """Analyze commit diff from Bitbucket URL"""
        try:
            # Convert Bitbucket web URL to API URL for diff
            # Example: https://bitbucket.org/workspace/repo/commits/abc123
            if 'bitbucket.org' in commit_url and '/commits/' in commit_url:
                parts = commit_url.split('/')
                workspace = parts[3]
                repo_slug = parts[4]
                commit_hash = parts[6].split('?')[0]  # Remove query params
                
                diff_url = f"{self.base_url}/repositories/{workspace}/{repo_slug}/diff/{commit_hash}"
                response = self.session.get(diff_url, timeout=30)
                response.raise_for_status()
                
                return self._analyze_diff_content(response.text)
        except Exception as e:
            logger.debug(f"Failed to analyze commit diff from URL {commit_url}: {e}")
        
        return None

    def _analyze_diff_content(self, diff_content: str) -> Dict[str, Any]:
        """Analyze diff content to extract meaningful code changes"""
        if not diff_content:
            return {}
        
        analysis = {
            'files_changed': [],
            'additions': 0,
            'deletions': 0,
            'file_types': set(),
            'change_summary': []
        }
        
        current_file = None
        file_additions = 0
        file_deletions = 0
        
        for line in diff_content.split('\n'):
            # File header
            if line.startswith('diff --git'):
                if current_file:
                    # Save previous file stats
                    analysis['files_changed'].append({
                        'file': current_file,
                        'additions': file_additions,
                        'deletions': file_deletions
                    })
                
                # Extract file path (a/path/to/file.ext b/path/to/file.ext)
                parts = line.split()
                if len(parts) >= 4:
                    file_path = parts[2][2:]  # Remove 'a/' prefix
                    current_file = file_path
                    file_additions = 0
                    file_deletions = 0
                    
                    # Track file type
                    if '.' in file_path:
                        ext = file_path.split('.')[-1].lower()
                        analysis['file_types'].add(ext)
            
            # Count additions and deletions
            elif line.startswith('+') and not line.startswith('+++'):
                analysis['additions'] += 1
                file_additions += 1
            elif line.startswith('-') and not line.startswith('---'):
                analysis['deletions'] += 1
                file_deletions += 1
        
        # Save last file
        if current_file:
            analysis['files_changed'].append({
                'file': current_file,
                'additions': file_additions,
                'deletions': file_deletions
            })
        
        # Convert set to list for JSON serialization, ensuring all items are strings
        analysis['file_types'] = [str(ft) for ft in analysis['file_types']]
        
        # Generate summary
        total_files = len(analysis['files_changed'])
        if total_files > 0:
            analysis['change_summary'] = [
                f"Modified {total_files} file{'s' if total_files > 1 else ''}",
                f"+{analysis['additions']} -{analysis['deletions']} lines"
            ]
            
            # Add file type summary
            if analysis['file_types']:
                file_types_str = ', '.join(str(ft) for ft in analysis['file_types'][:5])  # Limit to 5 types
                if len(analysis['file_types']) > 5:
                    file_types_str += f" and {len(analysis['file_types']) - 5} more"
                analysis['change_summary'].append(f"File types: {file_types_str}")
        
        return analysis
    
    def test_connection(self) -> bool:
        """Test the Bitbucket connection and optionally verify workspace access"""
        try:
            url = f"{self.base_url}/user"
            logger.info(f"Testing Bitbucket connection to: {url}")
            logger.debug(f"Using email: {self.email}")
            logger.debug(f"API token starts with: {self.api_token[:10]}...")
            
            response = self.session.get(url, timeout=10)
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {dict(response.headers)}")
            
            if response.status_code == 401:
                logger.error("401 Unauthorized - Check your Bitbucket email and API token")
                logger.error("Make sure the API token has 'Account' and 'Repositories' read permissions")
                return False
                
            response.raise_for_status()
            logger.info("Bitbucket API connection successful")
            
            # Test access to each configured workspace
            accessible_workspaces = []
            for workspace in self.workspaces:
                try:
                    workspace_url = f"{self.base_url}/workspaces/{workspace}"
                    ws_response = self.session.get(workspace_url, timeout=10)
                    if ws_response.status_code == 200:
                        accessible_workspaces.append(workspace)
                        logger.info(f"✓ Workspace '{workspace}' is accessible")
                    elif ws_response.status_code == 404:
                        logger.warning(f"⚠ Workspace '{workspace}' not found (404)")
                    elif ws_response.status_code == 403:
                        logger.warning(f"⚠ Access denied to workspace '{workspace}' (403)")
                    else:
                        logger.warning(f"⚠ Workspace '{workspace}' returned status {ws_response.status_code}")
                except Exception as e:
                    logger.warning(f"⚠ Failed to test workspace '{workspace}': {e}")
            
            if accessible_workspaces:
                logger.info(f"Successfully connected. {len(accessible_workspaces)}/{len(self.workspaces)} workspace(s) accessible")
                return True
            else:
                logger.warning("Connection successful but no workspaces are accessible")
                return False
                
        except Exception as e:
            logger.error(f"Bitbucket connection test failed: {e}")
            return False
