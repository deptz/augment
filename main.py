#!/usr/bin/env python3
"""
Augment - JIRA Automation Platform

A tool to automatically generate and backfill structured descriptions for historical Jira tickets
using PRD/RFC documents, pull requests, commits, and LLM processing.
"""

import click
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import Config
from src.jira_client import JiraClient
from src.bitbucket_client import BitbucketClient
from src.confluence_client import ConfluenceClient
from src.llm_client import LLMClient
from src.generator import DescriptionGenerator
from src.models import ProcessingResult


def setup_logging(verbose: bool = False):
    """Setup logging configuration"""
    level = logging.DEBUG if verbose else logging.INFO
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(level)
    logger.addHandler(console_handler)
    
    # Reduce noise from external libraries
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def create_clients(config: Config):
    """Create API clients from configuration"""
    # Jira client (required)
    jira_client = JiraClient(
        server_url=config.jira['server_url'],
        username=config.jira['username'],
        api_token=config.jira['api_token'],
        prd_custom_field=config.jira['prd_custom_field'],
        rfc_custom_field=config.jira.get('rfc_custom_field'),
        mandays_custom_field=config.jira.get('mandays_custom_field')
    )
    
    # Bitbucket client (optional) - supports multiple workspaces
    bitbucket_client = None
    workspaces = config.get_bitbucket_workspaces()
    bitbucket_email = config.bitbucket.get('email', '')
    bitbucket_api_token = config.bitbucket.get('api_token', '')
    
    if workspaces and bitbucket_email and bitbucket_api_token:
        # Pass Jira credentials for Development Panel API
        jira_credentials = {
            'username': config.jira['username'],
            'api_token': config.jira['api_token']
        }
        bitbucket_client = BitbucketClient(
            workspaces=workspaces,
            email=bitbucket_email,
            api_token=bitbucket_api_token,
            jira_server_url=config.jira['server_url'],
            jira_credentials=jira_credentials
        )
    
    # Confluence client (optional)
    confluence_client = None
    if all(config.confluence.get(key) for key in ['server_url', 'username', 'api_token']):
        confluence_client = ConfluenceClient(
            server_url=config.confluence['server_url'],
            username=config.confluence['username'],
            api_token=config.confluence['api_token']
        )
    
    # LLM client (required)
    llm_config = config.get_llm_config()
    llm_client = LLMClient(llm_config)
    
    return jira_client, bitbucket_client, confluence_client, llm_client


def test_connections(jira_client, bitbucket_client, confluence_client, llm_client):
    """Test all API connections"""
    logger = logging.getLogger(__name__)
    
    logger.info("Testing API connections...")
    
    # Test Jira
    if not jira_client.test_connection():
        logger.error("❌ Jira connection failed")
        return False
    logger.info("✅ Jira connection successful")
    
    # Test Bitbucket (optional)
    if bitbucket_client:
        if not bitbucket_client.test_connection():
            logger.warning("⚠️  Bitbucket connection failed - will skip PR/commit data")
            bitbucket_client = None
        else:
            logger.info("✅ Bitbucket connection successful")
    else:
        logger.info("ℹ️  Bitbucket not configured - will skip PR/commit data")
    
    # Test Confluence (optional)
    if confluence_client:
        if not confluence_client.test_connection():
            logger.warning("⚠️  Confluence connection failed - will skip PRD data")
            confluence_client = None
        else:
            logger.info("✅ Confluence connection successful")
    else:
        logger.info("ℹ️  Confluence not configured - will skip PRD data")
    
    # Test LLM
    if not llm_client.test_connection():
        logger.error("❌ LLM connection failed")
        return False
    logger.info("✅ LLM connection successful")
    
    return True


def print_results_summary(results):
    """Print a summary of processing results"""
    logger = logging.getLogger(__name__)
    
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success and not r.skipped_reason]
    skipped = [r for r in results if r.skipped_reason]
    
    logger.info("\n" + "="*60)
    logger.info("PROCESSING SUMMARY")
    logger.info("="*60)
    logger.info(f"Total tickets processed: {len(results)}")
    logger.info(f"✅ Successful: {len(successful)}")
    logger.info(f"⊝ Skipped: {len(skipped)}")
    logger.info(f"❌ Failed: {len(failed)}")
    
    if failed:
        logger.info(f"\nFailed tickets:")
        for result in failed:
            logger.info(f"  - {result.ticket_key}: {result.error}")
    
    if skipped:
        logger.info(f"\nSkipped tickets:")
        for result in skipped:
            logger.info(f"  - {result.ticket_key}: {result.skipped_reason}")


@click.group()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.pass_context
def cli(ctx, config, verbose):
    """Augment - JIRA Automation Platform"""
    setup_logging(verbose)
    
    # Load configuration
    try:
        config_obj = Config(config)
        if not config_obj.validate():
            sys.exit(1)
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)
    
    ctx.obj = config_obj


@cli.command()
@click.argument('ticket_key')
@click.option('--dry-run', is_flag=True, help='Preview changes without updating (default mode)')
@click.option('--update', is_flag=True, help='Actually update the ticket')
@click.pass_context
def single(ctx, ticket_key, dry_run, update):
    """Process a single ticket"""
    config = ctx.obj
    logger = logging.getLogger(__name__)
    
    # Determine mode: if --update is specified, use live mode; otherwise use dry run
    if update:
        dry_run_mode = False
    else:
        # Default to dry run mode unless --update is explicitly specified
        dry_run_mode = True
    
    if dry_run_mode:
        logger.info("🔍 DRY RUN MODE - No tickets will be updated")
    else:
        logger.info("⚠️  LIVE MODE - Tickets will be updated!")
    
    # Create clients
    jira_client, bitbucket_client, confluence_client, llm_client = create_clients(config)
    
    # Test connections
    if not test_connections(jira_client, bitbucket_client, confluence_client, llm_client):
        sys.exit(1)
    
    # Create generator
    generator = DescriptionGenerator(
        jira_client=jira_client,
        bitbucket_client=bitbucket_client,
        confluence_client=confluence_client,
        llm_client=llm_client,
        prompt_template=config.prompts['description_template'],
        include_code_analysis=config.processing.get('include_code_analysis', True)
    )
    
    # Process the ticket
    result = generator.process_ticket(ticket_key, dry_run_mode)
    
    if result.success:
        logger.info(f"✅ Successfully processed {ticket_key}")
        if result.description:
            logger.info(f"\nGenerated description:\n{result.description.description}")
    elif result.skipped_reason:
        logger.info(f"⊝ Skipped {ticket_key}: {result.skipped_reason}")
    else:
        logger.error(f"❌ Failed to process {ticket_key}: {result.error}")
        sys.exit(1)


@cli.command()
@click.argument('jql')
@click.option('--dry-run', is_flag=True, help='Preview changes without updating (default mode)')
@click.option('--update', is_flag=True, help='Actually update tickets')
@click.option('--max-results', default=100, help='Maximum number of tickets to process')
@click.pass_context
def batch(ctx, jql, dry_run, update, max_results):
    """Process multiple tickets using JQL query"""
    config = ctx.obj
    logger = logging.getLogger(__name__)
    
    # Determine mode: if --update is specified, use live mode; otherwise use dry run
    if update:
        dry_run_mode = False
    else:
        # Default to dry run mode unless --update is explicitly specified
        dry_run_mode = True
    
    if dry_run_mode:
        logger.info("🔍 DRY RUN MODE - No tickets will be updated")
    else:
        logger.info("⚠️  LIVE MODE - Tickets will be updated!")
        response = click.confirm(f"Are you sure you want to update tickets matching: {jql}")
        if not response:
            logger.info("Operation cancelled")
            return
    
    # Create clients
    jira_client, bitbucket_client, confluence_client, llm_client = create_clients(config)
    
    # Test connections
    if not test_connections(jira_client, bitbucket_client, confluence_client, llm_client):
        sys.exit(1)
    
    # Create generator
    generator = DescriptionGenerator(
        jira_client=jira_client,
        bitbucket_client=bitbucket_client,
        confluence_client=confluence_client,
        llm_client=llm_client,
        prompt_template=config.prompts['description_template'],
        include_code_analysis=config.processing.get('include_code_analysis', True)
    )
    
    # Process tickets
    results = generator.process_batch(jql, dry_run_mode, max_results)
    
    # Print summary
    print_results_summary(results)




@cli.command()
@click.pass_context
def test(ctx):
    """Test API connections"""
    config = ctx.obj
    
    # Create clients
    jira_client, bitbucket_client, confluence_client, llm_client = create_clients(config)
    
    # Test connections
    success = test_connections(jira_client, bitbucket_client, confluence_client, llm_client)
    
    if success:
        click.echo("✅ All configured services are working!")
    else:
        click.echo("❌ Some services failed - check configuration")
        sys.exit(1)


if __name__ == '__main__':
    cli()
