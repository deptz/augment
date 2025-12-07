#!/usr/bin/env python3
"""
Simple client example for the Augment API

This script demonstrates how to interact with the API programmatically.
"""

import requests
import time
import json
import argparse
from typing import Optional


class JiraDescriptionAPIClient:
    """Simple client for the Augment API"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
    
    def health_check(self) -> dict:
        """Check API health status"""
        response = self.session.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()
    
    def process_single_ticket(self, ticket_key: str, update_jira: bool = False) -> dict:
        """Process a single ticket"""
        payload = {
            "ticket_key": ticket_key,
            "update_jira": update_jira
        }
        response = self.session.post(f"{self.base_url}/generate/single", json=payload)
        response.raise_for_status()
        return response.json()
    
    def start_batch_job(self, jql: str, max_results: int = 100, update_jira: bool = False) -> str:
        """Start a batch processing job and return job ID"""
        payload = {
            "jql": jql,
            "max_results": max_results,
            "update_jira": update_jira
        }
        response = self.session.post(f"{self.base_url}/generate/batch", json=payload)
        response.raise_for_status()
        return response.json()["job_id"]
    
    def get_job_status(self, job_id: str) -> dict:
        """Get status of a batch job"""
        response = self.session.get(f"{self.base_url}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()
    
    def wait_for_job_completion(self, job_id: str, poll_interval: int = 5, timeout: int = 3600) -> dict:
        """Wait for a batch job to complete"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status_data = self.get_job_status(job_id)
            status = status_data["status"]
            
            print(f"Job {job_id}: {status}")
            if "progress" in status_data:
                progress = status_data["progress"]
                print(f"  Progress: {progress.get('processed', 0)}/{progress.get('total', 0)}")
            
            if status == "completed":
                return status_data
            elif status == "failed":
                raise Exception(f"Job failed: {status_data.get('error', 'Unknown error')}")
            
            time.sleep(poll_interval)
        
        raise Exception(f"Job timed out after {timeout} seconds")
    
    def process_batch_and_download(self, jql: str, max_results: int = 100, 
                                 update_jira: bool = False, poll_interval: int = 5) -> dict:
        """Complete workflow: start batch job, wait for completion"""
        print(f"Starting batch job...")
        print(f"JQL: {jql}")
        print(f"Max results: {max_results}")
        print(f"Update JIRA: {update_jira}")
        
        # Start job
        job_id = self.start_batch_job(jql, max_results, update_jira)
        print(f"Job started: {job_id}")
        
        # Wait for completion
        print("Waiting for job completion...")
        result = self.wait_for_job_completion(job_id, poll_interval)
        
        return result


def main():
    parser = argparse.ArgumentParser(description="Augment API Client")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Health check command
    health_parser = subparsers.add_parser("health", help="Check API health")
    
    # Single ticket command
    single_parser = subparsers.add_parser("single", help="Process single ticket")
    single_parser.add_argument("ticket_key", help="JIRA ticket key")
    single_parser.add_argument("--update", action="store_true", help="Update JIRA ticket")
    
    # Batch command
    batch_parser = subparsers.add_parser("batch", help="Process multiple tickets")
    batch_parser.add_argument("jql", help="JQL query")
    batch_parser.add_argument("--max-results", type=int, default=100, help="Maximum results")
    batch_parser.add_argument("--update", action="store_true", help="Update JIRA tickets")
    batch_parser.add_argument("--poll-interval", type=int, default=5, help="Poll interval in seconds")
    
    # Job status command
    status_parser = subparsers.add_parser("status", help="Check job status")
    status_parser.add_argument("job_id", help="Job ID")
    
    # API URL option
    parser.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Create client
    client = JiraDescriptionAPIClient(args.api_url)
    
    try:
        if args.command == "health":
            health = client.health_check()
            print("API Health Status:")
            print(json.dumps(health, indent=2))
        
        elif args.command == "single":
            result = client.process_single_ticket(args.ticket_key, args.update)
            print("Single Ticket Result:")
            print(json.dumps(result, indent=2))
        
        elif args.command == "batch":
            result = client.process_batch_and_download(
                jql=args.jql,
                max_results=args.max_results,
                update_jira=args.update,
                poll_interval=args.poll_interval
            )
            
            print("\nBatch Processing Summary:")
            batch_result = result["result"]
            print(f"Total tickets: {batch_result['total_tickets']}")
            print(f"Processed: {batch_result['processed_tickets']}")
            print(f"Successful: {batch_result['successful']}")
            print(f"Failed: {batch_result['failed']}")
            print(f"Skipped: {batch_result['skipped']}")
        
        elif args.command == "status":
            status = client.get_job_status(args.job_id)
            print("Job Status:")
            print(json.dumps(status, indent=2))
    
    except requests.exceptions.RequestException as e:
        print(f"API Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"Error details: {error_detail}")
            except:
                print(f"Response: {e.response.text}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
