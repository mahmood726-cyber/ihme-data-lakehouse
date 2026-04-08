"""Tests for CLI argument parsing and basic command routing."""
from ihme_data_lakehouse.cli import build_parser

def test_parser_fetch_domain():
    parser = build_parser()
    args = parser.parse_args(["fetch", "gbd_results", "--skip-existing"])
    assert args.command == "fetch"
    assert args.domain == "gbd_results"
    assert args.skip_existing is True
    assert args.check_only is False

def test_parser_fetch_all():
    parser = build_parser()
    args = parser.parse_args(["fetch", "--all"])
    assert args.all is True

def test_parser_promote_domain():
    parser = build_parser()
    args = parser.parse_args(["promote", "gbd_risk"])
    assert args.command == "promote"
    assert args.domain == "gbd_risk"

def test_parser_search():
    parser = build_parser()
    args = parser.parse_args(["search", "mortality", "--domain", "gbd_results"])
    assert args.keyword == "mortality"
    assert args.domain == "gbd_results"

def test_parser_status():
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"

def test_parser_registry_list():
    parser = build_parser()
    args = parser.parse_args(["registry-list"])
    assert args.command == "registry-list"
